"""Composite, explainable player score.

score = model_part (predicted Win-Probability-Added, role-weighted)
      + matchup_part (aggregate dismissal-history edge + style-specific edge
                      vs the opponent's actual pace/spin mix — see
                      features/style_matchup.py)
      + phase_fit_part (strength in their best phase, relative to teammates)
      + standing_part (proven track record: importance_score, ICC rank)
      + risk_part (eligibility/registry penalties)
      + team_need_part (synergy bonus for being strong in this specific
                        pool's neediest phase — only set by `score_many`,
                        see recommend/team_need.py; a lone `score()` call has
                        no pool to compare against, so it stays 0)

`model_part` is driven by predicted WPA (`criiq_data/wpa.py` — how much a
player's batting/bowling actually swings their team's win probability), not
contribution-share: contribution-share couldn't tell a proven match-winner
from a fringe player with a good-looking stat line in low-stakes matches — a
real case found this session had it ranking a part-time all-rounder above a
long-proven opener. WPA values are naturally tiny (a genuinely elite
match-winner might average +0.05 to +0.10 win-probability-added per match),
so they're rescaled by `SETTINGS.wpa_scale` to land in the same points range
the rest of the composite score uses — see that setting's docstring for how
the constant was chosen.

Every part is additive and stored in `components` alongside a non-additive
`inputs` sub-dict of the raw numbers behind them — mirrors the
`importance_score`/`importance_components` pattern already used in
`data-collection/criiq_data/impact.py`, so `/selection/explain` always has a
concrete, honest breakdown to show (including when the model was skipped
entirely for a low-sample player — cold start records
`components["model_applied"] = False` rather than silently blending noise).
"""
from __future__ import annotations

import sqlite3

import pandas as pd

from ..config import SETTINGS
from ..features.common import batting_capable, bowling_capable, shrink
from ..features.current import build_extra_context, build_model_features
from ..features.schema import MODEL_FEATURES
from ..features.style_matchup import style_matchup_edge
from ..roster import player_current_teams, team_pool
from .team_need import compute_team_need, player_team_need_bonus
from .train import load_metadata, load_models

# Fallback constants used only when the live data can't support an empirical
# prior (e.g. an entirely empty scope) — plausible T20 defaults, not tuned.
_FALLBACK_BATTING_WPA_PRIOR = 0.0
_FALLBACK_BOWLING_WPA_PRIOR = 0.0
_FALLBACK_DISMISSAL_RATE_PRIOR = 0.05


class RecommendationScorer:
    def __init__(self, conn: sqlite3.Connection, fmt: str = SETTINGS.format,
                 gender: str = SETTINGS.gender, models: dict | None = None):
        self.conn = conn
        self.fmt = fmt
        self.gender = gender
        # `load_models`/`load_metadata` are scoped by (fmt, gender) -- without
        # passing these through, a scorer constructed for gender="male" would
        # have silently loaded (and scored real male players with) whatever
        # model happened to be trained for the default gender instead.
        self.models = models if models is not None else load_models(fmt, gender)
        self.metadata = load_metadata(fmt, gender)
        self._priors = self._compute_priors()
        # keyed by opponent -- doesn't depend on the player being scored, so
        # scoring a whole pool against the same opponent (score_many) would
        # otherwise recompute it once per player for no reason.
        self._opponent_roster_cache: dict[str, list[str]] = {}

    def _opponent_roster(self, opponent: str) -> list[str]:
        if opponent not in self._opponent_roster_cache:
            self._opponent_roster_cache[opponent] = team_pool(
                self.conn, opponent, self.fmt, self.gender)
        return self._opponent_roster_cache[opponent]

    def _compute_priors(self) -> dict:
        scope_ids = player_current_teams(self.conn, self.fmt, self.gender)["player_id"]
        if scope_ids.empty:
            return {
                "batting_wpa": _FALLBACK_BATTING_WPA_PRIOR,
                "bowling_wpa": _FALLBACK_BOWLING_WPA_PRIOR,
                "dismissal_rate": _FALLBACK_DISMISSAL_RATE_PRIOR,
            }
        placeholders = ",".join("?" * len(scope_ids))
        wpa = pd.read_sql_query(
            f"SELECT batting_wpa, bowling_wpa FROM player_match_wpa "
            f"WHERE format=? AND player_id IN ({placeholders})",
            self.conn, params=(self.fmt, *scope_ids))
        career = pd.read_sql_query(
            f"SELECT bat_average, bat_strike_rate FROM player_career "
            f"WHERE format=? AND player_id IN ({placeholders}) "
            f"AND bat_average > 0 AND bat_strike_rate > 0",
            self.conn, params=(self.fmt, *scope_ids))
        dismissal_rates = (career["bat_strike_rate"] / (100 * career["bat_average"])) if len(career) else pd.Series(dtype=float)
        return {
            "batting_wpa": wpa["batting_wpa"].mean() if wpa["batting_wpa"].notna().any() else _FALLBACK_BATTING_WPA_PRIOR,
            "bowling_wpa": wpa["bowling_wpa"].mean() if wpa["bowling_wpa"].notna().any() else _FALLBACK_BOWLING_WPA_PRIOR,
            "dismissal_rate": dismissal_rates.mean() if len(dismissal_rates) else _FALLBACK_DISMISSAL_RATE_PRIOR,
        }

    def score(self, player_id: str, opponent: str, venue_id: str | None = None) -> dict:
        feats = build_model_features(self.conn, player_id, opponent, venue_id, self.fmt)
        ctx = build_extra_context(self.conn, player_id, opponent, self.fmt, self.gender,
                                   opponent_roster=self._opponent_roster(opponent), venue_id=venue_id)
        bucket = feats["role_bucket"] or ctx.role_bucket

        model_applied = (feats["career_matches"] or 0) >= SETTINGS.min_matches_for_model \
            and bool(self.models)
        predicted_batting_wpa, predicted_bowling_wpa = None, None
        if model_applied:
            row = pd.DataFrame([{f: feats[f] for f in MODEL_FEATURES}])
            if "batting_wpa" in self.models:
                predicted_batting_wpa = float(self.models["batting_wpa"].predict(row)[0])
            if "bowling_wpa" in self.models:
                predicted_bowling_wpa = float(self.models["bowling_wpa"].predict(row)[0])
        else:
            predicted_batting_wpa = shrink(feats["career_batting_wpa"], feats["career_batting_wpa_matches"],
                                            self._priors["batting_wpa"])
            predicted_bowling_wpa = shrink(feats["career_bowling_wpa"], feats["career_bowling_wpa_matches"],
                                            self._priors["bowling_wpa"])

        # pandas aggregates (career_*_wpa) are NaN, not None, when a player
        # has no rows for that discipline — normalize once so every
        # downstream check (and JSON output) sees a clean `None`.
        if pd.isna(predicted_batting_wpa):
            predicted_batting_wpa = None
        if pd.isna(predicted_bowling_wpa):
            predicted_bowling_wpa = None
        has_bat_data = pd.notna(feats["career_batting_wpa"])
        has_bowl_data = pd.notna(feats["career_bowling_wpa"])

        # Only credit a discipline the player's role suggests OR that they
        # have genuine (non-fabricated) history in — a shrink() call with no
        # observed data returns the bare prior, which must not be awarded to
        # e.g. a specialist batter's bowling axis just because it's nonzero.
        active_wpa = []
        if (batting_capable(bucket) or has_bat_data) and predicted_batting_wpa is not None:
            active_wpa.append(predicted_batting_wpa)
        if (bowling_capable(bucket) or has_bowl_data) and predicted_bowling_wpa is not None:
            active_wpa.append(predicted_bowling_wpa)
        active_wpa.sort(reverse=True)

        # A pure specialist only ever has one active discipline to sum, so a
        # plain sum structurally caps every specialist below any all-rounder
        # with two merely-decent disciplines — a genuinely elite batter could
        # never outscore a mediocre all-rounder on this alone. Instead, the
        # *primary* (best) discipline is credited at full weight, and any
        # secondary discipline adds a discounted bonus for genuine
        # versatility — real, but not enough to dominate raw excellence.
        primary = active_wpa[0] if active_wpa else 0.0
        secondary_bonus = sum(active_wpa[1:]) * SETTINGS.secondary_discipline_weight
        model_part = round(min(45.0, (primary + secondary_bonus) * SETTINGS.wpa_scale), 1)

        baseline_row = self.conn.execute(
            "SELECT bat_average, bat_strike_rate FROM player_career WHERE player_id=? AND format=?",
            (player_id, self.fmt)).fetchone()
        if baseline_row and baseline_row["bat_average"] and baseline_row["bat_strike_rate"]:
            career_dismissal_rate = baseline_row["bat_strike_rate"] / (100 * baseline_row["bat_average"])
        else:
            career_dismissal_rate = self._priors["dismissal_rate"]

        aggregate_matchup_part = 0.0
        if ctx.matchup_balls > 0:
            shrunk_rate = shrink(ctx.matchup_dismissal_rate, ctx.matchup_balls, career_dismissal_rate,
                                  prior_strength=SETTINGS.shrinkage_prior_matches * 6)
            aggregate_matchup_part = round(max(-8.0, min(8.0, (career_dismissal_rate - shrunk_rate) * 120)), 1)

        # Secondary, backup signal: opponent's actual pace/spin mix weighted
        # against the batter's own vs-style record (see features/style_matchup)
        # — smaller-magnitude than the aggregate signal above, and adds
        # nothing when either side's style data isn't known well enough.
        opponent_roster = self._opponent_roster(opponent)
        style = style_matchup_edge(self.conn, player_id, opponent, career_dismissal_rate,
                                    self.fmt, self.gender, opponent_roster=opponent_roster)

        # Symmetric bowling-side matchup: was entirely absent before -- a
        # specialist bowler rarely faces enough balls herself to ever get a
        # meaningful `aggregate_matchup_part` above (that's fundamentally a
        # *batting* signal), so bowlers previously scored with matchup_part
        # stuck near 0 regardless of how she's actually bowled against this
        # specific opponent's specific batters. Scale (175, vs the batting
        # side's 120) is calibrated against the real distribution of career
        # bowling wicket-rate (std ≈0.019 vs batting dismissal-rate's
        # std ≈0.028) so a one-std-dev edge reads as a comparably-sized bonus
        # on both axes, not copied blindly from the batting side.
        career_row = self.conn.execute(
            "SELECT wickets, balls_bowled FROM player_career WHERE player_id=? AND format=?",
            (player_id, self.fmt)).fetchone()
        career_bowl_wicket_rate = (career_row["wickets"] / career_row["balls_bowled"]
                                    if career_row and career_row["balls_bowled"] else None)
        bowl_matchup_part = 0.0
        if ctx.bowl_matchup_balls > 0 and career_bowl_wicket_rate is not None:
            shrunk_wicket_rate = shrink(ctx.bowl_matchup_wicket_rate, ctx.bowl_matchup_balls,
                                         career_bowl_wicket_rate,
                                         prior_strength=SETTINGS.shrinkage_prior_matches * 6)
            # Higher-than-career wicket rate against this specific opponent's
            # batters is GOOD for a bowler -- opposite polarity from the
            # batting side, where a LOWER dismissal rate is good.
            bowl_matchup_part = round(max(-8.0, min(8.0,
                (shrunk_wicket_rate - career_bowl_wicket_rate) * 175)), 1)

        matchup_part = round(aggregate_matchup_part + style["edge_part"] + bowl_matchup_part, 1)

        phase_fit_part = 0.0
        best_bat_pct = max(
            (v.get("bat_team_percentile") or 0 for v in ctx.phase_profile.values()), default=0)
        best_bowl_rank_score = 0.0
        for v in ctx.phase_profile.values():
            rank, size = v.get("bowl_team_rank"), v.get("bowl_team_size")
            if rank and size and size > 1:
                best_bowl_rank_score = max(best_bowl_rank_score, 1 - (rank - 1) / (size - 1))
        phase_fit_part = round(min(8.0, best_bat_pct / 100 * 4 + best_bowl_rank_score * 4), 1)

        standing_part = 0.0
        if ctx.importance_score is not None:
            standing_part += ctx.importance_score * 0.15
        if ctx.icc_rank is not None:
            standing_part += 5.0
        standing_part = round(min(20.0, standing_part), 1)

        risk_part = 0.0
        if ctx.age_advisory:
            risk_part -= 3.0
        if ctx.retirement_status == "INCONSISTENT":
            risk_part -= 5.0
        if ctx.retirement_status == "INACTIVE" and (ctx.recall_flag or ctx.recent_domestic_activity):
            risk_part -= 4.0
        risk_part = round(risk_part, 1)

        total = round(max(0.0, min(100.0, model_part + matchup_part + phase_fit_part
                                    + standing_part + risk_part)), 1)

        components = {
            "model_part": model_part, "matchup_part": matchup_part,
            "phase_fit_part": phase_fit_part, "standing_part": standing_part,
            "risk_part": risk_part,
            # Only ever set by `score_many` (a pool-wide, not per-player,
            # computation) — a lone `score()` call has no pool to compare
            # against, so these stay at their honest "not evaluated" default.
            "team_need_part": 0.0, "team_need_phase": None,
            "model_applied": model_applied,
            "cold_start_reason": None if model_applied else (
                "no_trained_model_available" if not self.models else
                f"career_matches ({feats['career_matches']}) < min_matches_for_model ({SETTINGS.min_matches_for_model})"),
            "inputs": {
                "career_matches": feats["career_matches"],
                "predicted_batting_wpa": round(predicted_batting_wpa, 4) if predicted_batting_wpa is not None else None,
                "predicted_bowling_wpa": round(predicted_bowling_wpa, 4) if predicted_bowling_wpa is not None else None,
                "vs_opponent_matches": feats["vs_opp_matches"],
                "venue_matches": feats["venue_matches"],
                # shrink()/shrink_series() can return pandas NaN (not None)
                # when both the raw observation and the prior it'd fall back
                # to are missing (a pure batter's bowling side, career-wide) —
                # normalize the same way bowl_dot_pct/bowl_boundary_pct below
                # already do, so explain.py never has to render a literal "nan%".
                "venue_bat_contribution_pct": None if pd.isna(feats["venue_bat_contribution_pct"]) else feats["venue_bat_contribution_pct"],
                "venue_bowl_contribution_pct": None if pd.isna(feats["venue_bowl_contribution_pct"]) else feats["venue_bowl_contribution_pct"],
                "venue_name": ctx.venue_name,
                "venue_setting_average": ctx.venue_setting_average,
                "venue_setting_strike_rate": ctx.venue_setting_strike_rate,
                "venue_chasing_average": ctx.venue_chasing_average,
                "venue_chasing_strike_rate": ctx.venue_chasing_strike_rate,
                "venue_bogey_bowler": ctx.venue_bogey_bowler,
                "domestic_form_matches": feats["domestic_form_matches"],
                "domestic_form_batting_wpa": feats["domestic_form_batting_wpa"],
                "domestic_form_bowling_wpa": feats["domestic_form_bowling_wpa"],
                "matchup_balls_vs_opponent_bowlers": ctx.matchup_balls,
                "matchup_dismissal_rate": ctx.matchup_dismissal_rate,
                "aggregate_matchup_part": aggregate_matchup_part,
                "style_matchup_available": style["available"],
                "style_matchup_part": style["edge_part"],
                "opponent_bowling_mix": style.get("opponent_bowling_mix"),
                "bowl_matchup_balls_vs_opponent_batters": ctx.bowl_matchup_balls,
                "bowl_matchup_wicket_rate": ctx.bowl_matchup_wicket_rate,
                "bowl_matchup_part": bowl_matchup_part,
                "importance_score": ctx.importance_score, "win_pct": ctx.win_pct,
                "icc_rank": ctx.icc_rank, "retirement_status": ctx.retirement_status,
                "status_reason": ctx.status_reason,
                "recall_flag": ctx.recall_flag,
                "recent_domestic_activity": ctx.recent_domestic_activity,
                "age_advisory": ctx.age_advisory,
                "is_keeper": ctx.is_keeper,
                # Descriptive only, not model inputs -- see features/current.py's
                # docstring on why these were tried as trained-model features
                # and dropped after checking against the real backtest. Pure
                # batters get pandas NaN (mean of an all-missing column), not
                # None, from build_model_features -- normalize the same way
                # predicted_batting_wpa/predicted_bowling_wpa already are above.
                "bowl_dot_pct": None if pd.isna(feats.get("career_bowl_dot_pct")) else feats["career_bowl_dot_pct"],
                "bowl_boundary_pct": None if pd.isna(feats.get("career_bowl_boundary_pct")) else feats["career_bowl_boundary_pct"],
                "archetype": ctx.archetype,
                "bowling_style": ctx.bowling_style,
                "batting_hand": ctx.batting_hand,
            },
        }

        return {
            "player_id": player_id, "name": ctx.name, "role_bucket": bucket,
            "is_keeper": ctx.is_keeper, "batting_position_median": ctx.batting_position_median,
            "opponent": opponent, "venue_id": venue_id, "score": total,
            "components": components,
        }

    def score_many(self, player_ids: list[str], opponent: str,
                    venue_id: str | None = None) -> list[dict]:
        """Scores every player, then applies a synergy-aware team-need bonus
        (see `recommend/team_need.py`) computed once across this whole pool —
        a player scored alone has no way to know "this team is thin on death
        bowling", only the pool as a whole does.
        """
        scored = [self.score(pid, opponent, venue_id) for pid in player_ids]

        team_need = compute_team_need(self.conn, player_ids, self.fmt, self.gender)
        for player in scored:
            need = player_team_need_bonus(self.conn, player["player_id"], team_need, self.fmt)
            player["components"]["team_need_part"] = need["bonus"]
            player["components"]["team_need_phase"] = need["phase"]
            if need["bonus"]:
                player["score"] = round(min(100.0, player["score"] + need["bonus"]), 1)
        return scored

"""composite, explainable player score.

adds up model_part (predicted WPA, role-weighted), matchup_part (dismissal
history + style edge vs the opponent's pace/spin mix), phase_fit_part (best
phase vs teammates), standing_part (importance score, ICC rank), risk_part
(eligibility penalties), and team_need_part (pool synergy bonus, set only by
score_many, see recommend/team_need.py).

model_part comes from predicted WPA (criiq_data/wpa.py), not contribution
share, since a contribution-share ranking once put a part-time all-rounder
above a long-proven opener. WPA is naturally tiny, so it's rescaled by
SETTINGS.wpa_scale to match the rest of the score's points range.

each part is stored in components, alongside a non-additive inputs dict of
the raw numbers behind them, mirroring the importance_score pattern in
data-collection/criiq_data/impact.py.
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

# fallback constants for when live data can't support an empirical prior,
# e.g. an empty scope. plausible T20 defaults, not tuned.
_FALLBACK_BATTING_WPA_PRIOR = 0.0
_FALLBACK_BOWLING_WPA_PRIOR = 0.0
_FALLBACK_DISMISSAL_RATE_PRIOR = 0.05


class RecommendationScorer:
    def __init__(self, conn: sqlite3.Connection, fmt: str = SETTINGS.format,
                 gender: str = SETTINGS.gender, models: dict | None = None):
        self.conn = conn
        self.fmt = fmt
        self.gender = gender
        # load_models/load_metadata are scoped by (fmt, gender), so pass these
        # through or a scorer could silently load the wrong gender's model.
        self.models = models if models is not None else load_models(fmt, gender)
        self.metadata = load_metadata(fmt, gender)
        self._priors = self._compute_priors()
        # keyed by opponent since it doesn't depend on the player, so
        # score_many doesn't recompute it per player.
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
        # gender-relative par SR for the penalty below: median career SR among
        # real batters (bat_average >= 15) so tailenders don't drag it down.
        real_batters = career[career["bat_average"] >= 15] if len(career) else career
        sr_benchmark = float(real_batters["bat_strike_rate"].median()) if len(real_batters) else None
        return {
            "batting_wpa": wpa["batting_wpa"].mean() if wpa["batting_wpa"].notna().any() else _FALLBACK_BATTING_WPA_PRIOR,
            "bowling_wpa": wpa["bowling_wpa"].mean() if wpa["bowling_wpa"].notna().any() else _FALLBACK_BOWLING_WPA_PRIOR,
            "dismissal_rate": dismissal_rates.mean() if len(dismissal_rates) else _FALLBACK_DISMISSAL_RATE_PRIOR,
            "batter_sr_benchmark": sr_benchmark,
        }

    def _game_awareness(self, feats: dict, ctx: "object") -> dict:
        """[0,1] game-awareness/experience factor, averaged over whichever
        signals are available. only used to scale down the strike-rate
        penalty, since an experienced player is trusted to bat slower.

        signals: career matches (experience), importance_score (big-moment
        impact), chasing SR vs gender par (composure), bat_consistency.
        """
        signals = {}
        matches = feats.get("career_matches") or 0
        signals["experience"] = min(1.0, matches / SETTINGS.experience_full_matches)
        if ctx.importance_score is not None:
            signals["big_moment"] = max(0.0, min(1.0, ctx.importance_score / 100.0))
        benchmark = self._priors.get("batter_sr_benchmark")
        if ctx.chasing_strike_rate is not None and benchmark:
            signals["chasing"] = max(0.0, min(1.0, ctx.chasing_strike_rate / benchmark))
        if ctx.bat_consistency is not None:
            signals["consistency"] = max(0.0, min(1.0, ctx.bat_consistency))
        factor = sum(signals.values()) / len(signals) if signals else 0.0
        return {"factor": round(factor, 3), "signals": {k: round(v, 3) for k, v in signals.items()}}

    def _strike_rate_penalty(self, feats: dict, ctx: "object", bucket: str) -> tuple[float, dict]:
        """soft penalty (<= 0) for a batting-capable player below the gender
        par strike rate, scaled down by game awareness. never a reward, never
        applied to pure bowlers.
        """
        awareness = self._game_awareness(feats, ctx)
        benchmark = self._priors.get("batter_sr_benchmark")
        career_sr = feats.get("career_bat_sr")
        if not batting_capable(bucket) or not benchmark or career_sr is None or pd.isna(career_sr) or career_sr <= 0:
            return 0.0, awareness
        if career_sr >= benchmark:
            return 0.0, awareness  # at or above par: no penalty
        shortfall = (benchmark - career_sr) / benchmark        # fraction below par, (0,1)
        raw = min(SETTINGS.sr_penalty_cap, shortfall * SETTINGS.sr_penalty_scale)
        penalty = -round(raw * (1.0 - awareness["factor"]), 1)  # awareness offsets it
        return penalty, awareness

    def score(self, player_id: str, opponent: str, venue_id: str | None = None,
              opponent_players: list[str] | None = None) -> dict:
        feats = build_model_features(self.conn, player_id, opponent, venue_id, self.fmt)
        ctx = build_extra_context(self.conn, player_id, opponent, self.fmt, self.gender,
                                   opponent_roster=self._opponent_roster(opponent), venue_id=venue_id,
                                   opponent_players=opponent_players)
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

        # pandas aggregates are NaN, not None, when a player has no rows for
        # that discipline, so normalize once to a clean None.
        if pd.isna(predicted_batting_wpa):
            predicted_batting_wpa = None
        if pd.isna(predicted_bowling_wpa):
            predicted_bowling_wpa = None
        has_bat_data = pd.notna(feats["career_batting_wpa"])
        has_bowl_data = pd.notna(feats["career_bowling_wpa"])

        # only credit a discipline the player's role suggests or has real
        # history in, since shrink() with no data just returns the bare prior.
        active_wpa = []
        if (batting_capable(bucket) or has_bat_data) and predicted_batting_wpa is not None:
            active_wpa.append(predicted_batting_wpa)
        if (bowling_capable(bucket) or has_bowl_data) and predicted_bowling_wpa is not None:
            active_wpa.append(predicted_bowling_wpa)
        active_wpa.sort(reverse=True)

        # a plain sum would cap every specialist below a mediocre all-rounder,
        # so the primary (best) discipline counts full and a second
        # discipline only adds a discounted bonus.
        primary = active_wpa[0] if active_wpa else 0.0
        secondary_bonus = sum(active_wpa[1:]) * SETTINGS.secondary_discipline_weight
        model_part = min(45.0, (primary + secondary_bonus) * SETTINGS.wpa_scale)
        # cold-start confidence discount: without this, a 3-match player who
        # bowled well against weak opposition could score a near-full
        # model_part. scale by how much history backs it, ramping to full
        # trust at min_matches_for_model.
        if not model_applied:
            confidence = min(1.0, (feats["career_matches"] or 0) / SETTINGS.min_matches_for_model)
            model_part *= confidence
        model_part = round(model_part, 1)

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

        # secondary signal: opponent's pace/spin mix vs the batter's vs-style
        # record (see features/style_matchup). scoped to the named XI if given, not the whole team.
        roster_for_style = opponent_players or self._opponent_roster(opponent)
        style = style_matchup_edge(self.conn, player_id, opponent, career_dismissal_rate,
                                    self.fmt, self.gender, opponent_roster=roster_for_style)

        # symmetric bowling-side matchup, since aggregate_matchup_part above
        # is fundamentally a batting signal and left bowlers stuck near 0.
        # scale (175 vs batting's 120) is tuned to the real wicket-rate std dev.
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
            # higher wicket rate here is good for a bowler, opposite polarity from the batting side
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

        strike_rate_part, awareness = self._strike_rate_penalty(feats, ctx, bucket)

        total = round(max(0.0, min(100.0, model_part + matchup_part + phase_fit_part
                                    + standing_part + risk_part + strike_rate_part)), 1)

        components = {
            "model_part": model_part, "matchup_part": matchup_part,
            "phase_fit_part": phase_fit_part, "standing_part": standing_part,
            "risk_part": risk_part, "strike_rate_part": strike_rate_part,
            # only set by score_many (pool-wide, not per-player), since a
            # lone score() call has no pool to compare against.
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
                # shrink() can return NaN, not None, when both the observation
                # and the prior are missing, so normalize like bowl_dot_pct below.
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
                # descriptive only, not model inputs, see features/current.py.
                # pure batters get NaN here, not None, so normalize like the wpa fields above.
                "bowl_dot_pct": None if pd.isna(feats.get("career_bowl_dot_pct")) else feats["career_bowl_dot_pct"],
                "bowl_boundary_pct": None if pd.isna(feats.get("career_bowl_boundary_pct")) else feats["career_bowl_boundary_pct"],
                "age_years": feats.get("age_years"),
                "archetype": ctx.archetype,
                "bowling_style": ctx.bowling_style,
                "batting_hand": ctx.batting_hand,
                "bat_balls": ctx.bat_balls,
                "bat_strike_rate": ctx.bat_strike_rate,
                "bat_boundary_pct": ctx.bat_boundary_pct,
                "bat_dot_pct": ctx.bat_dot_pct,
                "bat_sixes": ctx.bat_sixes,
                "bat_six_rate": ctx.bat_six_rate,
                "bat_best_phase": ctx.bat_best_phase,
                "bat_best_phase_sr": ctx.bat_best_phase_sr,
                "bat_best_phase_boundary_pct": ctx.bat_best_phase_boundary_pct,
                "career_bat_sr": None if pd.isna(feats.get("career_bat_sr")) else feats.get("career_bat_sr"),
                "sr_benchmark": self._priors.get("batter_sr_benchmark"),
                "chasing_strike_rate": ctx.chasing_strike_rate,
                "setting_strike_rate": ctx.setting_strike_rate,
                "bat_consistency": ctx.bat_consistency,
                "game_awareness_factor": awareness["factor"],
                "game_awareness_signals": awareness["signals"],
            },
        }

        return {
            "player_id": player_id, "name": ctx.name, "role_bucket": bucket,
            "is_keeper": ctx.is_keeper, "batting_position_median": ctx.batting_position_median,
            "opponent": opponent, "venue_id": venue_id, "score": total,
            "components": components,
        }

    def score_many(self, player_ids: list[str], opponent: str,
                    venue_id: str | None = None,
                    opponent_players: list[str] | None = None) -> list[dict]:
        """scores every player, then applies a synergy-aware team-need bonus
        computed once across the pool, since a lone player has no way to know
        the team is thin on death bowling.

        opponent_players: the opponent's named XI, if any, threaded to each
        score() call so matchups target exactly those players.
        """
        scored = [self.score(pid, opponent, venue_id, opponent_players=opponent_players)
                  for pid in player_ids]

        team_need = compute_team_need(self.conn, player_ids, self.fmt, self.gender)
        for player in scored:
            need = player_team_need_bonus(self.conn, player["player_id"], team_need, self.fmt)
            player["components"]["team_need_part"] = need["bonus"]
            player["components"]["team_need_phase"] = need["phase"]
            if need["bonus"]:
                player["score"] = round(min(100.0, player["score"] + need["bonus"]), 1)
        return scored

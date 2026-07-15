"""Live scoring feature builder — one player, "as of now".

Builds the same `MODEL_FEATURES` shape as `features/historical.py`, but with
no leakage concern: since we are scoring a genuinely unplayed future match,
using the player's *entire* history to date is correct (the historical
builder only restricts to "before this date" because it's manufacturing
training rows for *past* matches, where using the full history would leak
the future into the label).

Also assembles the extra context (`ExtraContext`) that `recommend/score.py`
needs for the parts of the composite score that are NOT part of the trained
model: opponent-bowler dismissal matchups, phase profile, track record,
and eligibility/risk — see `features/historical.py`'s docstring for why
matchup data isn't reconstructed for training.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import SETTINGS
from ..roster import team_pool
from .common import recency_weighted_mean, role_bucket, shrink
from .schema import MODEL_FEATURES


def resolve_role(conn: sqlite3.Connection, player_id: str, fmt: str) -> tuple[str, bool, float | None]:
    """(role_bucket, is_keeper, batting_position_median), preferring
    `player_role_final` — data-driven from batting position + ball-count
    workload, refined further for known international squads via
    Wikipedia-sourced keeper/role lookups (see data-collection's
    `role_finalize.py`) — over the noisier Wikidata-derived
    `player_registry.role` fallback, which is used only when a player has no
    `player_role_final` row at all (shouldn't happen once role-finalize has
    run, but a new player added since could lack one). Batting position has
    no registry-side fallback — it's simply absent if `player_role_final`
    hasn't been (re-)built since the player's matches were ingested.
    """
    final = conn.execute(
        "SELECT primary_role, is_keeper, batting_position_median FROM player_role_final "
        "WHERE player_id=? AND format=?", (player_id, fmt)).fetchone()
    if final and final["primary_role"]:
        return role_bucket(final["primary_role"]), bool(final["is_keeper"]), final["batting_position_median"]

    registry = conn.execute(
        "SELECT role FROM player_registry WHERE player_id=? AND format=?",
        (player_id, fmt)).fetchone()
    return role_bucket(registry["role"] if registry else None), False, None


def _player_match_history(conn: sqlite3.Connection, player_id: str, fmt: str) -> pd.DataFrame:
    hist = pd.read_sql_query(
        "SELECT pmi.date AS date, pmi.opponent AS opponent, pmi.won AS won, "
        "pmi.bat_strike_rate AS bat_strike_rate, pmi.bat_contribution_pct AS bat_contribution_pct, "
        "pmi.economy AS economy, pmi.wickets AS wickets, pmi.balls_bowled AS balls_bowled, "
        "pmi.bowl_contribution_pct AS bowl_contribution_pct, "
        "pmi.bowl_dot_pct AS bowl_dot_pct, pmi.bowl_boundary_pct AS bowl_boundary_pct, "
        "pw.batting_wpa AS batting_wpa, pw.bowling_wpa AS bowling_wpa, "
        "m.venue_id AS venue_id "
        "FROM player_match_impact pmi JOIN matches m ON pmi.match_id = m.match_id "
        "LEFT JOIN player_match_wpa pw ON pw.player_id = pmi.player_id "
        "AND pw.match_id = pmi.match_id AND pw.format = pmi.format "
        "WHERE pmi.player_id = ? AND pmi.format = ? ORDER BY pmi.date",
        conn, params=(player_id, fmt))
    # see features/historical.py: wickets is 0 (not NULL) for non-bowling
    # matches too, so it needs the same balls_bowled>0 mask before use.
    hist["wickets_when_bowled"] = hist["wickets"].where(hist["balls_bowled"] > 0)
    return hist


def build_model_features(conn: sqlite3.Connection, player_id: str, opponent: str,
                          venue_id: str | None, fmt: str = SETTINGS.format) -> dict:
    hist = _player_match_history(conn, player_id, fmt)
    row: dict = {f: None for f in MODEL_FEATURES}
    row["career_matches"] = len(hist)
    # Discipline-specific counts (not part of the trained model's feature
    # schema — used only by score.py to shrink bat/bowl contribution toward a
    # prior with the *right* sample size; a specialist bowler with 100 career
    # matches but 3 batting innings should shrink hard on the batting side).
    row["career_bat_matches"] = 0
    row["career_bowl_matches"] = 0
    row["career_batting_wpa_matches"] = 0
    row["career_bowling_wpa_matches"] = 0
    row["domestic_form_matches"] = 0

    # Age today -- no leakage concern (an objective fact, not derived from any
    # outcome); computed regardless of career history (even a debutant has an
    # age). Real coverage is partial (~36% of players have a known
    # date_of_birth via opt-in ESPNcricinfo enrichment), NaN otherwise, same
    # as historical.py's point-in-time version of this feature.
    dob_row = conn.execute(
        "SELECT date_of_birth FROM players WHERE player_id=?", (player_id,)).fetchone()
    if dob_row and dob_row["date_of_birth"]:
        try:
            dob = dt.date.fromisoformat(dob_row["date_of_birth"][:10])
            row["age_years"] = round((dt.date.today() - dob).days / 365.25, 1)
        except ValueError:
            pass

    if hist.empty:
        row["role_bucket"], _, _ = resolve_role(conn, player_id, fmt)
        return row

    row["career_bat_contribution_pct"] = hist["bat_contribution_pct"].mean()
    row["career_bowl_contribution_pct"] = hist["bowl_contribution_pct"].mean()
    row["career_bat_sr"] = hist["bat_strike_rate"].mean()
    row["career_bowl_economy"] = hist["economy"].mean()
    row["career_batting_wpa"] = hist["batting_wpa"].mean()
    row["career_bowling_wpa"] = hist["bowling_wpa"].mean()
    row["career_bowl_wickets_per_match"] = hist["wickets_when_bowled"].mean()
    # Descriptive only -- NOT in MODEL_FEATURES. Tried as trained-model inputs
    # (plus form_ variants and a balls-per-wicket strike rate) and checked
    # against the real temporal holdout: every one of them made the bowling
    # WPA model *worse* (correlation dropped from 0.103 to as low as 0.088 --
    # see model-training/README.md). Kept here only as plain-language color
    # for explain.py ("she builds pressure with a high dot-ball rate"), which
    # carries no such risk since it isn't fed back into a prediction.
    row["career_bowl_dot_pct"] = hist["bowl_dot_pct"].mean()
    row["career_bowl_boundary_pct"] = hist["bowl_boundary_pct"].mean()
    row["career_bat_matches"] = int(hist["bat_contribution_pct"].notna().sum())
    row["career_bowl_matches"] = int(hist["bowl_contribution_pct"].notna().sum())
    # Discipline-specific WPA sample sizes — used by score.py to shrink
    # career_batting_wpa/career_bowling_wpa toward a prior with the *right*
    # denominator, mirroring career_bat_matches/career_bowl_matches above.
    row["career_batting_wpa_matches"] = int(hist["batting_wpa"].notna().sum())
    row["career_bowling_wpa_matches"] = int(hist["bowling_wpa"].notna().sum())

    recent = hist.tail(SETTINGS.form_window_matches)
    order = pd.RangeIndex(len(recent))
    row["form_bat_contribution_pct"] = recency_weighted_mean(
        recent["bat_contribution_pct"], order, SETTINGS.form_recency_lambda)
    row["form_bowl_contribution_pct"] = recency_weighted_mean(
        recent["bowl_contribution_pct"], order, SETTINGS.form_recency_lambda)
    row["form_bat_sr"] = recency_weighted_mean(
        recent["bat_strike_rate"], order, SETTINGS.form_recency_lambda)
    row["form_bowl_economy"] = recency_weighted_mean(
        recent["economy"], order, SETTINGS.form_recency_lambda)
    row["form_batting_wpa"] = recency_weighted_mean(
        recent["batting_wpa"], order, SETTINGS.form_recency_lambda)
    row["form_bowling_wpa"] = recency_weighted_mean(
        recent["bowling_wpa"], order, SETTINGS.form_recency_lambda)
    row["form_bowl_wickets_per_match"] = recency_weighted_mean(
        recent["wickets_when_bowled"], order, SETTINGS.form_recency_lambda)

    # vs-opponent and venue records are the sparsest features (often 0-2
    # matches), so the raw mean is shrunk toward the career baseline exactly
    # like `features/historical.py` does for training — this is what makes
    # "no venue specified" (venue_matches=0) behave in-distribution: shrink()
    # with n=0 simply returns the career prior, the same continuous
    # degradation training rows see as venue_matches -> 0, instead of an
    # abrupt raw-mean-vs-missing cliff (confirmed via the Mandhana-vs-
    # Hemalatha sanity check to otherwise produce wildly unstable predictions).
    vs_opp = hist[hist["opponent"] == opponent]
    row["vs_opp_matches"] = len(vs_opp)
    row["vs_opp_bat_contribution_pct"] = shrink(
        vs_opp["bat_contribution_pct"].mean() if len(vs_opp) else None,
        len(vs_opp), row["career_bat_contribution_pct"])
    row["vs_opp_bowl_contribution_pct"] = shrink(
        vs_opp["bowl_contribution_pct"].mean() if len(vs_opp) else None,
        len(vs_opp), row["career_bowl_contribution_pct"])
    row["vs_opp_win_pct"] = 100 * vs_opp["won"].mean() if len(vs_opp) else None

    at_venue = hist[hist["venue_id"] == venue_id] if venue_id else hist.iloc[0:0]
    row["venue_matches"] = len(at_venue)
    row["venue_bat_contribution_pct"] = shrink(
        at_venue["bat_contribution_pct"].mean() if len(at_venue) else None,
        len(at_venue), row["career_bat_contribution_pct"])
    row["venue_bowl_contribution_pct"] = shrink(
        at_venue["bowl_contribution_pct"].mean() if len(at_venue) else None,
        len(at_venue), row["career_bowl_contribution_pct"])

    # Domestic form: no leakage concern here (unlike historical.py's
    # merge_asof reconstruction) -- data-collection's player_domestic_form is
    # already "current, as of the last refresh", so a live scoring query just
    # reads it directly. Same shrink-toward-international-career-baseline,
    # same effective-sample-size cap, as training.
    dom = conn.execute(
        "SELECT matches, batting_wpa_per_match, bowling_wpa_per_match "
        "FROM player_domestic_form WHERE player_id=? AND format=?", (player_id, fmt)).fetchone()
    if dom:
        row["domestic_form_matches"] = dom["matches"] or 0
        capped_n = min(row["domestic_form_matches"], SETTINGS.domestic_form_max_effective_matches)
        row["domestic_form_batting_wpa"] = shrink(
            dom["batting_wpa_per_match"], capped_n, row["career_batting_wpa"])
        row["domestic_form_bowling_wpa"] = shrink(
            dom["bowling_wpa_per_match"], capped_n, row["career_bowling_wpa"])

    row["role_bucket"], _, _ = resolve_role(conn, player_id, fmt)
    return row


@dataclass
class ExtraContext:
    name: str | None = None
    role_bucket: str = "unknown"
    is_keeper: bool = False
    batting_position_median: float | None = None
    matchup_balls: int = 0
    matchup_dismissal_rate: float | None = None   # dismissals per ball vs this opponent's bowlers
    matchup_runs_per_ball: float | None = None
    bowl_matchup_balls: int = 0
    bowl_matchup_wicket_rate: float | None = None  # wickets per ball vs this opponent's specific batters
    bowl_matchup_runs_per_ball: float | None = None
    phase_profile: dict = field(default_factory=dict)
    importance_score: float | None = None
    win_pct: float | None = None
    potm_rate: float | None = None
    icc_rank: int | None = None
    retirement_status: str | None = None
    status_reason: str | None = None
    recall_flag: bool = False
    recent_domestic_activity: bool = False
    age_advisory: bool = False
    selection_rate: float | None = None
    venue_name: str | None = None
    venue_setting_average: float | None = None
    venue_setting_strike_rate: float | None = None
    venue_chasing_average: float | None = None
    venue_chasing_strike_rate: float | None = None
    venue_bogey_bowler: dict | None = None  # this opponent's top dismisser of her, at this ground
    archetype: str | None = None  # data-collection's player_advanced.archetype (anchor/power hitter/finisher/balanced)
    bowling_style: str | None = None
    batting_hand: str | None = None
    # Descriptive batting profile (data-collection's player_advanced.profile_json,
    # batting block) -- "what to expect / where the impact is". Surfaced in
    # explain.py, never a model feature.
    bat_balls: int | None = None
    bat_strike_rate: float | None = None
    bat_boundary_pct: float | None = None
    bat_dot_pct: float | None = None
    bat_sixes: int | None = None
    bat_six_rate: float | None = None       # sixes per 100 balls
    bat_best_phase: str | None = None        # phase with this batter's highest strike rate
    bat_best_phase_sr: float | None = None
    bat_best_phase_boundary_pct: float | None = None


def build_extra_context(conn: sqlite3.Connection, player_id: str, opponent: str,
                         fmt: str = SETTINGS.format, gender: str = SETTINGS.gender,
                         opponent_roster: list[str] | None = None,
                         venue_id: str | None = None) -> ExtraContext:
    """`opponent_roster`: the opponent's current player_ids (`roster.team_pool`),
    pre-computed and passed in by callers scoring many players against the
    same opponent (e.g. `RecommendationScorer.score_many`) -- it doesn't
    depend on `player_id`, so recomputing it fresh per player scored would be
    pure waste. Computed internally when omitted (e.g. direct/test callers).
    """
    ctx = ExtraContext()

    name_row = conn.execute(
        "SELECT canonical_name FROM players WHERE player_id=?", (player_id,)).fetchone()
    ctx.name = name_row["canonical_name"] if name_row else None

    matchup = pd.read_sql_query(
        "SELECT balls, runs, dismissals FROM dismissal_matchup "
        "WHERE format=? AND batter_id=? AND bowler_team=?",
        conn, params=(fmt, player_id, opponent))
    if not matchup.empty and matchup["balls"].sum() > 0:
        balls = int(matchup["balls"].sum())
        ctx.matchup_balls = balls
        ctx.matchup_dismissal_rate = float(matchup["dismissals"].sum()) / balls
        ctx.matchup_runs_per_ball = float(matchup["runs"].sum()) / balls

    # Symmetric bowling-side matchup: how well THIS player has bowled against
    # the opponent's *specific current batters* (not the blunt "any batter,
    # any team" aggregate) -- was entirely missing before: dismissal_matchup
    # has no batting_team column, so unlike the batting axis above (which
    # filters by the stored bowler_team), opponent-scoping here goes through
    # the opponent's current roster membership on the batter_id side, same
    # roster lookup `features/style_matchup.py`'s opponent_bowling_mix uses.
    opponent_batters = opponent_roster if opponent_roster is not None else team_pool(conn, opponent, fmt, gender)
    if opponent_batters:
        placeholders = ",".join("?" * len(opponent_batters))
        bowl_matchup = pd.read_sql_query(
            f"SELECT balls, runs, dismissals FROM dismissal_matchup "
            f"WHERE format=? AND bowler_id=? AND batter_id IN ({placeholders})",
            conn, params=(fmt, player_id, *opponent_batters))
        if not bowl_matchup.empty and bowl_matchup["balls"].sum() > 0:
            balls = int(bowl_matchup["balls"].sum())
            ctx.bowl_matchup_balls = balls
            ctx.bowl_matchup_wicket_rate = float(bowl_matchup["dismissals"].sum()) / balls
            ctx.bowl_matchup_runs_per_ball = float(bowl_matchup["runs"].sum()) / balls

    phase_rows = conn.execute(
        "SELECT phase, bat_strike_rate, bat_team_percentile, bowl_economy, bowl_team_rank, "
        "bowl_team_size FROM player_phase WHERE player_id=? AND format=?",
        (player_id, fmt)).fetchall()
    ctx.phase_profile = {r["phase"]: dict(r) for r in phase_rows}

    if venue_id:
        vrow = conn.execute(
            "SELECT venue_name, setting_average, setting_strike_rate, "
            "chasing_average, chasing_strike_rate FROM player_by_venue "
            "WHERE player_id=? AND format=? AND venue_id=?",
            (player_id, fmt, venue_id)).fetchone()
        if vrow:
            ctx.venue_name = vrow["venue_name"]
            ctx.venue_setting_average = vrow["setting_average"]
            ctx.venue_setting_strike_rate = vrow["setting_strike_rate"]
            ctx.venue_chasing_average = vrow["chasing_average"]
            ctx.venue_chasing_strike_rate = vrow["chasing_strike_rate"]
        # This opponent's top dismisser of her, at this specific ground --
        # same `bowler_team=?` direct match the batting matchup above uses
        # (venue_dismissal_matchup stores it the same way dismissal_matchup
        # does), not a roster join.
        bogey = conn.execute(
            "SELECT bowler_name, bowler_team, dismissals, balls, runs "
            "FROM venue_dismissal_matchup WHERE batter_id=? AND format=? "
            "AND venue_id=? AND bowler_team=? ORDER BY dismissals DESC, balls DESC LIMIT 1",
            (player_id, fmt, venue_id, opponent)).fetchone()
        if bogey and bogey["dismissals"] > 0:
            ctx.venue_bogey_bowler = dict(bogey)

    impact = conn.execute(
        "SELECT importance_score, win_pct, potm_rate FROM player_impact "
        "WHERE player_id=? AND format=?", (player_id, fmt)).fetchone()
    if impact:
        ctx.importance_score = impact["importance_score"]
        ctx.win_pct = impact["win_pct"]
        ctx.potm_rate = impact["potm_rate"]

    ctx.role_bucket, ctx.is_keeper, ctx.batting_position_median = resolve_role(conn, player_id, fmt)

    registry = conn.execute(
        "SELECT retirement_status, recall_flag, age_advisory, selection_rate, icc_rank, "
        "status_reason, recent_domestic_activity FROM player_registry "
        "WHERE player_id=? AND format=?",
        (player_id, fmt)).fetchone()
    if registry:
        ctx.retirement_status = registry["retirement_status"]
        ctx.recall_flag = bool(registry["recall_flag"])
        ctx.age_advisory = bool(registry["age_advisory"])
        ctx.selection_rate = registry["selection_rate"]
        ctx.icc_rank = registry["icc_rank"]
        ctx.status_reason = registry["status_reason"]
        ctx.recent_domestic_activity = bool(registry["recent_domestic_activity"])

    style_row = conn.execute(
        "SELECT bowling_style, batting_hand FROM players WHERE player_id=?",
        (player_id,)).fetchone()
    if style_row:
        ctx.bowling_style = style_row["bowling_style"]
        ctx.batting_hand = style_row["batting_hand"]

    advanced = conn.execute(
        "SELECT archetype, profile_json FROM player_advanced WHERE player_id=? AND format=?",
        (player_id, fmt)).fetchone()
    if advanced:
        ctx.archetype = advanced["archetype"]
        _attach_batting_profile(ctx, advanced["profile_json"])

    return ctx


def _attach_batting_profile(ctx: "ExtraContext", profile_json: str | None) -> None:
    """Pull the descriptive batting block (strike rate / boundary% / dot% /
    sixes / per-phase splits) out of `player_advanced.profile_json` and onto
    the context, plus derive the batter's single strongest phase (highest
    strike rate among phases they've faced >= 30 balls in) -- the "best overs
    to play / where the impact is" signal. All descriptive: none of this
    feeds the score, only `explain.py`'s narrative.
    """
    if not profile_json:
        return
    try:
        bat = json.loads(profile_json).get("batting")
    except (ValueError, TypeError):
        return
    if not bat:
        return
    ctx.bat_balls = bat.get("balls")
    ctx.bat_strike_rate = bat.get("strike_rate")
    ctx.bat_boundary_pct = bat.get("boundary_pct")
    ctx.bat_dot_pct = bat.get("dot_pct")
    ctx.bat_sixes = bat.get("sixes")
    ctx.bat_six_rate = bat.get("six_rate")

    phases = bat.get("by_phase") or {}
    best = max(
        ((ph, v) for ph, v in phases.items()
         if (v.get("balls") or 0) >= 30 and v.get("strike_rate") is not None),
        key=lambda kv: kv[1]["strike_rate"], default=None)
    if best:
        ph, v = best
        ctx.bat_best_phase = ph
        ctx.bat_best_phase_sr = v.get("strike_rate")
        ctx.bat_best_phase_boundary_pct = v.get("boundary_pct")

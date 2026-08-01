"""point-in-time (leakage-safe) training feature table.

targets are batting_wpa/bowling_wpa (win probability actually added, see
criiq_data/wpa.py) rather than bat_contribution_pct/bowl_contribution_pct,
since contribution-share measures how big the numbers were, not whether they
moved the team toward winning. the contribution columns remain as features.

for each row of player_match_impact, reconstructs the feature groups that
would otherwise leak the label if pulled from the final aggregated tables
(those include the match itself and everything after it):

  * recent form: recency-weighted mean over the last N matches, strictly
    before this match's date
  * career-to-date: expanding mean over prior matches
  * opponent/venue-to-date: expanding mean restricted to prior matches
    against this opponent / at this venue

role bucket is pulled from the current player_registry snapshot as-is, since
role rarely changes within a career.

dismissal_matchup (batter-vs-bowler) is deliberately not reconstructed here:
it's a career total with no per-match granularity, so a point-in-time
version would need rebuilding from raw deliveries for an already sparse
signal. it's folded in at live-scoring time instead, as a separate matchup
edge component (see recommend/score.py).

age_years was tried as a model feature and rejected, it made holdout
correlation worse (see model-training/README.md). still computed at
live-scoring time (features/current.py) as descriptive context for
explain.py.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from ..config import SETTINGS
from .common import role_bucket, shrink_series
from .schema import CATEGORICAL_FEATURES, ID_COLUMNS, MODEL_FEATURES, TARGETS


def _weighted_recent(window: np.ndarray, decay: float) -> float:
    n = len(window)
    if n == 0:
        return np.nan
    vals = np.asarray(window, dtype=float)
    mask = ~np.isnan(vals)
    if not mask.any():
        return np.nan
    weights = decay ** np.arange(n - 1, -1, -1)
    w = weights[mask]
    v = vals[mask]
    return float((w * v).sum() / w.sum())


def _rolling_form(grouped_col: pd.Series, window: int, decay: float) -> pd.Series:
    return grouped_col.transform(
        lambda s: s.shift(1).rolling(window, min_periods=1)
        .apply(lambda a: _weighted_recent(a, decay), raw=True)
    )


def _attach_domestic_form(conn: sqlite3.Connection, df: pd.DataFrame, fmt: str) -> pd.DataFrame:
    """domestic form as of this international match's date. uses merge_asof,
    not a plain groupby/transform, since an international row isn't part of
    the domestic-only subgroup being rolled and wouldn't align back onto it.
    merge_asof(direction="backward") finds the most recent domestic
    checkpoint at or before that date for each international row.
    """
    empty_cols = {"domestic_form_matches": 0, "domestic_form_batting_wpa": None,
                  "domestic_form_bowling_wpa": None}
    domestic = pd.read_sql_query(
        "SELECT player_id, date, batting_wpa, bowling_wpa FROM player_match_wpa "
        "WHERE format=? AND team_type='club'", conn, params=(fmt,))
    if domestic.empty:
        return df.assign(**empty_cols)

    domestic["date"] = pd.to_datetime(domestic["date"], errors="coerce")
    domestic = domestic.dropna(subset=["date"]).sort_values(["player_id", "date"])
    dom_by_player = domestic.groupby("player_id")
    window, decay = SETTINGS.form_window_matches, SETTINGS.form_recency_lambda
    # not shifted: by the time a later international row looks this up via
    # merge_asof, it's already in the past for that row.
    domestic["domestic_form_batting_wpa"] = dom_by_player["batting_wpa"].transform(
        lambda s: s.rolling(window, min_periods=1).apply(lambda a: _weighted_recent(a, decay), raw=True))
    domestic["domestic_form_bowling_wpa"] = dom_by_player["bowling_wpa"].transform(
        lambda s: s.rolling(window, min_periods=1).apply(lambda a: _weighted_recent(a, decay), raw=True))
    domestic["domestic_form_matches"] = dom_by_player.cumcount() + 1

    # df["date"] stays a plain string throughout this module. merge_asof
    # needs a real datetime column, so join on a temporary one instead.
    df = df.reset_index(drop=True)
    df["_orig_order"] = df.index
    df["_date_dt"] = pd.to_datetime(df["date"], errors="coerce")
    left = df.sort_values("_date_dt")
    right = domestic.rename(columns={"date": "_date_dt"}).sort_values("_date_dt")[
        ["player_id", "_date_dt", "domestic_form_matches",
         "domestic_form_batting_wpa", "domestic_form_bowling_wpa"]]
    merged = pd.merge_asof(left, right, on="_date_dt", by="player_id", direction="backward")
    merged = merged.sort_values("_orig_order").reset_index(drop=True).drop(
        columns=["_orig_order", "_date_dt"])
    merged["domestic_form_matches"] = merged["domestic_form_matches"].fillna(0).astype(int)

    # shrink toward the player's own international career WPA, capped so no
    # amount of domestic volume can fully outweigh the international prior.
    capped_n = merged["domestic_form_matches"].clip(upper=SETTINGS.domestic_form_max_effective_matches)
    merged["domestic_form_batting_wpa"] = shrink_series(
        merged["domestic_form_batting_wpa"], capped_n, merged["career_batting_wpa"])
    merged["domestic_form_bowling_wpa"] = shrink_series(
        merged["domestic_form_bowling_wpa"], capped_n, merged["career_bowling_wpa"])
    return merged


def build_training_table(conn: sqlite3.Connection, fmt: str = SETTINGS.format,
                          gender: str = SETTINGS.gender) -> pd.DataFrame:
    pmi = pd.read_sql_query(
        "SELECT pmi.player_id, pmi.match_id, pmi.date, pmi.opponent, pmi.won, "
        "pmi.bat_strike_rate, pmi.bat_contribution_pct, pmi.economy, pmi.wickets, "
        "pmi.balls_bowled, pmi.bowl_contribution_pct, pw.batting_wpa, pw.bowling_wpa, m.venue_id "
        "FROM player_match_impact pmi "
        "JOIN matches m ON pmi.match_id = m.match_id "
        "LEFT JOIN player_match_wpa pw ON pw.player_id = pmi.player_id "
        "AND pw.match_id = pmi.match_id AND pw.format = pmi.format "
        "WHERE m.format = ? AND m.gender = ? AND pmi.date IS NOT NULL",
        conn, params=(fmt, gender))
    if pmi.empty:
        return pd.DataFrame(columns=ID_COLUMNS + MODEL_FEATURES + TARGETS)

    df = pmi.sort_values(["player_id", "date"]).reset_index(drop=True)
    # wickets is 0 (not NULL) even for matches she didn't bowl, unlike
    # economy/bowl_contribution_pct. mask by balls_bowled>0 so it describes
    # wicket-taking threat only when she actually bowls.
    df["wickets_when_bowled"] = df["wickets"].where(df["balls_bowled"] > 0)

    by_player = df.groupby("player_id")
    df["career_matches"] = by_player.cumcount()
    df["career_bat_contribution_pct"] = by_player["bat_contribution_pct"].transform(
        lambda s: s.shift(1).expanding().mean())
    df["career_bowl_contribution_pct"] = by_player["bowl_contribution_pct"].transform(
        lambda s: s.shift(1).expanding().mean())
    df["career_bat_sr"] = by_player["bat_strike_rate"].transform(
        lambda s: s.shift(1).expanding().mean())
    df["career_bowl_economy"] = by_player["economy"].transform(
        lambda s: s.shift(1).expanding().mean())
    df["career_batting_wpa"] = by_player["batting_wpa"].transform(
        lambda s: s.shift(1).expanding().mean())
    df["career_bowling_wpa"] = by_player["bowling_wpa"].transform(
        lambda s: s.shift(1).expanding().mean())
    df["career_bowl_wickets_per_match"] = by_player["wickets_when_bowled"].transform(
        lambda s: s.shift(1).expanding().mean())

    window, decay = SETTINGS.form_window_matches, SETTINGS.form_recency_lambda
    df["form_bat_contribution_pct"] = _rolling_form(by_player["bat_contribution_pct"], window, decay)
    df["form_bowl_contribution_pct"] = _rolling_form(by_player["bowl_contribution_pct"], window, decay)
    df["form_bat_sr"] = _rolling_form(by_player["bat_strike_rate"], window, decay)
    df["form_bowl_economy"] = _rolling_form(by_player["economy"], window, decay)
    df["form_batting_wpa"] = _rolling_form(by_player["batting_wpa"], window, decay)
    df["form_bowling_wpa"] = _rolling_form(by_player["bowling_wpa"], window, decay)
    df["form_bowl_wickets_per_match"] = _rolling_form(by_player["wickets_when_bowled"], window, decay)

    # vs-opponent and venue records are sparse (often 0-2 matches), so shrink
    # the raw expanding means toward the career baseline (see
    # shrink_series's docstring) to keep venue_matches=0 in-distribution.
    by_opp = df.groupby(["player_id", "opponent"])
    df["vs_opp_matches"] = by_opp.cumcount()
    raw_vs_opp_bat = by_opp["bat_contribution_pct"].transform(lambda s: s.shift(1).expanding().mean())
    raw_vs_opp_bowl = by_opp["bowl_contribution_pct"].transform(lambda s: s.shift(1).expanding().mean())
    df["vs_opp_bat_contribution_pct"] = shrink_series(
        raw_vs_opp_bat, df["vs_opp_matches"], df["career_bat_contribution_pct"])
    df["vs_opp_bowl_contribution_pct"] = shrink_series(
        raw_vs_opp_bowl, df["vs_opp_matches"], df["career_bowl_contribution_pct"])
    df["vs_opp_win_pct"] = by_opp["won"].transform(
        lambda s: 100 * s.shift(1).expanding().mean())

    by_venue = df.groupby(["player_id", "venue_id"])
    df["venue_matches"] = by_venue.cumcount()
    raw_venue_bat = by_venue["bat_contribution_pct"].transform(lambda s: s.shift(1).expanding().mean())
    raw_venue_bowl = by_venue["bowl_contribution_pct"].transform(lambda s: s.shift(1).expanding().mean())
    df["venue_bat_contribution_pct"] = shrink_series(
        raw_venue_bat, df["venue_matches"], df["career_bat_contribution_pct"])
    df["venue_bowl_contribution_pct"] = shrink_series(
        raw_venue_bowl, df["venue_matches"], df["career_bowl_contribution_pct"])

    df = _attach_domestic_form(conn, df, fmt)

    # prefer player_role_final over the noisier player_registry.role
    # fallback, same as features/current.py at scoring time, since train and
    # score must agree on how role_bucket is derived.
    registry_roles = pd.read_sql_query(
        "SELECT player_id, role FROM player_registry WHERE format = ?", conn, params=(fmt,))
    registry_roles["registry_role_bucket"] = registry_roles["role"].map(role_bucket)
    final_roles = pd.read_sql_query(
        "SELECT player_id, primary_role FROM player_role_final WHERE format = ?", conn, params=(fmt,))

    roles = registry_roles.merge(final_roles, on="player_id", how="left")
    roles["role_bucket"] = roles["primary_role"].fillna(roles["registry_role_bucket"]).map(role_bucket)
    df = df.merge(roles[["player_id", "role_bucket"]], on="player_id", how="left")
    df["role_bucket"] = df["role_bucket"].fillna("unknown").astype("category")
    for col in CATEGORICAL_FEATURES:
        if col != "role_bucket":
            df[col] = df[col].astype("category")

    return df[ID_COLUMNS + MODEL_FEATURES + TARGETS]

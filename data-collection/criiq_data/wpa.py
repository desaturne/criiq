"""Win-Probability-Added (WPA) — per-player, per-match, per-phase.

Contribution-share (`bat_contribution_pct`/`bowl_contribution_pct`, the
recommendation engine's original regression target) measures how *big* a
player's numbers were, not whether they mattered to winning. A 30-run cameo
that turns a losing chase around and a 30-run innings in a dead rubber look
identical to contribution-share; they are not remotely the same value to a
selector. WPA fixes this by crediting each ball's swing in P(win) — scored by
the already-fitted `EmpiricalWinProb` model (`winprob.py`) — to whoever was
actually on strike or bowling at that ball.

Ball-by-ball state is rebuilt here rather than reused from
`ml_features.build_ball_state_for_format`'s output, because that table
deliberately excludes player identity (it's *training data for the win-prob
model itself*, kept player-agnostic by design). Everything else about the
reconstruction — sort order, cumulative score/wickets/balls, phase bucketing —
is identical to that function on purpose, so the two stay consistent; only the
extra `striker`/`non_striker`/`bowler` columns are new here.

Attribution: the striker is credited `delta_wp` (this ball's
`win_prob_batting` minus the previous ball's, within the same match+innings)
on the **batting** axis; the bowler is credited `-delta_wp` on the **bowling**
axis (the bowling team's probability moved the opposite way — win_prob_batting
and win_prob_bowling are complements by construction). The non-striker gets
nothing — the standard WPA convention; crediting a rare non-striker run-out to
the wrong end is a smaller, more honest error than guessing which end was
involved (Cricsheet's ball-by-ball export doesn't say).
"""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from .config import SETTINGS, enabled_sources
from .db import set_meta
from .identity import resolve_player_ids
from .logging_utils import get_logger
from .ml_features import T20_BALLS
from .winprob import EmpiricalWinProb

log = get_logger("wpa")


def _phase(over: int) -> str:
    if over <= 5:
        return "powerplay"
    if over <= 14:
        return "middle"
    return "death"


def _build_ball_state_with_players(conn, fmt: str) -> pd.DataFrame:
    # Deliberately every team_type: domestic matches are *scored* by the
    # already-fitted (international-only-trained) win-probability model, the
    # same way an international match is -- see build_wpa_for_format's
    # docstring on why that's a reasonable reuse, not a new assumption.
    d = pd.read_sql_query(
        "SELECT d.match_id, d.innings, d.over, d.ball_in_over, d.striker, "
        "d.non_striker, d.bowler, d.runs_total, d.wides, d.noballs, "
        "d.player_dismissed, m.gender FROM deliveries d JOIN matches m ON d.match_id = m.match_id "
        "WHERE m.format = ?", conn, params=(fmt,))
    if d.empty:
        return d
    d = d.sort_values(["match_id", "innings", "over", "ball_in_over"]).reset_index(drop=True)
    g = d.groupby(["match_id", "innings"])
    d["legal"] = ((d["wides"].fillna(0) == 0) & (d["noballs"].fillna(0) == 0)).astype(int)
    d["runs_total"] = d["runs_total"].fillna(0).astype(int)
    d["score"] = g["runs_total"].cumsum()
    d["balls_bowled"] = g["legal"].cumsum()
    d["wkt"] = d["player_dismissed"].notna().astype(int)
    d["wickets"] = g["wkt"].cumsum()
    d["balls_remaining"] = (T20_BALLS - d["balls_bowled"]).clip(lower=0)
    d["phase"] = d["over"].apply(_phase)

    inn1_totals = d[d["innings"] == 1].groupby("match_id")["score"].max()
    d["target"] = d["match_id"].map(inn1_totals) + 1
    chase = d["innings"] == 2
    d["target"] = d["target"].where(chase)
    d["runs_required"] = (d["target"] - d["score"]).where(chase)
    return d


def _win_prob_inputs(d: pd.DataFrame) -> pd.DataFrame:
    return d[["innings", "wickets", "balls_remaining", "runs_required", "balls_bowled", "score"]]


def _starting_state_wp(model: EmpiricalWinProb, d: pd.DataFrame) -> pd.DataFrame:
    """P(batting team wins) at the true 0-0 start of each (match, innings) —
    the "previous" state for every innings' first ball, which has no prior row.
    """
    start = d.groupby(["match_id", "innings"], as_index=False).first().copy()
    start["score"] = 0
    start["wickets"] = 0
    start["balls_bowled"] = 0
    start["balls_remaining"] = T20_BALLS
    chase = start["innings"] == 2
    start["runs_required"] = start["target"].where(chase)
    start["wp"] = model.predict(_win_prob_inputs(start))
    return start[["match_id", "innings", "wp"]]


def compute_ball_wpa(conn, fmt: str) -> pd.DataFrame:
    """One row per delivery, with `delta_wp`, `striker`, `bowler`, `phase` —
    the building block both aggregate tables are computed from.
    """
    d = _build_ball_state_with_players(conn, fmt)
    if d.empty:
        return d
    model = EmpiricalWinProb.load(fmt)
    d["win_prob_batting"] = model.predict(_win_prob_inputs(d))

    g = d.groupby(["match_id", "innings"])
    d["prev_wp"] = g["win_prob_batting"].shift(1)
    missing = d["prev_wp"].isna()
    start_wp = _starting_state_wp(model, d)
    filled = d.loc[missing, ["match_id", "innings"]].merge(
        start_wp, on=["match_id", "innings"], how="left")["wp"]
    d.loc[missing, "prev_wp"] = filled.to_numpy()
    d["delta_wp"] = d["win_prob_batting"] - d["prev_wp"]
    return d


def _name_to_ident(conn) -> dict[str, str]:
    return {r["player_name"]: r["identifier"]
            for r in conn.execute("SELECT player_name, identifier FROM identifier_map")}


def _resolve_ids_by_name(conn, names: pd.Series, genders: pd.Series, name2ident: dict) -> pd.Series:
    """name -> player_id, gender-aware for the handful of Cricsheet registry
    identifiers reused across two genuinely different people of different
    genders (see identity.py's `_colliding_identifiers`) -- WITHOUT this, a
    men's-match delivery and a women's-match delivery for a colliding
    identifier would get their win-probability swings blended into the same
    player's WPA, corrupting exactly the metric this whole engine predicts.
    """
    idents = names.map(name2ident)
    return resolve_player_ids(conn, idents, genders)


def build_wpa_for_format(conn, fmt: str) -> dict:
    balls = compute_ball_wpa(conn, fmt)
    if balls.empty:
        log.info("wpa %s: no ball data", fmt)
        return {"format": fmt, "player_matches": 0}

    name2ident = _name_to_ident(conn)
    balls["striker_id"] = _resolve_ids_by_name(conn, balls["striker"], balls["gender"], name2ident)
    balls["bowler_id"] = _resolve_ids_by_name(conn, balls["bowler"], balls["gender"], name2ident)

    bat_events = balls.dropna(subset=["striker_id"])[
        ["match_id", "striker_id", "phase", "delta_wp"]
    ].rename(columns={"striker_id": "player_id", "delta_wp": "wpa"})
    bat_events["axis"] = "batting"

    bowl_events = balls.dropna(subset=["bowler_id"])[
        ["match_id", "bowler_id", "phase", "delta_wp"]
    ].rename(columns={"bowler_id": "player_id", "delta_wp": "wpa"})
    bowl_events["wpa"] = -bowl_events["wpa"]
    bowl_events["axis"] = "bowling"

    events = pd.concat([bat_events, bowl_events], ignore_index=True)

    # match_id -> team/opponent/date/team_type, for player_match_wpa's context
    # columns -- team_type is what lets player_domestic_form (below) separate
    # domestic matches back out again without a second ball-by-ball pass.
    match_info = pd.read_sql_query(
        "SELECT match_id, date, team1, team2, team_type FROM matches WHERE format=?",
        conn, params=(fmt,))
    mp = pd.read_sql_query(
        "SELECT mp.match_id, mp.player_name, mp.team, m.gender FROM match_players mp "
        "JOIN matches m ON m.match_id = mp.match_id WHERE m.format=?", conn, params=(fmt,))
    mp["player_id"] = _resolve_ids_by_name(conn, mp["player_name"], mp["gender"], name2ident)
    mp = mp.dropna(subset=["player_id"])[["match_id", "player_id", "team"]].drop_duplicates()

    now = dt.datetime.now().isoformat(timespec="seconds")

    # --- player_match_wpa --------------------------------------------------
    per_match_axis = events.groupby(["match_id", "player_id", "axis"])["wpa"].sum().unstack(
        fill_value=0.0).reset_index()
    for col in ("batting", "bowling"):
        if col not in per_match_axis.columns:
            per_match_axis[col] = 0.0

    phase_breakdown = (events.groupby(["match_id", "player_id", "phase", "axis"])["wpa"]
                       .sum().reset_index())

    match_rows = per_match_axis.merge(mp, on=["match_id", "player_id"], how="left")
    match_rows = match_rows.merge(match_info, on="match_id", how="left")
    match_rows["opponent"] = match_rows.apply(
        lambda r: r["team2"] if r["team"] == r["team1"] else r["team1"], axis=1)

    phase_json_by_key: dict[tuple, dict] = {}
    for r in phase_breakdown.itertuples(index=False):
        key = (r.match_id, r.player_id)
        phase_json_by_key.setdefault(key, {})
        phase_json_by_key[key].setdefault(r.phase, {})[r.axis] = round(float(r.wpa), 5)

    match_wpa_rows = []
    for r in match_rows.itertuples(index=False):
        key = (r.match_id, r.player_id)
        match_wpa_rows.append((
            r.player_id, r.match_id, fmt, r.date, r.team, r.opponent, r.team_type,
            round(float(r.batting), 5), round(float(r.bowling), 5),
            json.dumps(phase_json_by_key.get(key, {})), now,
        ))

    conn.executemany(
        "INSERT INTO player_match_wpa(player_id, match_id, format, date, team, opponent, "
        "team_type, batting_wpa, bowling_wpa, phase_breakdown_json, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id, match_id) DO UPDATE SET "
        "team=excluded.team, opponent=excluded.opponent, team_type=excluded.team_type, "
        "batting_wpa=excluded.batting_wpa, "
        "bowling_wpa=excluded.bowling_wpa, phase_breakdown_json=excluded.phase_breakdown_json, "
        "updated_at=excluded.updated_at", match_wpa_rows)

    # --- player_phase_wpa (career aggregate) -------------------------------
    # International-only, like player_career/player_impact -- this is the
    # "career phase value" signal model-training reads; blending in domestic
    # matches here would corrupt it the same way it would corrupt a career
    # batting average. Domestic gets its own aggregate below instead.
    match_team_type = dict(zip(match_info["match_id"], match_info["team_type"]))
    events_intl = events[events["match_id"].map(match_team_type) == "international"]
    phase_matches = (events_intl.groupby(["player_id", "phase"])["match_id"]
                     .nunique().rename("matches").reset_index())
    phase_totals = (events_intl.groupby(["player_id", "phase", "axis"])["wpa"]
                    .sum().unstack(fill_value=0.0).reset_index())
    for col in ("batting", "bowling"):
        if col not in phase_totals.columns:
            phase_totals[col] = 0.0
    phase_summary = phase_matches.merge(phase_totals, on=["player_id", "phase"], how="left")

    phase_rows = [
        (r.player_id, fmt, r.phase, int(r.matches),
         round(float(r.batting) / r.matches, 5) if r.matches else None,
         round(float(r.bowling) / r.matches, 5) if r.matches else None, now)
        for r in phase_summary.itertuples(index=False)
    ]
    conn.executemany(
        "INSERT INTO player_phase_wpa(player_id, format, phase, matches, "
        "batting_wpa_per_match, bowling_wpa_per_match, updated_at) VALUES(?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id, format, phase) DO UPDATE SET "
        "matches=excluded.matches, batting_wpa_per_match=excluded.batting_wpa_per_match, "
        "bowling_wpa_per_match=excluded.bowling_wpa_per_match, updated_at=excluded.updated_at",
        phase_rows)

    conn.commit()
    log.info("wpa %s: %d player-match rows, %d player-phase rows",
              fmt, len(match_wpa_rows), len(phase_rows))
    return {"format": fmt, "player_matches": len(match_wpa_rows), "player_phases": len(phase_rows)}


def build_domestic_form_for_format(conn, fmt: str) -> int:
    """Recent-N domestic-only matches' average WPA per player -- the signal
    that lets someone quiet internationally but genuinely in-form
    domestically show it, without touching the international-only
    player_career/player_impact/player_phase_wpa tables at all. Reads
    `player_match_wpa` (already tagged by team_type in build_wpa_for_format),
    not raw deliveries -- no second ball-by-ball pass needed.
    """
    rows = pd.read_sql_query(
        "SELECT player_id, date, batting_wpa, bowling_wpa FROM player_match_wpa "
        "WHERE format=? AND team_type='club' ORDER BY player_id, date",
        conn, params=(fmt,))
    if rows.empty:
        log.info("domestic_form %s: no domestic matches", fmt)
        return 0

    n = SETTINGS.impact_recent_matches
    recent = rows.groupby("player_id").tail(n)
    now = dt.datetime.now().isoformat(timespec="seconds")
    out_rows = []
    for pid, g in recent.groupby("player_id"):
        matches = len(g)
        out_rows.append((
            pid, fmt, matches,
            round(float(g["batting_wpa"].mean()), 5),
            round(float(g["bowling_wpa"].mean()), 5),
            g["date"].max(), now,
        ))
    conn.executemany(
        "INSERT INTO player_domestic_form(player_id, format, matches, "
        "batting_wpa_per_match, bowling_wpa_per_match, last_match_date, updated_at) "
        "VALUES(?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id, format) DO UPDATE SET "
        "matches=excluded.matches, batting_wpa_per_match=excluded.batting_wpa_per_match, "
        "bowling_wpa_per_match=excluded.bowling_wpa_per_match, "
        "last_match_date=excluded.last_match_date, updated_at=excluded.updated_at",
        out_rows)
    conn.commit()
    log.info("domestic_form %s: %d players", fmt, len(out_rows))
    return len(out_rows)


def build_wpa(conn) -> dict:
    out = {}
    for fmt in sorted({s.fmt for s in enabled_sources()}):
        out[fmt] = build_wpa_for_format(conn, fmt)
        build_domestic_form_for_format(conn, fmt)
    set_meta(conn, "wpa_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out

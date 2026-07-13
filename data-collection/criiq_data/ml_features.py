from __future__ import annotations

import datetime as dt

import pandas as pd

from .config import FEATURES_DIR, enabled_sources
from .db import set_meta
from .identity import resolve_player_ids
from .logging_utils import get_logger
from .stats import build_innings

log = get_logger("ml")

T20_BALLS = 120


def _formats() -> list[str]:
    return sorted({s.fmt for s in enabled_sources()})


def _team_totals(conn, fmt: str) -> dict:
    tot = pd.read_sql_query(
        "SELECT d.match_id, d.batting_team AS team, SUM(d.runs_total) AS runs "
        "FROM deliveries d JOIN matches m ON d.match_id=m.match_id "
        "WHERE m.format=? GROUP BY d.match_id, d.batting_team", conn, params=(fmt,))
    return {(r.match_id, r.team): int(r.runs) for r in tot.itertuples()}


def _team_wickets(conn, fmt: str) -> dict:
    tw = pd.read_sql_query(
        "SELECT d.match_id, d.bowling_team AS team, "
        "SUM(CASE WHEN d.player_dismissed IS NOT NULL THEN 1 ELSE 0 END) AS w "
        "FROM deliveries d JOIN matches m ON d.match_id=m.match_id "
        "WHERE m.format=? GROUP BY d.match_id, d.bowling_team", conn, params=(fmt,))
    return {(r.match_id, r.team): int(r.w) for r in tw.itertuples()}


def build_match_features_for_format(conn, fmt: str) -> int:
    matches = pd.read_sql_query(
        "SELECT match_id, date, gender, team1, team2, winner, toss_winner, "
        "toss_decision, venue_id FROM matches WHERE format=?", conn, params=(fmt,))
    if matches.empty:
        return 0
    totals = _team_totals(conn, fmt)
    inn1 = pd.read_sql_query(
        "SELECT d.match_id, MIN(d.batting_team) AS bat_first FROM deliveries d "
        "JOIN matches m ON d.match_id=m.match_id WHERE m.format=? AND d.innings=1 "
        "GROUP BY d.match_id", conn, params=(fmt,))
    bat_first = dict(zip(inn1["match_id"], inn1["bat_first"]))

    matches["date"] = pd.to_datetime(matches["date"], errors="coerce")
    rows = []
    for m in matches.itertuples(index=False):
        for team, opp, is_t1 in ((m.team1, m.team2, 1), (m.team2, m.team1, 0)):
            won = 1 if m.winner == team else (0 if m.winner == opp else None)
            rows.append({
                "match_id": m.match_id, "date": m.date, "team": team, "opp": opp,
                "is_team1": is_t1, "scored": totals.get((m.match_id, team)),
                "conceded": totals.get((m.match_id, opp)), "won": won})
    long = pd.DataFrame(rows).sort_values(["date", "match_id"])

    g = long.groupby("team")
    long["form_winpct"] = g["won"].transform(lambda s: s.shift().rolling(10, min_periods=1).mean())
    long["avg_score"] = g["scored"].transform(lambda s: s.shift().rolling(10, min_periods=1).mean())
    long["avg_conceded"] = g["conceded"].transform(lambda s: s.shift().rolling(10, min_periods=1).mean())
    long["form_n"] = g["won"].transform(lambda s: s.shift().rolling(10, min_periods=1).count())
    long["h2h_winpct"] = long.groupby(["team", "opp"])["won"].transform(
        lambda s: s.shift().expanding().mean())

    t1 = long[long["is_team1"] == 1].set_index("match_id")
    t2 = long[long["is_team1"] == 0].set_index("match_id")
    now = dt.datetime.now().isoformat(timespec="seconds")

    def _f(v):
        return None if v is None or pd.isna(v) else round(float(v), 3)

    out = []
    for m in matches.itertuples(index=False):
        if m.match_id not in t1.index or m.match_id not in t2.index:
            continue
        a, b = t1.loc[m.match_id], t2.loc[m.match_id]
        bf = bat_first.get(m.match_id)
        label = None if a["won"] is None or pd.isna(a["won"]) else int(a["won"])
        out.append((
            m.match_id, fmt, m.gender,
            m.date.date().isoformat() if pd.notna(m.date) else None, m.venue_id,
            m.team1, m.team2, m.toss_winner, m.toss_decision, bf,
            1 if m.toss_winner == m.team1 else 0,
            1 if bf == m.team1 else 0,
            int(a["form_n"]) if pd.notna(a["form_n"]) else 0,
            _f(a["form_winpct"]), _f(b["form_winpct"]),
            _f(a["avg_score"]), _f(b["avg_score"]),
            _f(a["avg_conceded"]), _f(b["avg_conceded"]), _f(a["h2h_winpct"]),
            _f((a["form_winpct"] or 0) - (b["form_winpct"] or 0))
            if pd.notna(a["form_winpct"]) and pd.notna(b["form_winpct"]) else None,
            _f((a["avg_score"] or 0) - (b["avg_score"] or 0))
            if pd.notna(a["avg_score"]) and pd.notna(b["avg_score"]) else None,
            label, "result" if m.winner else "no_result", now))

    conn.executemany(
        "INSERT INTO match_features(match_id, format, gender, date, venue_id, team1, "
        "team2, toss_winner, toss_decision, bat_first_team, toss_winner_is_team1, "
        "team1_bat_first, form_matches, team1_form_winpct, team2_form_winpct, "
        "team1_avg_score, team2_avg_score, team1_avg_conceded, team2_avg_conceded, "
        "h2h_team1_winpct, winpct_diff, avg_score_diff, label_team1_won, result_type, "
        "updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(match_id) DO UPDATE SET "
        "team1_form_winpct=excluded.team1_form_winpct, team2_form_winpct=excluded.team2_form_winpct, "
        "team1_avg_score=excluded.team1_avg_score, team2_avg_score=excluded.team2_avg_score, "
        "team1_avg_conceded=excluded.team1_avg_conceded, team2_avg_conceded=excluded.team2_avg_conceded, "
        "h2h_team1_winpct=excluded.h2h_team1_winpct, winpct_diff=excluded.winpct_diff, "
        "avg_score_diff=excluded.avg_score_diff, label_team1_won=excluded.label_team1_won, "
        "form_matches=excluded.form_matches, updated_at=excluded.updated_at", out)
    conn.commit()
    log.info("match_features %s: %d matches", fmt, len(out))
    return len(out)


def build_ball_state_for_format(conn, fmt: str) -> int:
    d = pd.read_sql_query(
        "SELECT d.match_id, d.innings, d.over, d.ball_in_over, d.batting_team, "
        "d.bowling_team, d.runs_total, d.wides, d.noballs, d.player_dismissed, "
        "m.gender, m.winner FROM deliveries d JOIN matches m ON d.match_id=m.match_id "
        "WHERE m.format=?", conn, params=(fmt,))
    if d.empty:
        return 0
    d = d.sort_values(["match_id", "innings", "over", "ball_in_over"]).reset_index(drop=True)
    g = d.groupby(["match_id", "innings"])
    d["legal"] = ((d["wides"].fillna(0) == 0) & (d["noballs"].fillna(0) == 0)).astype(int)
    d["runs_total"] = d["runs_total"].fillna(0).astype(int)
    d["score"] = g["runs_total"].cumsum()
    d["balls_bowled"] = g["legal"].cumsum()
    d["wkt"] = d["player_dismissed"].notna().astype(int)
    d["wickets"] = g["wkt"].cumsum()
    d["balls_remaining"] = (T20_BALLS - d["balls_bowled"]).clip(lower=0)
    d["phase"] = d["over"].apply(lambda o: "powerplay" if o <= 5 else ("middle" if o <= 14 else "death"))
    d["current_run_rate"] = (6 * d["score"] / d["balls_bowled"]).where(d["balls_bowled"] > 0).round(3)

    inn1 = d[d["innings"] == 1].groupby("match_id")["score"].max()
    d["target"] = d["match_id"].map(inn1) + 1
    chase = d["innings"] == 2
    d["target"] = d["target"].where(chase)
    d["runs_required"] = (d["target"] - d["score"]).where(chase)
    d["req_run_rate"] = (6 * d["runs_required"] / d["balls_remaining"]).where(
        chase & (d["balls_remaining"] > 0)).round(3)
    d["label_batting_team_won"] = (d["winner"] == d["batting_team"]).astype("Int64")
    d.loc[d["winner"].isna(), "label_batting_team_won"] = pd.NA

    cols = ["match_id", "gender", "innings", "over", "phase", "batting_team",
            "bowling_team", "score", "wickets", "balls_bowled", "balls_remaining",
            "current_run_rate", "target", "runs_required", "req_run_rate", "wkt",
            "label_batting_team_won"]
    FEATURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FEATURES_DIR / f"ball_state_{fmt}.parquet"
    d[cols].to_parquet(path, index=False)
    log.info("ball_state %s: %d rows -> %s", fmt, len(d), path.name)
    return len(d)


def build_player_match_impact_for_format(conn, fmt: str) -> int:
    inn = build_innings(conn, fmt)
    if inn.empty:
        return 0
    team_runs = _team_totals(conn, fmt)
    team_wkts = _team_wickets(conn, fmt)
    # gender-aware: `inn` already carries each row's match gender (see
    # stats.build_innings), needed because a handful of Cricsheet's own
    # registry identifiers are reused across two genuinely different people
    # of different genders -- a plain identifier->player_id dict would
    # silently pick one of them for every row.
    inn = inn.assign(resolved_player_id=resolve_player_ids(conn, inn["identifier"], inn["gender"]))
    now = dt.datetime.now().isoformat(timespec="seconds")

    rows = []
    for r in inn.itertuples(index=False):
        pid = r.resolved_player_id
        if not pid:
            continue
        runs = int(r.runs)
        bf = int(r.balls_faced)
        bb = int(r.balls_bowled)
        rc = int(r.runs_conceded)
        wk = int(r.wickets)
        dots = int(r.dot_balls)
        bdry = int(r.boundary_balls)
        tr = team_runs.get((r.match_id, r.team), 0)
        tw = team_wkts.get((r.match_id, r.team), 0)
        bat_sr = round(100 * runs / bf, 1) if bf else None
        econ = round(6 * rc / bb, 2) if bb else None
        bat_contrib = round(100 * runs / tr, 1) if bf and tr else None
        bowl_contrib = round(100 * wk / tw, 1) if bb and tw else None
        # dot%/boundary% are containment-quality signals economy alone
        # can't separate ("gave away ones and twos" vs "conceded boundaries")
        # -- None (not 0) when she didn't bowl, same convention as economy.
        dot_pct = round(100 * dots / bb, 1) if bb else None
        boundary_pct = round(100 * bdry / bb, 1) if bb else None
        # Balls per wicket -- only defined in matches she actually struck;
        # None rather than 0 for a wicketless spell, so it reads as "no
        # signal this match" instead of "instant wickets", when averaged.
        bowl_sr = round(bb / wk, 1) if wk else None
        impact = round((bat_contrib or 0) + (bowl_contrib or 0), 1)
        rows.append((
            pid, r.match_id, fmt,
            r.date.date().isoformat() if pd.notna(r.date) else None,
            r.team, r.opponent, int(r.won), runs, bf, bat_sr, bat_contrib,
            wk, bb, rc, econ, bowl_contrib, dot_pct, boundary_pct, bowl_sr,
            impact, now))

    conn.executemany(
        "INSERT INTO player_match_impact(player_id, match_id, format, date, team, "
        "opponent, won, runs, balls_faced, bat_strike_rate, bat_contribution_pct, "
        "wickets, balls_bowled, runs_conceded, economy, bowl_contribution_pct, "
        "bowl_dot_pct, bowl_boundary_pct, bowl_strike_rate, "
        "impact_rating, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id, match_id) DO UPDATE SET "
        "bat_strike_rate=excluded.bat_strike_rate, bat_contribution_pct=excluded.bat_contribution_pct, "
        "bowl_contribution_pct=excluded.bowl_contribution_pct, "
        "bowl_dot_pct=excluded.bowl_dot_pct, bowl_boundary_pct=excluded.bowl_boundary_pct, "
        "bowl_strike_rate=excluded.bowl_strike_rate, impact_rating=excluded.impact_rating, "
        "won=excluded.won, updated_at=excluded.updated_at", rows)
    conn.commit()
    log.info("player_match_impact %s: %d rows", fmt, len(rows))
    return len(rows)


def build_match_features(conn) -> dict:
    out = {f: build_match_features_for_format(conn, f) for f in _formats()}
    set_meta(conn, "match_features_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out


def build_ball_state(conn) -> dict:
    out = {f: build_ball_state_for_format(conn, f) for f in _formats()}
    set_meta(conn, "ball_state_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out


def build_player_match_impact(conn) -> dict:
    out = {f: build_player_match_impact_for_format(conn, f) for f in _formats()}
    set_meta(conn, "player_match_impact_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out


def build_all(conn) -> dict:
    return {"match_features": build_match_features(conn),
            "ball_state": build_ball_state(conn),
            "player_match_impact": build_player_match_impact(conn)}

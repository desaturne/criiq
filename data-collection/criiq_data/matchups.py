from __future__ import annotations

import datetime as dt

import pandas as pd

from .config import enabled_sources
from .db import set_meta
from .h2h import BOWLER_WICKETS
from .identity import player_id_map
from .logging_utils import get_logger

log = get_logger("matchups")

# ~one over: enough for a real sample without hiding a genuine short matchup.
MIN_MATCHUP_BALLS = 6


def build_for_format(conn, fmt: str) -> int:
    d = pd.read_sql_query(
        "SELECT d.striker, d.bowler, d.bowling_team, d.runs_off_bat, d.wides, "
        "d.wicket_type, d.player_dismissed, m.gender "
        "FROM deliveries d JOIN matches m ON d.match_id=m.match_id "
        "WHERE m.format=? AND m.team_type='international'",
        conn, params=(fmt,))
    if d.empty:
        return 0
    n2i = {r["player_name"]: r["identifier"]
           for r in conn.execute("SELECT player_name, identifier FROM identifier_map")}
    unambiguous, split = player_id_map(conn)
    pid2name = {r["player_id"]: r["canonical_name"]
                for r in conn.execute("SELECT player_id, canonical_name FROM players")}

    d["legal"] = (d["wides"].fillna(0) == 0).astype(int)
    d["sid"] = d["striker"].map(n2i)
    d["bid"] = d["bowler"].map(n2i)
    d = d.dropna(subset=["sid", "bid"])
    d["dismissed"] = ((d["player_dismissed"] == d["striker"]) &
                      d["wicket_type"].isin(BOWLER_WICKETS)).astype(int)

    # gender kept in the group key, otherwise identifiers reused across genders (see identity.py)
    # would have their dismissal history blended together.
    grp = d.groupby(["sid", "bid", "gender"]).agg(
        balls=("legal", "sum"), runs=("runs_off_bat", "sum"),
        dismissals=("dismissed", "sum")).reset_index()
    # keeps every matchup with a real sample, including zero dismissals,
    # since "never dismissed her" is as real a fact as "dismissed her 3 times".
    grp = grp[grp["balls"] >= MIN_MATCHUP_BALLS]
    if grp.empty:
        return 0
    bteam = d.groupby(["bid", "gender"])["bowling_team"].agg(
        lambda s: s.mode().iloc[0] if not s.mode().empty else None).to_dict()

    now = dt.datetime.now().isoformat(timespec="seconds")
    rows = []
    for r in grp.itertuples(index=False):
        batter_pid = unambiguous.get(r.sid) or split.get((r.sid, r.gender))
        bowler_pid = unambiguous.get(r.bid) or split.get((r.bid, r.gender))
        if not batter_pid or not bowler_pid:
            continue
        rows.append((
            fmt, batter_pid, bowler_pid, pid2name.get(batter_pid),
            pid2name.get(bowler_pid), bteam.get((r.bid, r.gender)),
            int(r.balls), int(r.runs), int(r.dismissals), now,
        ))
    conn.executemany(
        "INSERT INTO dismissal_matchup(format, batter_id, bowler_id, batter_name, "
        "bowler_name, bowler_team, balls, runs, dismissals, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(format, batter_id, bowler_id) DO UPDATE SET "
        "bowler_team=excluded.bowler_team, balls=excluded.balls, runs=excluded.runs, "
        "dismissals=excluded.dismissals, updated_at=excluded.updated_at", rows)
    conn.commit()
    log.info("matchups %s: %d dismissal pairs", fmt, len(rows))
    return len(rows)


def build_venue_matchups_for_format(conn, fmt: str) -> int:
    """same logic as build_for_format, with venue_id added to the group key
    since the bogey bowler at a specific ground can differ from the overall one.
    """
    d = pd.read_sql_query(
        "SELECT d.striker, d.bowler, d.bowling_team, d.runs_off_bat, d.wides, "
        "d.wicket_type, d.player_dismissed, m.gender, m.venue_id "
        "FROM deliveries d JOIN matches m ON d.match_id=m.match_id "
        "WHERE m.format=? AND m.team_type='international' AND m.venue_id IS NOT NULL",
        conn, params=(fmt,))
    if d.empty:
        return 0
    n2i = {r["player_name"]: r["identifier"]
           for r in conn.execute("SELECT player_name, identifier FROM identifier_map")}
    unambiguous, split = player_id_map(conn)
    pid2name = {r["player_id"]: r["canonical_name"]
                for r in conn.execute("SELECT player_id, canonical_name FROM players")}

    d["legal"] = (d["wides"].fillna(0) == 0).astype(int)
    d["sid"] = d["striker"].map(n2i)
    d["bid"] = d["bowler"].map(n2i)
    d = d.dropna(subset=["sid", "bid"])
    d["dismissed"] = ((d["player_dismissed"] == d["striker"]) &
                      d["wicket_type"].isin(BOWLER_WICKETS)).astype(int)

    grp = d.groupby(["sid", "bid", "gender", "venue_id"]).agg(
        balls=("legal", "sum"), runs=("runs_off_bat", "sum"),
        dismissals=("dismissed", "sum")).reset_index()
    grp = grp[grp["balls"] >= MIN_MATCHUP_BALLS]
    if grp.empty:
        return 0
    bteam = d.groupby(["bid", "gender"])["bowling_team"].agg(
        lambda s: s.mode().iloc[0] if not s.mode().empty else None).to_dict()

    now = dt.datetime.now().isoformat(timespec="seconds")
    rows = []
    for r in grp.itertuples(index=False):
        batter_pid = unambiguous.get(r.sid) or split.get((r.sid, r.gender))
        bowler_pid = unambiguous.get(r.bid) or split.get((r.bid, r.gender))
        if not batter_pid or not bowler_pid:
            continue
        rows.append((
            fmt, r.venue_id, batter_pid, bowler_pid, pid2name.get(batter_pid),
            pid2name.get(bowler_pid), bteam.get((r.bid, r.gender)),
            int(r.balls), int(r.runs), int(r.dismissals), now,
        ))
    conn.executemany(
        "INSERT INTO venue_dismissal_matchup(format, venue_id, batter_id, bowler_id, "
        "batter_name, bowler_name, bowler_team, balls, runs, dismissals, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(format, venue_id, batter_id, bowler_id) DO UPDATE SET "
        "bowler_team=excluded.bowler_team, balls=excluded.balls, runs=excluded.runs, "
        "dismissals=excluded.dismissals, updated_at=excluded.updated_at", rows)
    conn.commit()
    log.info("venue_matchups %s: %d dismissal pairs", fmt, len(rows))
    return len(rows)


def top_dismissers_at_venue(conn, player_id: str, fmt: str, venue_id: str, limit: int = 5) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT bowler_name, bowler_team, dismissals, balls, runs "
        "FROM venue_dismissal_matchup WHERE batter_id=? AND format=? AND venue_id=? "
        "ORDER BY dismissals DESC, balls DESC LIMIT ?", (player_id, fmt, venue_id, limit))]


def build_matchups(conn) -> dict:
    out = {}
    for fmt in sorted({s.fmt for s in enabled_sources()}):
        out[fmt] = build_for_format(conn, fmt)
        build_venue_matchups_for_format(conn, fmt)
    set_meta(conn, "matchups_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out


def top_dismissers(conn, player_id: str, fmt: str, limit: int = 10) -> dict:
    rows = [dict(r) for r in conn.execute(
        "SELECT bowler_name, bowler_team, dismissals, balls, runs "
        "FROM dismissal_matchup WHERE batter_id=? AND format=? "
        "ORDER BY dismissals DESC, balls DESC", (player_id, fmt))]
    per_opponent: dict[str, dict] = {}
    for r in rows:
        team = r["bowler_team"]
        if team and team not in per_opponent:
            per_opponent[team] = {"bowler": r["bowler_name"],
                                  "dismissals": r["dismissals"], "balls": r["balls"]}
    return {"overall": rows[:limit], "worst_bowler_per_opponent": per_opponent}


def favourite_victims(conn, player_id: str, fmt: str, limit: int = 10) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT batter_name, dismissals, balls, runs FROM dismissal_matchup "
        "WHERE bowler_id=? AND format=? ORDER BY dismissals DESC, balls DESC LIMIT ?",
        (player_id, fmt, limit))]


def batter_vs_team_bowlers(conn, player_id: str, fmt: str, opponent_team: str) -> dict:
    """every bowler from opponent_team this batter has faced (>= MIN_MATCHUP_BALLS balls),
    not just the ones who dismissed her. ranked by dismissal count, not rate.
    """
    rows = conn.execute(
        "SELECT bowler_name, balls, runs, dismissals FROM dismissal_matchup "
        "WHERE batter_id=? AND format=? AND bowler_team=? "
        "ORDER BY dismissals DESC, balls DESC", (player_id, fmt, opponent_team)).fetchall()
    bowlers = []
    for r in rows:
        balls = r["balls"]
        bowlers.append({
            "bowler_name": r["bowler_name"], "balls": balls, "runs": r["runs"],
            "dismissals": r["dismissals"],
            "strike_rate": round(100 * r["runs"] / balls, 1) if balls else None,
            "dismissal_rate": round(r["dismissals"] / balls, 4) if balls else None,
        })
    return {"opponent": opponent_team, "bowlers": bowlers,
            "bogey_bowler": bowlers[0] if bowlers else None}


def bowler_vs_team_batters(conn, player_id: str, fmt: str, opponent_team: str,
                           gender: str = "female") -> dict:
    """every batter from opponent_team this bowler has faced (>= MIN_MATCHUP_BALLS balls).
    dismissal_matchup has no batting_team column, so opponent scoping goes through
    roster membership (role_finalize.team_candidates) instead.

    best_matchup is the batter dismissed the most times; most_expensive is the one
    who's hit the most total runs off her.
    """
    from .role_finalize import team_candidates
    roster = team_candidates(conn, opponent_team, gender)
    if roster.empty:
        return {"opponent": opponent_team, "batters": [], "best_matchup": None, "most_expensive": None}

    placeholders = ",".join("?" * len(roster))
    rows = conn.execute(
        f"SELECT batter_name, balls, runs, dismissals FROM dismissal_matchup "
        f"WHERE bowler_id=? AND format=? AND batter_id IN ({placeholders})",
        (player_id, fmt, *roster["player_id"])).fetchall()
    batters = []
    for r in rows:
        balls = r["balls"]
        batters.append({
            "batter_name": r["batter_name"], "balls": balls, "runs": r["runs"],
            "wickets": r["dismissals"],
            "economy": round(6 * r["runs"] / balls, 2) if balls else None,
            "batter_strike_rate": round(100 * r["runs"] / balls, 1) if balls else None,
        })
    batters.sort(key=lambda b: (-b["wickets"], -b["balls"]))
    best_matchup = batters[0] if batters and batters[0]["wickets"] > 0 else None
    most_expensive = max(batters, key=lambda b: b["runs"], default=None)
    return {"opponent": opponent_team, "batters": batters,
            "best_matchup": best_matchup, "most_expensive": most_expensive}

from __future__ import annotations

import datetime as dt

import pandas as pd

from .config import enabled_sources
from .db import set_meta
from .h2h import BOWLER_WICKETS
from .identity import player_id_map
from .logging_utils import get_logger

log = get_logger("matchups")


def build_for_format(conn, fmt: str) -> int:
    d = pd.read_sql_query(
        "SELECT d.striker, d.bowler, d.bowling_team, d.runs_off_bat, d.wides, "
        "d.wicket_type, d.player_dismissed, m.gender "
        "FROM deliveries d JOIN matches m ON d.match_id=m.match_id WHERE m.format=?",
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

    # gender kept in every group key: the handful of Cricsheet registry
    # identifiers reused across two genuinely different people of different
    # genders (see identity.py) would otherwise have their dismissal history
    # against each other blended into one meaningless combined pair.
    grp = d.groupby(["sid", "bid", "gender"]).agg(
        balls=("legal", "sum"), runs=("runs_off_bat", "sum"),
        dismissals=("dismissed", "sum")).reset_index()
    grp = grp[grp["dismissals"] >= 1]
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


def build_matchups(conn) -> dict:
    out = {}
    for fmt in sorted({s.fmt for s in enabled_sources()}):
        out[fmt] = build_for_format(conn, fmt)
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

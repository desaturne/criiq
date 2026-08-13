from __future__ import annotations

import datetime as dt

import pandas as pd

from .config import enabled_sources
from .db import set_meta
from .identity import player_id_map
from .logging_utils import get_logger

log = get_logger("fielding")

_CAUGHT = "caught"
_CAUGHT_AND_BOWLED = "caught and bowled"
_STUMPED = "stumped"
_RUN_OUT = "run out"

# below this many matches, a dismissals-per-match rate is too noisy to rank
# on -- better_fielder() falls back to the raw dismissal count instead.
MIN_MATCHES_FOR_RATE = 5


def build_fielding_for_format(conn, fmt: str, team_type: str | None = "international") -> int:
    """career catches/run-outs/stumpings per player, from deliveries'
    fielder_1/2/3 columns (see ingest.py). Credit rules mirror how
    ESPNcricinfo attributes fielding dismissals:

      * caught          -> fielder_1 (the catcher) only
      * caught and bowled -> the bowler (cricsheet leaves fielder_* blank here)
      * stumped         -> fielder_1 only (always the keeper)
      * run out         -> every fielder cricsheet lists (a direct hit and
                            the fielder who set it up both get credit)
    """
    tt_clause = " AND m.team_type = ?" if team_type is not None else ""
    params = (fmt, team_type) if team_type is not None else (fmt,)
    deliv = pd.read_sql_query(
        f"""
        SELECT d.match_id, d.bowler, d.wicket_type, d.fielder_1, d.fielder_2, d.fielder_3,
               m.gender
        FROM deliveries d JOIN matches m ON d.match_id = m.match_id
        WHERE m.format = ?{tt_clause} AND d.wicket_type IN (?, ?, ?, ?)
        """, conn, params=(*params, _CAUGHT, _CAUGHT_AND_BOWLED, _STUMPED, _RUN_OUT))
    if deliv.empty:
        log.info("fielding %s: no wicket rows", fmt)
        return 0

    n2i = {r["player_name"]: r["identifier"]
           for r in conn.execute("SELECT player_name, identifier FROM identifier_map")}

    credits = []  # (identifier, gender, kind)
    for r in deliv.itertuples():
        if r.wicket_type == _CAUGHT_AND_BOWLED:
            ident = n2i.get(r.bowler)
            if ident:
                credits.append((ident, r.gender, "catches"))
            continue
        fielders = [f for f in (r.fielder_1, r.fielder_2, r.fielder_3) if f]
        if r.wicket_type == _CAUGHT:
            kind, fielders = "catches", fielders[:1]
        elif r.wicket_type == _STUMPED:
            kind, fielders = "stumpings", fielders[:1]
        else:
            kind = "run_outs"  # every listed fielder gets credit
        for name in fielders:
            ident = n2i.get(name)
            if ident:
                credits.append((ident, r.gender, kind))

    if not credits:
        log.info("fielding %s: no creditable dismissals", fmt)
        return 0

    cred = pd.DataFrame(credits, columns=["identifier", "gender", "kind"])

    # real matches-appeared count (not just matches they batted/bowled in) --
    # a specialist fielder can take catches without ever facing a ball.
    mp = pd.read_sql_query(
        f"""
        SELECT DISTINCT mp.player_name, mp.match_id
        FROM match_players mp JOIN matches m ON mp.match_id = m.match_id
        WHERE m.format = ?{tt_clause}
        """, conn, params=params)
    idmap = pd.read_sql_query("SELECT player_name, identifier FROM identifier_map", conn)
    mp = mp.merge(idmap, on="player_name", how="left").dropna(subset=["identifier"])
    matches_played = mp.groupby("identifier")["match_id"].nunique()

    unambiguous, split = player_id_map(conn)
    meta = {}
    for r in conn.execute("SELECT cricsheet_identifier, gender, canonical_name FROM players"):
        meta[(r["cricsheet_identifier"], r["gender"])] = r["canonical_name"]

    now = dt.datetime.now().isoformat(timespec="seconds")
    rows = []
    for (ident, gender), g in cred.groupby(["identifier", "gender"]):
        pid = unambiguous.get(ident) or split.get((ident, gender))
        name = meta.get((ident, gender)) or meta.get((ident, None))
        if not pid or not name:
            continue
        counts = g["kind"].value_counts()
        catches = int(counts.get("catches", 0))
        run_outs = int(counts.get("run_outs", 0))
        stumpings = int(counts.get("stumpings", 0))
        dismissals = catches + run_outs + stumpings
        matches = int(matches_played.get(ident, 0))
        rows.append((
            pid, fmt, name, matches, catches, run_outs, stumpings, dismissals,
            round(dismissals / matches, 2) if matches else None, now,
        ))

    conn.executemany(
        "INSERT INTO player_fielding(player_id, format, name, matches, catches, "
        "run_outs, stumpings, dismissals, dismissals_per_match, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id, format) DO UPDATE SET "
        "name=excluded.name, matches=excluded.matches, catches=excluded.catches, "
        "run_outs=excluded.run_outs, stumpings=excluded.stumpings, "
        "dismissals=excluded.dismissals, dismissals_per_match=excluded.dismissals_per_match, "
        "updated_at=excluded.updated_at", rows)
    conn.commit()
    log.info("fielding %s: %d player fielding records built", fmt, len(rows))
    return len(rows)


def build_fielding(conn) -> dict:
    out = {}
    for fmt in sorted({s.fmt for s in enabled_sources()}):
        out[fmt] = build_fielding_for_format(conn, fmt)
    set_meta(conn, "fielding_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out


def get_fielding(conn, player_id: str, fmt: str = "T20") -> dict | None:
    row = conn.execute(
        "SELECT matches, catches, run_outs, stumpings, dismissals, dismissals_per_match "
        "FROM player_fielding WHERE player_id=? AND format=?", (player_id, fmt)).fetchone()
    return dict(row) if row else None


def better_fielder(conn, player_id_a: str, player_id_b: str, fmt: str = "T20") -> dict:
    """Ranks two players by fielding record: dismissals-per-match once both
    have a real sample (MIN_MATCHES_FOR_RATE+), otherwise raw dismissals --
    a per-match rate over a handful of matches is noise, not signal.
    """
    a = get_fielding(conn, player_id_a, fmt)
    b = get_fielding(conn, player_id_b, fmt)
    if not a or not b:
        return {"comparable": False, "reason": "no fielding record for one or both players",
                "a": a, "b": b}

    def _rank_value(rec: dict) -> float:
        if rec["matches"] >= MIN_MATCHES_FOR_RATE and rec["dismissals_per_match"] is not None:
            return rec["dismissals_per_match"]
        return rec["dismissals"]

    va, vb = _rank_value(a), _rank_value(b)
    better_id = None if va == vb else (player_id_a if va > vb else player_id_b)
    return {"comparable": True, "better_fielder_id": better_id, "a": a, "b": b}

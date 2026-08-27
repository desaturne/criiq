"""head-to-head matchup matrix between two specific sets of players.

cross-references dismissal_matchup (built from ball-by-ball data) to show
which of my players match up well against a named opponent XI's players.
purely reads existing data; pairs with no recorded history are just omitted.
"""
from __future__ import annotations

import sqlite3

from ..config import SETTINGS

# minimum balls before a pairing counts, one over, same floor data-collection's
# matchup tables use so a 2-ball fluke isn't surfaced as a "matchup"
_MIN_PAIR_BALLS = 6


def _rows(conn, fmt, id_col, id_values, other_col, other_values):
    my_ph = ",".join("?" * len(id_values))
    opp_ph = ",".join("?" * len(other_values))
    return conn.execute(
        f"SELECT batter_id, bowler_id, batter_name, bowler_name, balls, runs, dismissals "
        f"FROM dismissal_matchup WHERE format=? AND {id_col} IN ({my_ph}) "
        f"AND {other_col} IN ({opp_ph}) AND balls >= ?",
        (fmt, *id_values, *other_values, _MIN_PAIR_BALLS)).fetchall()


def head_to_head_matrix(conn: sqlite3.Connection, my_ids: list[str], opponent_ids: list[str],
                        fmt: str = SETTINGS.format) -> dict:
    """{"batting": {...}, "bowling": {...}}, each keyed by my player's name.

    batting: my batters vs the opponent's bowlers, per bowler faced (>= 6
    balls), plus the bogey bowler (most dismissals) and best matchup (most
    runs scored).
    bowling: my bowlers vs the opponent's batters, plus best (most dismissals)
    and most_expensive (most runs conceded).
    """
    if not my_ids or not opponent_ids:
        return {"batting": {}, "bowling": {}}

    batting: dict = {}
    for r in _rows(conn, fmt, "batter_id", my_ids, "bowler_id", opponent_ids):
        balls = r["balls"] or 0
        entry = {"opponent": r["bowler_name"], "balls": balls, "runs": r["runs"],
                 "dismissals": r["dismissals"],
                 "dismissal_rate": round(r["dismissals"] / balls, 3) if balls else None,
                 "strike_rate": round(100 * r["runs"] / balls, 1) if balls else None}
        batting.setdefault(r["batter_name"], []).append(entry)

    bowling: dict = {}
    for r in _rows(conn, fmt, "bowler_id", my_ids, "batter_id", opponent_ids):
        balls = r["balls"] or 0
        entry = {"opponent": r["batter_name"], "balls": balls, "runs": r["runs"],
                 "dismissals": r["dismissals"],
                 "wicket_rate": round(r["dismissals"] / balls, 3) if balls else None,
                 "economy": round(6 * r["runs"] / balls, 2) if balls else None}
        bowling.setdefault(r["bowler_name"], []).append(entry)

    def _bat_summary(matchups):
        return {
            "matchups": sorted(matchups, key=lambda m: -m["balls"]),
            # bogey bowler: dismissed this batter most (ties broken by rate)
            "bogey": max(matchups, key=lambda m: (m["dismissals"], m["dismissal_rate"] or 0))
                     if any(m["dismissals"] for m in matchups) else None,
            # best matchup: most runs scored off that bowler
            "best": max(matchups, key=lambda m: m["runs"]) if matchups else None,
        }

    def _bowl_summary(matchups):
        return {
            "matchups": sorted(matchups, key=lambda m: -m["balls"]),
            "best": max(matchups, key=lambda m: (m["dismissals"], m["wicket_rate"] or 0))
                    if any(m["dismissals"] for m in matchups) else None,
            "most_expensive": max(matchups, key=lambda m: m["runs"]) if matchups else None,
        }

    return {
        "batting": {name: _bat_summary(ms) for name, ms in batting.items()},
        "bowling": {name: _bowl_summary(ms) for name, ms in bowling.items()},
    }

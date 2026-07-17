"""Head-to-head matchup matrix between two specific sets of players.

Given *my* players and a named *opponent XI*, cross-references the real
batter-vs-bowler dismissal history (`dismissal_matchup`, built by
data-collection from ball-by-ball data) to answer "which of my players matches
up well against which of theirs" -- the concrete input a coach wants when
picking a side to counter a specific opposition, not just an aggregate team
matchup. Purely a read/aggregation over data that already exists; it invents
nothing and, for any pair with no recorded history, simply omits them rather
than guessing.
"""
from __future__ import annotations

import sqlite3

from ..config import SETTINGS

# Minimum balls in a specific pairing before it's worth reporting -- an over,
# the same floor data-collection's matchup tables use, so a 2-ball fluke isn't
# surfaced as a "matchup".
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
    """`{"batting": {...}, "bowling": {...}}`, each keyed by my player's name.

    - batting: my batters vs the opponent's bowlers. Per batter, every bowler
      faced (>= 6 balls) with balls/runs/dismissals/dismissal-rate/strike-rate,
      plus the **bogey** bowler (most dismissals, then highest dismissal rate)
      and the batter's **best** matchup (most runs scored).
    - bowling: my bowlers vs the opponent's batters. Per bowler, every batter
      bowled to, plus **best** (most dismissals) and **most_expensive** (most
      runs conceded).
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

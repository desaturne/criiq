"""relative team strength, for spotting lopsided matchups.

mean importance_score doesn't separate a top side from a minnow well, since
associate nations pad it beating other associates. counting current
ICC-ranked players in the squad is the signal that actually works here.
"""
from __future__ import annotations

import sqlite3

from ..config import SETTINGS
from ..roster import team_pool


def team_strength(conn: sqlite3.Connection, team: str, fmt: str = SETTINGS.format,
                  gender: str = SETTINGS.gender) -> dict:
    """{team, icc_ranked, pool_size}. icc_ranked is how many of the team's
    eligible pool hold a current ICC ranking, the strength headline.
    """
    pool = team_pool(conn, team, fmt, gender)
    if not pool:
        return {"team": team, "icc_ranked": 0, "pool_size": 0}
    ph = ",".join("?" * len(pool))
    icc_ranked = conn.execute(
        f"SELECT COUNT(*) FROM player_registry WHERE format=? AND icc_rank IS NOT NULL "
        f"AND player_id IN ({ph})", (fmt, *pool)).fetchone()[0]
    return {"team": team, "icc_ranked": int(icc_ranked), "pool_size": len(pool)}


def strength_context(conn: sqlite3.Connection, team: str, opponent: str,
                     fmt: str = SETTINGS.format, gender: str = SETTINGS.gender) -> dict:
    """compares the two sides and flags whether it's lopsided enough for the
    stronger team to rotate: this team must lead by >= lopsided_icc_gap and
    the opponent be thin at the top (<= 1 ranked player).
    """
    mine = team_strength(conn, team, fmt, gender)
    theirs = team_strength(conn, opponent, fmt, gender)
    gap = mine["icc_ranked"] - theirs["icc_ranked"]
    lopsided = (gap >= SETTINGS.lopsided_icc_gap and theirs["icc_ranked"] <= 1
                and mine["icc_ranked"] >= 1)
    return {
        "team": mine, "opponent": theirs, "icc_ranked_gap": gap,
        "stronger_side": team if gap > 0 else (opponent if gap < 0 else None),
        "lopsided": lopsided,
    }

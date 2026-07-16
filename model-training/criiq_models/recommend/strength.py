"""Relative team strength, for spotting lopsided matchups.

The coach's point: against a much weaker side, the stronger team can rest
frontline players and still expect to win, so the tool should say so and offer
a rotation XI. That needs a team-strength signal -- and the obvious candidate,
mean `importance_score`, turns out useless for it: associate nations pad their
importance beating other associates, so Nepal's top-11 mean importance (~70) is
barely below India's (~79). The signal that actually separates a top side from
a minnow is **how many of its players hold a current ICC ranking** (a genuine
world-top-10 batter/bowler/all-rounder): India 6, Nepal 1, Oman 0 (men, live
DB). That -- not padded averages -- is what team strength keys on here. ICC
*country* rankings aren't ingested (only per-player ones), so this counts
world-ranked players in the squad as the faithful, available proxy.
"""
from __future__ import annotations

import sqlite3

from ..config import SETTINGS
from ..roster import team_pool


def team_strength(conn: sqlite3.Connection, team: str, fmt: str = SETTINGS.format,
                  gender: str = SETTINGS.gender) -> dict:
    """`{team, icc_ranked, pool_size}` -- `icc_ranked` = how many of the team's
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
    """Compare the two sides and decide whether it's lopsided enough that the
    stronger team could rotate. `lopsided` is True only when *this* team is the
    stronger one by a clear margin (ICC-ranked gap >= `lopsided_icc_gap`) and
    the opponent is genuinely thin at the top (<= 1 ranked player) -- so
    India-vs-Nepal fires, India-vs-Australia does not.
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

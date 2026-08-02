"""style-specific batter-vs-attack matchup.

extends recommend/score.py's matchup_part beyond the blunt aggregate
dismissal_matchup signal with a style-aware edge: the opponent's current
pace/spin bowling mix, weighted against the batter's own vs-pace/vs-spin
record.

secondary/backup signal, smaller magnitude than the aggregate dismissal
matchup, since style coverage is still partial (13 major nations) and
coarser than specific-bowler history when that's available.
"""
from __future__ import annotations

import json
import sqlite3

import pandas as pd

from ..config import SETTINGS
from .common import shrink
from ..roster import team_pool

STYLE_EDGE_CAP = 5.0


def opponent_bowling_mix(conn: sqlite3.Connection, opponent: str, fmt: str = SETTINGS.format,
                          gender: str = SETTINGS.gender, opponent_roster: list[str] | None = None) -> dict | None:
    """{"pace": share, "spin": share} of the opponent's current eligible
    bowlers with a known style. None if fewer than 2 are known, too thin to
    characterize an attack's composition.

    opponent_roster: pre-computed team_pool result, for callers scoring many
    players against the same opponent, since team_pool is expensive and
    doesn't depend on which player is being scored.
    """
    pool = opponent_roster if opponent_roster is not None else team_pool(conn, opponent, fmt, gender)
    if not pool:
        return None
    placeholders = ",".join("?" * len(pool))
    styles = pd.read_sql_query(
        f"SELECT bowling_style FROM player_styles WHERE player_id IN ({placeholders}) "
        f"AND bowling_style IS NOT NULL", conn, params=pool)
    if len(styles) < 2:
        return None
    counts = styles["bowling_style"].value_counts(normalize=True)
    return {"pace": float(counts.get("pace", 0.0)), "spin": float(counts.get("spin", 0.0))}


def style_matchup_edge(conn: sqlite3.Connection, player_id: str, opponent: str,
                        career_dismissal_rate: float | None, fmt: str = SETTINGS.format,
                        gender: str = SETTINGS.gender, opponent_roster: list[str] | None = None) -> dict:
    """a batter's dismissal-rate edge against the opponent's bowling mix,
    shrunk toward her career baseline. career_dismissal_rate should be the
    same value score.py computes for the aggregate matchup signal, so both
    agree on what "her normal record" means.

    returns {"available": False, "edge_part": 0.0} whenever the data isn't
    known well enough to say anything, never a guessed number.
    """
    if career_dismissal_rate is None:
        return {"available": False, "edge_part": 0.0}

    mix = opponent_bowling_mix(conn, opponent, fmt, gender, opponent_roster=opponent_roster)
    row = conn.execute(
        "SELECT profile_json FROM player_advanced WHERE player_id=? AND format=?",
        (player_id, fmt)).fetchone()
    if not mix or not row or not row["profile_json"]:
        return {"available": False, "edge_part": 0.0}

    vs_type = json.loads(row["profile_json"]).get("batting", {}).get("vs_bowling_type", {})
    if not vs_type:
        return {"available": False, "edge_part": 0.0}

    weighted_rate, total_weight = 0.0, 0.0
    for style, share in mix.items():
        block = vs_type.get(style)
        if not block or not block.get("balls"):
            continue
        raw_rate = block["dismissals"] / block["balls"]
        shrunk_rate = shrink(raw_rate, block["balls"], career_dismissal_rate,
                              prior_strength=SETTINGS.shrinkage_prior_matches * 6)
        weighted_rate += share * shrunk_rate
        total_weight += share

    if total_weight <= 0:
        return {"available": False, "edge_part": 0.0}
    weighted_rate /= total_weight

    edge_part = round(max(-STYLE_EDGE_CAP, min(STYLE_EDGE_CAP,
                                                (career_dismissal_rate - weighted_rate) * 120)), 1)
    return {"available": True, "edge_part": edge_part,
            "weighted_dismissal_rate": round(weighted_rate, 4), "opponent_bowling_mix": mix}

"""Style-specific batter-vs-attack matchup.

Extends `recommend/score.py`'s `matchup_part` beyond the blunt aggregate
`dismissal_matchup` signal (a batter's dismissal rate vs "this opponent's
bowlers" as one undifferentiated group) with a style-aware edge: the
opponent's actual current pace/spin bowling mix, weighted against the
batter's own vs-pace/vs-spin record.

Both halves of this signal only exist because of work done this session:
`player_styles.bowling_style` was backfilled for major nations' current
bowlers from Wikipedia squad data already fetched for `role_finalize.py`
(previously discarded — see that module's `_map_bowling_style`), and
`player_advanced.profile_json`'s `vs_bowling_type` split only populates once
enough bowlers have a resolved style (data-collection's `advanced.py`
reads `players.bowling_style`, a separate column from `player_styles`'s —
`role_finalize.merge_external_roles` backfills both).

This is a *secondary, backup* signal — smaller-magnitude than the aggregate
`dismissal_matchup` edge — for two reasons: style coverage is still partial
(13 major nations' current squads, not the full player pool), and style
alone is coarser than the specific-bowler history the aggregate signal uses
when it's available.
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
    bowlers with a known style. `None` if fewer than 2 are known — too thin
    to characterize an attack's composition at all.

    `opponent_roster`: pre-computed `roster.team_pool` result, for callers
    scoring many players against the same opponent -- `team_pool` includes an
    expensive cross-gender-identifier scan over the whole match history that
    doesn't depend on which player is being scored, so recomputing it fresh
    per player (as this used to) turned out to dominate `recommend`'s runtime
    for a full pool (confirmed by profiling: ~0.6s/call, the actual
    bottleneck behind an ~85s pool-wide score_many, not model prediction).
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
    """A batter's dismissal-rate edge against the opponent's actual bowling
    mix, shrunk toward and compared against her career baseline
    (`career_dismissal_rate` — pass the same value `score.py` already
    computes for the aggregate matchup signal, so both signals agree on
    what "her normal record" means).

    Returns `{"available": False, "edge_part": 0.0}` whenever the opponent's
    bowling mix or the player's vs-style splits aren't known well enough to
    say anything — never a guessed number.
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

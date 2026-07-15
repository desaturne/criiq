"""Synergy-aware team-need bonus.

Scoring each player in isolation (as `RecommendationScorer.score` does) can't
capture "this team is thin on death bowling, so a death-overs specialist is
worth more *here* than her standalone number suggests" — a real coach's
7th/8th pick partly depends on who's already in the frame. A fully sequential
re-scoring algorithm would capture this most precisely, but is harder to keep
provably well-behaved than the MILP `selection/optimize.py` already uses; this
is the practical middle ground — a single, transparent bonus computed once
per recommendation, added as its own component (not folded silently into
`model_part`), using data-collection's `player_phase_wpa` (see
`criiq_data/wpa.py`): identify the pool's single *neediest* phase (its
average combined batting+bowling win-probability-added falls furthest below
a format-wide benchmark), then reward whoever in the pool is genuinely
strong there.

The benchmark is scoped to the pool's own gender (`player_phase_wpa` has no
`gender` column of its own -- it's keyed by `player_id`, and `players.gender`
is only ever set for the ~32 identifiers split by the cross-gender-collision
fix, NULL for everyone else -- so scoping goes through a player's actual
match participation via `player_match_wpa` join `matches.gender`, the same
technique used throughout this codebase to resolve gender for players whose
`players.gender` column is NULL). Playing styles and typical phase-WPA
magnitudes genuinely differ between genders, so comparing a women's pool's
phase strength against a benchmark blended with men's data (or vice versa)
would be comparing against the wrong reference population entirely -- this
used to do exactly that (a real, fixed bug, not just a known simplification).
"""
from __future__ import annotations

import sqlite3

import pandas as pd

from ..config import SETTINGS

PHASES = ("powerplay", "middle", "death")
TEAM_NEED_CAP = 5.0


def _phase_benchmarks(conn: sqlite3.Connection, fmt: str, gender: str) -> dict[str, float]:
    df = pd.read_sql_query(
        "SELECT phase, batting_wpa_per_match, bowling_wpa_per_match FROM player_phase_wpa "
        "WHERE format=? AND player_id IN ("
        "  SELECT DISTINCT pw.player_id FROM player_match_wpa pw "
        "  JOIN matches m ON m.match_id = pw.match_id WHERE m.gender=?"
        ")", conn, params=(fmt, gender))
    if df.empty:
        return {}
    combined = df["batting_wpa_per_match"].fillna(0) + df["bowling_wpa_per_match"].fillna(0)
    return combined.groupby(df["phase"]).mean().to_dict()


def _pool_phase_averages(conn: sqlite3.Connection, player_ids: list[str], fmt: str) -> dict[str, float]:
    if not player_ids:
        return {}
    placeholders = ",".join("?" * len(player_ids))
    df = pd.read_sql_query(
        f"SELECT phase, batting_wpa_per_match, bowling_wpa_per_match FROM player_phase_wpa "
        f"WHERE format=? AND player_id IN ({placeholders})", conn, params=(fmt, *player_ids))
    if df.empty:
        return {}
    combined = df["batting_wpa_per_match"].fillna(0) + df["bowling_wpa_per_match"].fillna(0)
    return combined.groupby(df["phase"]).mean().to_dict()


def compute_team_need(conn: sqlite3.Connection, player_ids: list[str],
                       fmt: str = SETTINGS.format, gender: str = SETTINGS.gender) -> dict:
    """The pool's single neediest phase, if any phase falls below benchmark."""
    benchmarks = _phase_benchmarks(conn, fmt, gender)
    pool_avgs = _pool_phase_averages(conn, player_ids, fmt)
    gaps = {ph: pool_avgs.get(ph, 0.0) - benchmarks.get(ph, 0.0)
            for ph in PHASES if ph in benchmarks}
    if not gaps:
        return {"neediest_phase": None, "gaps": {}, "benchmarks": {}}
    neediest = min(gaps, key=gaps.get)
    return {
        "neediest_phase": neediest if gaps[neediest] < 0 else None,
        "gaps": {k: round(v, 4) for k, v in gaps.items()},
        "benchmarks": {k: round(v, 4) for k, v in benchmarks.items()},
    }


def player_team_need_bonus(conn: sqlite3.Connection, player_id: str, team_need: dict,
                           fmt: str = SETTINGS.format) -> dict:
    """Bonus for being strong in the team's single neediest phase — never a
    penalty (a player simply gets nothing if she isn't the answer to the
    team's specific gap, rather than being marked down for it).
    """
    phase = team_need.get("neediest_phase")
    if not phase:
        return {"bonus": 0.0, "phase": None}
    row = conn.execute(
        "SELECT batting_wpa_per_match, bowling_wpa_per_match FROM player_phase_wpa "
        "WHERE player_id=? AND format=? AND phase=?", (player_id, fmt, phase)).fetchone()
    if not row:
        return {"bonus": 0.0, "phase": phase}
    combined = (row["batting_wpa_per_match"] or 0.0) + (row["bowling_wpa_per_match"] or 0.0)
    surplus = combined - team_need["benchmarks"].get(phase, 0.0)
    # Checked against the real distribution (combined phase-WPA has a
    # standard deviation of ~0.065-0.078 across phases): a one-std-dev
    # surplus should read as a genuine, noticeable strength (~2-3 pts), and
    # only a two-std-dev surplus — truly exceptional — should hit the cap.
    # The first version of this used *200, which hit the cap for almost
    # every player in the pool regardless of whether she was actually the
    # answer to the team's specific gap; caught by eyeballing real output.
    bonus = round(max(0.0, min(TEAM_NEED_CAP, surplus * 35)), 1)
    return {"bonus": bonus, "phase": phase}

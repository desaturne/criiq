"""synergy-aware team-need bonus.

scoring players in isolation can't capture "this team is thin on death
bowling", so this finds the pool's single neediest phase (vs a format-wide
benchmark from player_phase_wpa) and rewards whoever is strong there, as its
own component rather than folded into model_part.

benchmark is scoped by gender via player_match_wpa join matches.gender, since
player_phase_wpa has no gender column and players.gender is mostly NULL.
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
    """the pool's single neediest phase, if any phase falls below benchmark."""
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
    """bonus for being strong in the team's neediest phase. never a penalty,
    a player who isn't the answer to the gap just gets nothing.
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
    # scale tuned against phase-wpa's real std dev (~0.065-0.078) so a genuine
    # surplus reads as a noticeable bonus without hitting the cap for everyone.
    # an earlier *200 scale hit the cap for almost every player, caught by eyeballing output.
    bonus = round(max(0.0, min(TEAM_NEED_CAP, surplus * 35)), 1)
    return {"bonus": bonus, "phase": phase}

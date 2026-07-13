"""Team-roster derivation.

`player_registry.nationality` is entirely NULL for T20 in the live DB, and
`players.nationality` (Wikidata-sourced) is only ~28% populated — neither is a
reliable way to know "which team does this player represent". The actual
match appearances (`match_players.team`, one row per player per match) are
complete and authoritative, so a player's current team is derived as the team
of their most recent appearance.
"""
from __future__ import annotations

import sqlite3

import pandas as pd

from .config import SETTINGS


def _player_id_map(conn: sqlite3.Connection) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """(unambiguous identifier->player_id, split (identifier, gender)->player_id).

    A handful of Cricsheet's own registry identifiers are confirmed reused
    across two genuinely different real people of different genders (found
    in the wild: "A Sharma" = a female India player 2009-2012 *and* a male
    UAE player 2023-2026) -- a quirk in their upstream data, not a bug in
    this codebase's matching. data-collection's `identity.resolve_players`
    already splits these into two distinct, stable player_ids (one per
    gender, `players.gender` set) rather than leaving them blended; the
    overwhelming majority of identifiers are untouched (`gender` stays NULL,
    exactly the id they've always had). Mirrors
    data-collection's `identity.player_id_map` -- kept local rather than
    imported, since this package deliberately never imports data-collection's
    own code (see features/historical.py's docstring), only reads its DB.
    """
    unambiguous: dict[str, str] = {}
    split: dict[tuple[str, str], str] = {}
    for r in conn.execute("SELECT cricsheet_identifier, gender, player_id FROM players"):
        if r["gender"] is None:
            unambiguous[r["cricsheet_identifier"]] = r["player_id"]
        else:
            split[(r["cricsheet_identifier"], r["gender"])] = r["player_id"]
    return unambiguous, split


def player_current_teams(conn: sqlite3.Connection, fmt: str = SETTINGS.format,
                          gender: str = SETTINGS.gender) -> pd.DataFrame:
    """One row per player_id: team + date of their most recent appearance."""
    appearances = pd.read_sql_query(
        "SELECT mp.player_name, mp.team, m.date "
        "FROM match_players mp JOIN matches m ON mp.match_id = m.match_id "
        "WHERE m.format = ? AND m.gender = ? AND m.date IS NOT NULL",
        conn, params=(fmt, gender))
    if appearances.empty:
        return pd.DataFrame(columns=["player_id", "team", "last_appearance_date"])

    ident_by_name = {r["player_name"]: r["identifier"]
                     for r in conn.execute("SELECT player_name, identifier FROM identifier_map")}
    unambiguous, split = _player_id_map(conn)
    idents = appearances["player_name"].map(ident_by_name)
    appearances["player_id"] = idents.map(unambiguous).astype(object)
    missing = appearances["player_id"].isna() & idents.notna()
    if missing.any():
        paired = pd.Series(list(zip(idents[missing], [gender] * missing.sum())), index=idents[missing].index)
        appearances.loc[missing, "player_id"] = paired.map(split)
    appearances = appearances.dropna(subset=["player_id"])
    if appearances.empty:
        return pd.DataFrame(columns=["player_id", "team", "last_appearance_date"])

    latest_idx = appearances.groupby("player_id")["date"].idxmax()
    latest = appearances.loc[latest_idx, ["player_id", "team", "date"]]
    return latest.rename(columns={"date": "last_appearance_date"}).reset_index(drop=True)


def team_pool(conn: sqlite3.Connection, team: str, fmt: str = SETTINGS.format,
              gender: str = SETTINGS.gender, include_inactive: bool = False) -> list[str]:
    """player_ids who currently represent `team`, eligibility-filtered.

    Hard-excludes RETIRED_* always; excludes INACTIVE unless `include_inactive`
    (e.g. an explicit recall scenario) or the registry's own recall_flag is set.
    """
    teams = player_current_teams(conn, fmt, gender)
    teams = teams[teams["team"] == team]
    if teams.empty:
        return []

    registry = pd.read_sql_query(
        "SELECT player_id, retirement_status, recall_flag FROM player_registry WHERE format = ?",
        conn, params=(fmt,))
    merged = teams.merge(registry, on="player_id", how="left")

    excluded = merged["retirement_status"].isin(SETTINGS.excluded_statuses)
    inactive = (merged["retirement_status"] == SETTINGS.inactive_status) & (merged["recall_flag"].fillna(0) == 0)
    keep = ~excluded & (include_inactive | ~inactive)
    return merged.loc[keep, "player_id"].tolist()


def known_teams(conn: sqlite3.Connection, fmt: str = SETTINGS.format,
                 gender: str = SETTINGS.gender) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT team1 AS team FROM matches WHERE format=? AND gender=? "
        "UNION SELECT DISTINCT team2 FROM matches WHERE format=? AND gender=?",
        (fmt, gender, fmt, gender))
    return sorted(r["team"] for r in rows if r["team"])

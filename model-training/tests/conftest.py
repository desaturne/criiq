"""A minimal, self-contained fixture schema — a subset of data-collection's
real `criiq.db` tables (only the columns criiq_models actually reads).
Deliberately not importing data-collection's schema/package: criiq_models
only ever reads that DB through a `conn` parameter passed in by the caller,
so tests exercise it the same way, against a tiny synthetic sqlite3 db.
"""
from __future__ import annotations

import sqlite3

import pytest

SCHEMA = """
CREATE TABLE matches (
    match_id TEXT PRIMARY KEY, format TEXT, gender TEXT, date TEXT,
    team1 TEXT, team2 TEXT, venue_id TEXT
);
CREATE TABLE match_players (
    match_id TEXT, team TEXT, player_name TEXT
);
CREATE TABLE identifier_map (
    player_name TEXT, identifier TEXT
);
CREATE TABLE players (
    player_id TEXT PRIMARY KEY, cricsheet_identifier TEXT, gender TEXT, canonical_name TEXT
);
CREATE TABLE player_registry (
    player_id TEXT, format TEXT, role TEXT, retirement_status TEXT, recall_flag INTEGER,
    age_advisory INTEGER, selection_rate REAL, icc_rank INTEGER
);
CREATE TABLE player_match_impact (
    player_id TEXT, match_id TEXT, format TEXT, date TEXT, team TEXT, opponent TEXT,
    won INTEGER, bat_strike_rate REAL, bat_contribution_pct REAL, economy REAL,
    bowl_contribution_pct REAL, wickets INTEGER, balls_bowled INTEGER,
    bowl_dot_pct REAL, bowl_boundary_pct REAL, bowl_strike_rate REAL
);
CREATE TABLE dismissal_matchup (
    format TEXT, batter_id TEXT, bowler_id TEXT, bowler_team TEXT,
    balls INTEGER, runs INTEGER, dismissals INTEGER
);
CREATE TABLE player_phase (
    player_id TEXT, format TEXT, phase TEXT, bat_strike_rate REAL, bat_team_percentile REAL,
    bowl_economy REAL, bowl_team_rank INTEGER, bowl_team_size INTEGER
);
CREATE TABLE player_impact (
    player_id TEXT, format TEXT, importance_score REAL, win_pct REAL, potm_rate REAL
);
CREATE TABLE player_career (
    player_id TEXT, format TEXT, bat_average REAL, bat_strike_rate REAL,
    wickets INTEGER, balls_bowled INTEGER
);
CREATE TABLE player_role_final (
    player_id TEXT, format TEXT, primary_role TEXT, is_keeper INTEGER DEFAULT 0,
    batting_position_median REAL, innings_batted INTEGER
);
CREATE TABLE player_match_wpa (
    player_id TEXT, match_id TEXT, format TEXT, date TEXT, team TEXT, opponent TEXT,
    batting_wpa REAL, bowling_wpa REAL, phase_breakdown_json TEXT
);
CREATE TABLE player_phase_wpa (
    player_id TEXT, format TEXT, phase TEXT, matches INTEGER,
    batting_wpa_per_match REAL, bowling_wpa_per_match REAL
);
CREATE TABLE player_styles (
    player_id TEXT PRIMARY KEY, bowling_style TEXT, batting_hand TEXT,
    playing_role TEXT, source TEXT
);
CREATE TABLE player_advanced (
    player_id TEXT, format TEXT, archetype TEXT, profile_json TEXT
);
"""


def register_player(conn: sqlite3.Connection, player_id: str, name: str,
                     identifier: str | None = None, role: str = "batter",
                     gender: str | None = None) -> None:
    """`gender`: leave `None` (the default) for an ordinary, unambiguous
    player -- only set it to simulate one half of a real Cricsheet registry
    identifier collision (see roster.py's `_player_id_map` docstring), where
    two distinct player rows share the same `identifier` but different
    `gender` values.
    """
    identifier = identifier or f"ident_{player_id}"
    conn.execute("INSERT INTO players(player_id, cricsheet_identifier, gender, canonical_name) "
                 "VALUES(?,?,?,?)", (player_id, identifier, gender, name))
    conn.execute("INSERT INTO identifier_map(player_name, identifier) VALUES(?,?)",
                 (name, identifier))
    conn.execute("INSERT INTO player_registry(player_id, format, role, retirement_status, "
                 "recall_flag, age_advisory, selection_rate, icc_rank) "
                 "VALUES(?,'T20',?,'ACTIVE',0,0,0.8,NULL)", (player_id, role))


def set_final_role(conn: sqlite3.Connection, player_id: str, primary_role: str,
                    is_keeper: bool = False, batting_position_median: float | None = None) -> None:
    conn.execute(
        "INSERT INTO player_role_final(player_id, format, primary_role, is_keeper, "
        "batting_position_median) VALUES(?,'T20',?,?,?)",
        (player_id, primary_role, int(is_keeper), batting_position_median))


def add_match(conn: sqlite3.Connection, match_id: str, date: str, team1: str, team2: str,
              venue_id: str = "test-ground", gender: str = "female") -> None:
    conn.execute("INSERT INTO matches(match_id, format, gender, date, team1, team2, venue_id) "
                 "VALUES(?,'T20',?,?,?,?,?)", (match_id, gender, date, team1, team2, venue_id))


def add_appearance(conn: sqlite3.Connection, match_id: str, team: str, name: str) -> None:
    conn.execute("INSERT INTO match_players(match_id, team, player_name) VALUES(?,?,?)",
                 (match_id, team, name))


def add_match_impact(conn: sqlite3.Connection, player_id: str, match_id: str, date: str,
                      team: str, opponent: str, won: int, bat_sr=None, bat_contrib=None,
                      economy=None, bowl_contrib=None, wickets: int = 0,
                      balls_bowled: int = 0, bowl_dot_pct=None, bowl_boundary_pct=None,
                      bowl_strike_rate=None) -> None:
    conn.execute(
        "INSERT INTO player_match_impact(player_id, match_id, format, date, team, opponent, "
        "won, bat_strike_rate, bat_contribution_pct, economy, bowl_contribution_pct, wickets, "
        "balls_bowled, bowl_dot_pct, bowl_boundary_pct, bowl_strike_rate) "
        "VALUES(?,?,'T20',?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (player_id, match_id, date, team, opponent, won, bat_sr, bat_contrib, economy,
         bowl_contrib, wickets, balls_bowled, bowl_dot_pct, bowl_boundary_pct, bowl_strike_rate))


def add_match_wpa(conn: sqlite3.Connection, player_id: str, match_id: str,
                   batting_wpa: float | None = None, bowling_wpa: float | None = None) -> None:
    conn.execute(
        "INSERT INTO player_match_wpa(player_id, match_id, format, batting_wpa, bowling_wpa) "
        "VALUES(?,?,'T20',?,?)", (player_id, match_id, batting_wpa, bowling_wpa))


def set_career_bowling(conn: sqlite3.Connection, player_id: str, wickets: int, balls_bowled: int) -> None:
    conn.execute(
        "INSERT INTO player_career(player_id, format, wickets, balls_bowled) VALUES(?,'T20',?,?)",
        (player_id, wickets, balls_bowled))


def add_bowler_matchup(conn: sqlite3.Connection, bowler_id: str, batter_id: str,
                        balls: int, runs: int, dismissals: int) -> None:
    conn.execute(
        "INSERT INTO dismissal_matchup(format, batter_id, bowler_id, balls, runs, dismissals) "
        "VALUES('T20',?,?,?,?,?)", (batter_id, bowler_id, balls, runs, dismissals))


def set_bowling_style(conn: sqlite3.Connection, player_id: str, bowling_style: str) -> None:
    conn.execute("INSERT INTO player_styles(player_id, bowling_style, source) VALUES(?,?,'test')",
                 (player_id, bowling_style))


def set_advanced_profile(conn: sqlite3.Connection, player_id: str, vs_bowling_type: dict) -> None:
    import json
    profile = {"batting": {"vs_bowling_type": vs_bowling_type}}
    conn.execute("INSERT INTO player_advanced(player_id, format, profile_json) VALUES(?,'T20',?)",
                 (player_id, json.dumps(profile)))


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    yield c
    c.close()

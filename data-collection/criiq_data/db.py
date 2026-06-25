from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import DB_PATH, ensure_dirs

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    match_id        TEXT PRIMARY KEY,
    format          TEXT NOT NULL,
    gender          TEXT NOT NULL,
    match_type      TEXT,
    season          TEXT,
    date            TEXT,
    event           TEXT,
    venue_raw       TEXT,
    venue_id        TEXT,
    city            TEXT,
    team1           TEXT,
    team2           TEXT,
    toss_winner     TEXT,
    toss_decision   TEXT,
    winner          TEXT,
    win_margin      TEXT,
    player_of_match TEXT,
    ingested_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_matches_fmt ON matches(format, gender, date);

CREATE TABLE IF NOT EXISTS deliveries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id        TEXT NOT NULL,
    innings         INTEGER,
    over            INTEGER,
    ball_in_over    INTEGER,
    batting_team    TEXT,
    bowling_team    TEXT,
    striker         TEXT,
    non_striker     TEXT,
    bowler          TEXT,
    runs_off_bat    INTEGER,
    extras          INTEGER,
    wides           INTEGER,
    noballs         INTEGER,
    runs_total      INTEGER,
    wicket_type     TEXT,
    player_dismissed TEXT
);
CREATE INDEX IF NOT EXISTS idx_deliv_match  ON deliveries(match_id);
CREATE INDEX IF NOT EXISTS idx_deliv_strike ON deliveries(striker);
CREATE INDEX IF NOT EXISTS idx_deliv_bowler ON deliveries(bowler);

CREATE TABLE IF NOT EXISTS match_players (
    match_id    TEXT NOT NULL,
    team        TEXT,
    player_name TEXT,
    UNIQUE(match_id, player_name)
);
CREATE INDEX IF NOT EXISTS idx_mp_player ON match_players(player_name);

CREATE TABLE IF NOT EXISTS identifier_map (
    player_name TEXT NOT NULL,
    identifier  TEXT NOT NULL,
    UNIQUE(player_name, identifier)
);
CREATE INDEX IF NOT EXISTS idx_idmap_id ON identifier_map(identifier);

CREATE TABLE IF NOT EXISTS people (
    identifier     TEXT PRIMARY KEY,
    name           TEXT,
    unique_name    TEXT,
    key_cricinfo   TEXT,
    key_cricinfo_2 TEXT
);
CREATE INDEX IF NOT EXISTS idx_people_cricinfo ON people(key_cricinfo);

CREATE TABLE IF NOT EXISTS players (
    player_id            TEXT PRIMARY KEY,
    cricsheet_identifier TEXT UNIQUE,
    canonical_name       TEXT,
    unique_name          TEXT,
    key_cricinfo         TEXT,
    nationality          TEXT,
    role                 TEXT,
    derived_role         TEXT,
    date_of_birth        TEXT,
    batting_hand         TEXT,
    bowling_style        TEXT,
    resolution_method    TEXT,
    needs_review         INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_players_cricinfo ON players(key_cricinfo);

CREATE TABLE IF NOT EXISTS venues (
    venue_raw      TEXT PRIMARY KEY,
    venue_id       TEXT,
    canonical_name TEXT
);

CREATE TABLE IF NOT EXISTS player_registry (
    player_id                 TEXT NOT NULL,
    format                    TEXT NOT NULL,
    retirement_status         TEXT,
    retired_formats           TEXT,
    retirement_date           TEXT,
    last_appearance_date      TEXT,
    last_appearance_opponent  TEXT,
    days_since_last_appearance INTEGER,
    date_of_birth             TEXT,
    age_at_last_match         REAL,
    career_phase              TEXT,
    role                      TEXT,
    bowling_style             TEXT,
    batting_hand              TEXT,
    nationality               TEXT,
    recall_flag               INTEGER DEFAULT 0,
    age_advisory              INTEGER DEFAULT 0,
    registry_last_updated     TEXT,
    PRIMARY KEY (player_id, format)
);

CREATE TABLE IF NOT EXISTS player_cards (
    player_id        TEXT NOT NULL,
    format           TEXT NOT NULL,
    name             TEXT,
    role             TEXT,
    nationality      TEXT,
    rfi              REAL,
    form_trend       TEXT,
    latest_match_date TEXT,
    matches_played   INTEGER,
    card_json        TEXT,
    card_last_updated TEXT,
    PRIMARY KEY (player_id, format)
);

CREATE TABLE IF NOT EXISTS player_career (
    player_id        TEXT NOT NULL,
    format           TEXT NOT NULL,
    name             TEXT,
    role             TEXT,
    bat_innings      INTEGER,
    runs             INTEGER,
    balls_faced      INTEGER,
    bat_average      REAL,
    bat_strike_rate  REAL,
    high_score       INTEGER,
    fifties          INTEGER,
    hundreds         INTEGER,
    bowl_innings     INTEGER,
    balls_bowled     INTEGER,
    overs            TEXT,
    runs_conceded    INTEGER,
    wickets          INTEGER,
    economy          REAL,
    bowl_average     REAL,
    bowl_strike_rate REAL,
    best_bowling     TEXT,
    updated_at       TEXT,
    PRIMARY KEY (player_id, format)
);

CREATE TABLE IF NOT EXISTS player_by_venue (
    player_id        TEXT NOT NULL,
    format           TEXT NOT NULL,
    venue_id         TEXT NOT NULL,
    venue_name       TEXT,
    matches          INTEGER,
    won              INTEGER,
    bat_innings      INTEGER,
    runs             INTEGER,
    balls_faced      INTEGER,
    bat_average      REAL,
    bat_strike_rate  REAL,
    high_score       INTEGER,
    bowl_innings     INTEGER,
    balls_bowled     INTEGER,
    wickets          INTEGER,
    runs_conceded    INTEGER,
    economy          REAL,
    best_bowling     TEXT,
    updated_at       TEXT,
    PRIMARY KEY (player_id, format, venue_id)
);
CREATE INDEX IF NOT EXISTS idx_venue_player ON player_by_venue(player_id, format);

CREATE TABLE IF NOT EXISTS dismissal_matchup (
    format       TEXT NOT NULL,
    batter_id    TEXT NOT NULL,
    bowler_id    TEXT NOT NULL,
    batter_name  TEXT,
    bowler_name  TEXT,
    bowler_team  TEXT,
    balls        INTEGER,
    runs         INTEGER,
    dismissals   INTEGER,
    updated_at   TEXT,
    PRIMARY KEY (format, batter_id, bowler_id)
);
CREATE INDEX IF NOT EXISTS idx_matchup_batter ON dismissal_matchup(format, batter_id);
CREATE INDEX IF NOT EXISTS idx_matchup_bowler ON dismissal_matchup(format, bowler_id);

CREATE TABLE IF NOT EXISTS player_phase (
    player_id           TEXT NOT NULL,
    format              TEXT NOT NULL,
    phase               TEXT NOT NULL,
    bat_balls           INTEGER,
    bat_runs            INTEGER,
    bat_strike_rate     REAL,
    bat_boundary_pct    REAL,
    bat_dot_pct         REAL,
    bat_dismissals      INTEGER,
    bat_team_rank       INTEGER,
    bat_team_size       INTEGER,
    bat_team_percentile REAL,
    bowl_balls          INTEGER,
    bowl_runs           INTEGER,
    bowl_wickets        INTEGER,
    bowl_economy        REAL,
    bowl_dot_pct        REAL,
    bowl_team_rank      INTEGER,
    bowl_team_size      INTEGER,
    updated_at          TEXT,
    PRIMARY KEY (player_id, format, phase)
);
CREATE INDEX IF NOT EXISTS idx_phase_player ON player_phase(player_id, format);

CREATE TABLE IF NOT EXISTS player_vs_opponent (
    player_id        TEXT NOT NULL,
    format           TEXT NOT NULL,
    opponent         TEXT NOT NULL,
    matches          INTEGER,
    won              INTEGER,
    win_pct          REAL,
    bat_innings      INTEGER,
    runs             INTEGER,
    balls_faced      INTEGER,
    bat_average      REAL,
    bat_strike_rate  REAL,
    high_score       INTEGER,
    fifties          INTEGER,
    hundreds         INTEGER,
    dismissals       INTEGER,
    bowl_innings     INTEGER,
    balls_bowled     INTEGER,
    wickets          INTEGER,
    runs_conceded    INTEGER,
    economy          REAL,
    bowl_average     REAL,
    bowl_strike_rate REAL,
    best_bowling     TEXT,
    player_of_match  INTEGER,
    updated_at       TEXT,
    PRIMARY KEY (player_id, format, opponent)
);
CREATE INDEX IF NOT EXISTS idx_vsopp_player ON player_vs_opponent(player_id, format);

CREATE TABLE IF NOT EXISTS player_impact (
    player_id            TEXT NOT NULL,
    format               TEXT NOT NULL,
    matches              INTEGER,
    bat_contribution_pct REAL,
    bowl_contribution_pct REAL,
    win_pct              REAL,
    avg_runs_in_wins     REAL,
    avg_runs_in_losses   REAL,
    player_of_match      INTEGER,
    potm_rate            REAL,
    match_winning_perfs  INTEGER,
    avg_partnership_broken REAL,
    top_order_scalps     INTEGER,
    top_order_scalp_pct  REAL,
    setting_strike_rate  REAL,
    chasing_strike_rate  REAL,
    setting_average      REAL,
    chasing_average      REAL,
    importance_score     REAL,
    importance_components TEXT,
    updated_at           TEXT,
    PRIMARY KEY (player_id, format)
);

CREATE TABLE IF NOT EXISTS player_advanced (
    player_id     TEXT NOT NULL,
    format        TEXT NOT NULL,
    archetype     TEXT,
    profile_json  TEXT,
    updated_at    TEXT,
    PRIMARY KEY (player_id, format)
);

CREATE TABLE IF NOT EXISTS player_styles (
    player_id     TEXT PRIMARY KEY,
    bowling_style TEXT,
    batting_hand  TEXT,
    playing_role  TEXT,
    source        TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS retirement_alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT,
    title           TEXT,
    link            TEXT UNIQUE,
    published       TEXT,
    matched_keyword TEXT,
    status          TEXT DEFAULT 'PENDING',
    detected_at     TEXT
);

CREATE TABLE IF NOT EXISTS discrepancies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   TEXT,
    field       TEXT,
    cricsheet_value TEXT,
    cricinfo_value  TEXT,
    detected_at TEXT
);
"""


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def table_count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]

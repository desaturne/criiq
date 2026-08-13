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
    -- Cricsheet's own `team_type` info field ('international' | 'club') --
    -- NOT the cricket format (that's `match_type`, confusingly). Lets
    -- domestic-league matches share this table with internationals while
    -- still being filterable by competition scope wherever that distinction
    -- matters (roster/registry: see registry.py, roster.py).
    team_type       TEXT DEFAULT 'international',
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

-- Anything dated after SETTINGS.data_cutoff_date lands here instead of the
-- production tables above -- a genuine, untouched forward-test set, not a
-- WHERE-clause convention every future reader has to remember. Same shape
-- as their production counterparts; ingest.py is the only writer of either.
CREATE TABLE IF NOT EXISTS matches_holdout (
    match_id        TEXT PRIMARY KEY,
    format          TEXT NOT NULL,
    gender          TEXT NOT NULL,
    match_type      TEXT,
    team_type       TEXT DEFAULT 'international',
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
    player_dismissed TEXT,
    -- Cricsheet's fielder_1/2/3 columns: the catcher (caught), keeper
    -- (stumped), or up to two fielders credited on a run out. NULL for
    -- dismissals with no fielder credit (bowled, lbw, caught and bowled --
    -- see fielding.py, which credits the bowler directly for the latter).
    fielder_1       TEXT,
    fielder_2       TEXT,
    fielder_3       TEXT
);
CREATE INDEX IF NOT EXISTS idx_deliv_match  ON deliveries(match_id);
CREATE INDEX IF NOT EXISTS idx_deliv_strike ON deliveries(striker);
CREATE INDEX IF NOT EXISTS idx_deliv_bowler ON deliveries(bowler);

CREATE TABLE IF NOT EXISTS deliveries_holdout (
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
    player_dismissed TEXT,
    fielder_1       TEXT,
    fielder_2       TEXT,
    fielder_3       TEXT
);

CREATE TABLE IF NOT EXISTS match_players (
    match_id    TEXT NOT NULL,
    team        TEXT,
    player_name TEXT,
    UNIQUE(match_id, player_name)
);
CREATE INDEX IF NOT EXISTS idx_mp_player ON match_players(player_name);

CREATE TABLE IF NOT EXISTS match_players_holdout (
    match_id    TEXT NOT NULL,
    team        TEXT,
    player_name TEXT,
    UNIQUE(match_id, player_name)
);

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

-- `cricsheet_identifier` is NOT globally unique on its own: Cricsheet's own
-- per-match player registry (rarely, but confirmed in this data) reuses the
-- same identifier across two genuinely different real people of different
-- genders -- a quirk in their upstream data, not a bug in how this codebase
-- matches players. `gender` disambiguates those cases (NULL for the
-- overwhelming majority of identifiers, which only ever appear under one
-- gender) -- see `identity.py`'s `_colliding_identifiers`/`player_id_for`.
CREATE TABLE IF NOT EXISTS players (
    player_id            TEXT PRIMARY KEY,
    cricsheet_identifier TEXT,
    gender               TEXT,
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
    needs_review         INTEGER DEFAULT 0,
    UNIQUE(cricsheet_identifier, gender)
);
CREATE INDEX IF NOT EXISTS idx_players_cricinfo ON players(key_cricinfo);
CREATE INDEX IF NOT EXISTS idx_players_identifier ON players(cricsheet_identifier);

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
    activity_signal           TEXT,
    status_reason             TEXT,
    icc_discipline            TEXT,
    selection_rate            REAL,
    window_player_matches     INTEGER,
    window_team_matches       INTEGER,
    -- True if she's had a domestic-league appearance within
    -- active_window_days -- an honest eligibility carve-out, distinct from
    -- retirement_status itself: a player can be genuinely INACTIVE/
    -- INCONSISTENT internationally (a true, unmodified label) while still
    -- being worth including in selection because she's recently played
    -- domestically. `roster.team_pool` checks this separately rather than
    -- letting it silently flip the status label to ACTIVE.
    recent_domestic_activity  INTEGER DEFAULT 0,
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

-- Career fielding: catches (including caught-and-bowled, credited to the
-- bowler), run outs (every fielder cricsheet lists gets credit -- a direct
-- hit and the fielder who set it up both count, mirroring ESPNcricinfo), and
-- stumpings (fielder_1 only -- always the keeper). See fielding.py.
CREATE TABLE IF NOT EXISTS player_fielding (
    player_id        TEXT NOT NULL,
    format            TEXT NOT NULL,
    name              TEXT,
    matches           INTEGER,
    catches           INTEGER,
    run_outs          INTEGER,
    stumpings         INTEGER,
    dismissals        INTEGER,
    dismissals_per_match REAL,
    updated_at        TEXT,
    PRIMARY KEY (player_id, format)
);
CREATE INDEX IF NOT EXISTS idx_fielding_rank ON player_fielding(format, dismissals DESC);

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
    -- Batting-first (setting) vs chasing splits, at this specific ground --
    -- mirrors player_impact's career-level setting_*/chasing_* columns
    -- (impact.py's `_sit` helper), just grouped by venue_id too.
    setting_balls        INTEGER,
    setting_runs         INTEGER,
    setting_average      REAL,
    setting_strike_rate  REAL,
    chasing_balls        INTEGER,
    chasing_runs          INTEGER,
    chasing_average      REAL,
    chasing_strike_rate  REAL,
    updated_at       TEXT,
    PRIMARY KEY (player_id, format, venue_id)
);

-- Per-ground batter-vs-bowler dismissals -- same real sample threshold as
-- dismissal_matchup (MIN_MATCHUP_BALLS, matchups.py), just scoped to one
-- venue instead of format-wide. Answers "who's gotten her out most *here*",
-- a genuinely different (and sometimes different!) question from her
-- overall bogey bowler.
CREATE TABLE IF NOT EXISTS venue_dismissal_matchup (
    format       TEXT NOT NULL,
    venue_id     TEXT NOT NULL,
    batter_id    TEXT NOT NULL,
    bowler_id    TEXT NOT NULL,
    batter_name  TEXT,
    bowler_name  TEXT,
    bowler_team  TEXT,
    balls        INTEGER,
    runs         INTEGER,
    dismissals   INTEGER,
    updated_at   TEXT,
    PRIMARY KEY (format, venue_id, batter_id, bowler_id)
);
CREATE INDEX IF NOT EXISTS idx_venue_matchup_batter ON venue_dismissal_matchup(format, venue_id, batter_id);
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

CREATE TABLE IF NOT EXISTS match_features (
    match_id              TEXT PRIMARY KEY,
    format                TEXT,
    gender                TEXT,
    date                  TEXT,
    venue_id              TEXT,
    team1                 TEXT,
    team2                 TEXT,
    toss_winner           TEXT,
    toss_decision         TEXT,
    bat_first_team        TEXT,
    toss_winner_is_team1  INTEGER,
    team1_bat_first       INTEGER,
    form_matches          INTEGER,
    team1_form_winpct     REAL,
    team2_form_winpct     REAL,
    team1_avg_score       REAL,
    team2_avg_score       REAL,
    team1_avg_conceded    REAL,
    team2_avg_conceded    REAL,
    h2h_team1_winpct      REAL,
    winpct_diff           REAL,
    avg_score_diff        REAL,
    label_team1_won       INTEGER,
    result_type           TEXT,
    updated_at            TEXT
);
CREATE INDEX IF NOT EXISTS idx_mf_fmt ON match_features(format, gender, date);

CREATE TABLE IF NOT EXISTS player_match_impact (
    player_id            TEXT NOT NULL,
    match_id             TEXT NOT NULL,
    format               TEXT,
    date                 TEXT,
    team                 TEXT,
    opponent             TEXT,
    won                  INTEGER,
    runs                 INTEGER,
    balls_faced          INTEGER,
    bat_strike_rate      REAL,
    bat_contribution_pct REAL,
    wickets              INTEGER,
    balls_bowled         INTEGER,
    runs_conceded        INTEGER,
    economy              REAL,
    bowl_contribution_pct REAL,
    bowl_dot_pct         REAL,
    bowl_boundary_pct    REAL,
    bowl_strike_rate     REAL,
    impact_rating        REAL,
    updated_at           TEXT,
    PRIMARY KEY (player_id, match_id)
);
CREATE INDEX IF NOT EXISTS idx_pmi_player ON player_match_impact(player_id, format);
CREATE INDEX IF NOT EXISTS idx_pmi_match ON player_match_impact(match_id);

CREATE TABLE IF NOT EXISTS icc_rankings (
    player_id   TEXT NOT NULL,
    format      TEXT NOT NULL,
    discipline  TEXT NOT NULL,
    gender      TEXT,
    rank        INTEGER,
    rating      INTEGER,
    player_name TEXT,
    matched     INTEGER DEFAULT 1,
    source      TEXT,
    source_url  TEXT,
    rank_date   TEXT,
    extracted_at TEXT,
    updated_at  TEXT,
    PRIMARY KEY (player_id, format, discipline)
);
CREATE INDEX IF NOT EXISTS idx_icc_fmt ON icc_rankings(format, discipline, rank);

CREATE TABLE IF NOT EXISTS player_role_final (
    player_id                TEXT NOT NULL,
    format                   TEXT NOT NULL,
    primary_role             TEXT,
    is_keeper                INTEGER DEFAULT 0,
    keeper_confidence        REAL,
    keeper_source            TEXT,
    batting_position_median  REAL,
    innings_batted           INTEGER,
    role_source              TEXT,
    updated_at               TEXT,
    PRIMARY KEY (player_id, format)
);

CREATE TABLE IF NOT EXISTS player_match_wpa (
    player_id            TEXT NOT NULL,
    match_id             TEXT NOT NULL,
    format               TEXT NOT NULL,
    date                 TEXT,
    team                 TEXT,
    opponent             TEXT,
    team_type            TEXT,
    batting_wpa          REAL,
    bowling_wpa          REAL,
    phase_breakdown_json TEXT,
    updated_at           TEXT,
    PRIMARY KEY (player_id, match_id)
);
CREATE INDEX IF NOT EXISTS idx_pmwpa_player ON player_match_wpa(player_id, format);
CREATE INDEX IF NOT EXISTS idx_pmwpa_match ON player_match_wpa(match_id);

CREATE TABLE IF NOT EXISTS player_phase_wpa (
    player_id              TEXT NOT NULL,
    format                 TEXT NOT NULL,
    phase                  TEXT NOT NULL,
    matches                INTEGER,
    batting_wpa_per_match  REAL,
    bowling_wpa_per_match  REAL,
    updated_at             TEXT,
    PRIMARY KEY (player_id, format, phase)
);

-- Recent domestic-league-only form, deliberately separate from
-- `player_career`/`player_impact` (which stay international-only, see
-- data-collection's README) -- lets an internationally-quiet player's real
-- current domestic form show up as its own signal instead of either
-- corrupting her international career line or being invisible entirely.
CREATE TABLE IF NOT EXISTS player_domestic_form (
    player_id             TEXT NOT NULL,
    format                TEXT NOT NULL,
    matches               INTEGER,
    batting_wpa_per_match REAL,
    bowling_wpa_per_match REAL,
    last_match_date       TEXT,
    updated_at            TEXT,
    PRIMARY KEY (player_id, format)
);

CREATE TABLE IF NOT EXISTS status_overrides (
    player_id         TEXT NOT NULL,
    format            TEXT NOT NULL,
    retirement_status TEXT,
    retirement_date   TEXT,
    note              TEXT,
    source            TEXT,
    updated_at        TEXT,
    PRIMARY KEY (player_id, format)
);
"""

_MIGRATIONS = [
    "ALTER TABLE player_registry ADD COLUMN icc_rank INTEGER",
    "ALTER TABLE player_registry ADD COLUMN icc_rating INTEGER",
    "ALTER TABLE player_registry ADD COLUMN activity_signal TEXT",
    "ALTER TABLE player_registry ADD COLUMN status_reason TEXT",
    "ALTER TABLE player_registry ADD COLUMN icc_discipline TEXT",
    "ALTER TABLE player_registry ADD COLUMN selection_rate REAL",
    "ALTER TABLE player_registry ADD COLUMN window_player_matches INTEGER",
    "ALTER TABLE player_registry ADD COLUMN window_team_matches INTEGER",
    "ALTER TABLE player_registry ADD COLUMN recent_domestic_activity INTEGER DEFAULT 0",
    "ALTER TABLE icc_rankings ADD COLUMN matched INTEGER DEFAULT 1",
    "ALTER TABLE icc_rankings ADD COLUMN source TEXT",
    "ALTER TABLE icc_rankings ADD COLUMN source_url TEXT",
    "ALTER TABLE icc_rankings ADD COLUMN rank_date TEXT",
    "ALTER TABLE icc_rankings ADD COLUMN extracted_at TEXT",
    "ALTER TABLE player_match_impact ADD COLUMN bowl_dot_pct REAL",
    "ALTER TABLE player_match_impact ADD COLUMN bowl_boundary_pct REAL",
    "ALTER TABLE player_match_impact ADD COLUMN bowl_strike_rate REAL",
    "ALTER TABLE matches ADD COLUMN team_type TEXT DEFAULT 'international'",
    "ALTER TABLE player_match_wpa ADD COLUMN team_type TEXT",
    "ALTER TABLE player_by_venue ADD COLUMN setting_balls INTEGER",
    "ALTER TABLE player_by_venue ADD COLUMN setting_runs INTEGER",
    "ALTER TABLE player_by_venue ADD COLUMN setting_average REAL",
    "ALTER TABLE player_by_venue ADD COLUMN setting_strike_rate REAL",
    "ALTER TABLE player_by_venue ADD COLUMN chasing_balls INTEGER",
    "ALTER TABLE player_by_venue ADD COLUMN chasing_runs INTEGER",
    "ALTER TABLE player_by_venue ADD COLUMN chasing_average REAL",
    "ALTER TABLE player_by_venue ADD COLUMN chasing_strike_rate REAL",
    "ALTER TABLE deliveries ADD COLUMN fielder_1 TEXT",
    "ALTER TABLE deliveries ADD COLUMN fielder_2 TEXT",
    "ALTER TABLE deliveries ADD COLUMN fielder_3 TEXT",
    "ALTER TABLE deliveries_holdout ADD COLUMN fielder_1 TEXT",
    "ALTER TABLE deliveries_holdout ADD COLUMN fielder_2 TEXT",
    "ALTER TABLE deliveries_holdout ADD COLUMN fielder_3 TEXT",
]


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _migrate_players_gender_scoped(conn: sqlite3.Connection) -> None:
    """one-time migration: `cricsheet_identifier TEXT UNIQUE` ->
    `UNIQUE(cricsheet_identifier, gender)`. SQLite can't ALTER a UNIQUE
    constraint in place, so this recreates the table; existing rows keep
    `gender=NULL` until identity.py's `resolve_players` fills them in.
    idempotent: a no-op once the `gender` column exists.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(players)")}
    if not cols or "gender" in cols:
        return
    conn.executescript("""
        CREATE TABLE players_new (
            player_id            TEXT PRIMARY KEY,
            cricsheet_identifier TEXT,
            gender               TEXT,
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
            needs_review         INTEGER DEFAULT 0,
            UNIQUE(cricsheet_identifier, gender)
        );
        INSERT INTO players_new (player_id, cricsheet_identifier, canonical_name,
            unique_name, key_cricinfo, nationality, role, derived_role, date_of_birth,
            batting_hand, bowling_style, resolution_method, needs_review)
        SELECT player_id, cricsheet_identifier, canonical_name, unique_name,
            key_cricinfo, nationality, role, derived_role, date_of_birth,
            batting_hand, bowling_style, resolution_method, needs_review
        FROM players;
        DROP TABLE players;
        ALTER TABLE players_new RENAME TO players;
        CREATE INDEX IF NOT EXISTS idx_players_cricinfo ON players(key_cricinfo);
        CREATE INDEX IF NOT EXISTS idx_players_identifier ON players(cricsheet_identifier);
    """)
    conn.commit()


def _backfill_international_team_type(conn: sqlite3.Connection) -> None:
    """matches ingested before domestic leagues existed have `team_type IS
    NULL`, not `'international'`. any reader filtering on
    `team_type='international'` would otherwise silently exclude them.
    idempotent: only touches rows still NULL.
    """
    conn.execute("UPDATE matches SET team_type='international' WHERE team_type IS NULL")
    conn.commit()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate_players_gender_scoped(conn)
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass
    _backfill_international_team_type(conn)
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

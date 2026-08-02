"""
database.py — opens the three SQLite databases the backend uses.

1) criiq.db  — Sushma's analytics database, built by the criiq_data pipeline.
               We open it READ-ONLY: the pipeline owns this file and rebuilds
               it, so the backend must never write to it.

2) app.db    — the backend's OWN database (created automatically on first run)
               for things the pipeline knows nothing about: upcoming fixtures,
               saved Playing-XI selections, manually added players.

3) auth.db   — login credentials and sessions, kept in their own file so that
               resetting app.db (fixtures/selections/manual players) can never
               accidentally wipe out user accounts, and so a login session can
               be revoked server-side (see sessions table + auth.py logout).

Why plain sqlite3 and not SQLAlchemy?  Everything we do is a handful of simple
SELECT/INSERT statements. SQLAlchemy would force us to describe all 25 pipeline
tables as Python classes for zero benefit. sqlite3 is in the standard library —
nothing extra to install, nothing extra to learn.
"""

import os
import sqlite3
from pathlib import Path

import bcrypt

BACKEND_DIR = Path(__file__).parent

# --- 1. Sushma's database (read-only) --------------------------------------

CRIIQ_DB_PATH = Path(
    os.environ.get(
        "CRIIQ_DB", BACKEND_DIR.parent / "data-collection" / "data" / "criiq.db"
    )
)

if not CRIIQ_DB_PATH.exists():
    raise SystemExit(
        f"criiq.db not found at {CRIIQ_DB_PATH}\n"
        "Run the pipeline first:  cd ../data-collection && python run.py refresh"
    )

# mode=ro opens the file read-only; check_same_thread=False lets FastAPI use
# the connection from its worker threads (safe here because we only read).
criiq_db = sqlite3.connect(f"file:{CRIIQ_DB_PATH}?mode=ro", uri=True,
                           check_same_thread=False)
criiq_db.row_factory = sqlite3.Row  # rows behave like dicts: row["name"]

# --- 2. Our own database (writable) -----------------------------------------

APP_DB_PATH = Path(os.environ.get("APP_DB", BACKEND_DIR / "app.db"))
app_db = sqlite3.connect(APP_DB_PATH, check_same_thread=False)
app_db.row_factory = sqlite3.Row

app_db.executescript(
    """
    CREATE TABLE IF NOT EXISTS fixtures (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        team1   TEXT NOT NULL,
        team2   TEXT NOT NULL,
        venue   TEXT NOT NULL,
        date    TEXT NOT NULL,           -- YYYY-MM-DD
        format  TEXT NOT NULL DEFAULT 'T20I',
        gender  TEXT NOT NULL DEFAULT 'female'
    );

    CREATE TABLE IF NOT EXISTS manual_players (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT NOT NULL,
        country       TEXT,
        role          TEXT NOT NULL,
        batting_hand  TEXT,
        bowling_style TEXT,
        status        TEXT NOT NULL DEFAULT 'ACTIVE'
    );

    -- One saved squad per match: the three id-lists stored as JSON text.
    CREATE TABLE IF NOT EXISTS selections (
        match_id   TEXT PRIMARY KEY,
        squad_json TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """
)

# --- 3. Auth database (writable, separate file) ------------------------------

AUTH_DB_PATH = Path(os.environ.get("AUTH_DB", BACKEND_DIR / "auth.db"))
auth_db = sqlite3.connect(AUTH_DB_PATH, check_same_thread=False)
auth_db.row_factory = sqlite3.Row

auth_db.executescript(
    """
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        email         TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        name          TEXT NOT NULL,
        role          TEXT NOT NULL DEFAULT 'coach'
    );

    -- One row per issued login token, so a token can be revoked (logout)
    -- instead of staying valid until it naturally expires.
    CREATE TABLE IF NOT EXISTS sessions (
        jti        TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """
)


def _ensure_column(connection, table: str, column: str, ddl: str) -> bool:
    """Adds the column if it is missing. Returns True if it was just added."""
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column in columns:
        return False
    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    return True


# Rows that already existed when `status` was introduced predate the whole
# admin-approval workflow, so they were implicitly approved. Without this
# backfill the ALTER's DEFAULT stamps every one of them 'Inactive', which
# retroactively locks out working accounts (it did exactly that to the seeded
# demo coach: login started answering "Registration pending admin approval").
# Only accounts created through /auth/register after this point start pending.
if _ensure_column(auth_db, "users", "status", "TEXT NOT NULL DEFAULT 'Inactive'"):
    auth_db.execute("UPDATE users SET status = 'Active'")
    auth_db.commit()

_ensure_column(auth_db, "users", "country", "TEXT NOT NULL DEFAULT 'India'")

# --- 4. Seed data (only inserted the first time) -----------------------------

DEMO_COACH_EMAIL = "rahul@criiq.local"


def seed():
    """Create the demo coach account and a few upcoming fixtures."""
    demo = auth_db.execute(
        "SELECT id, status FROM users WHERE email = ?", (DEMO_COACH_EMAIL,)
    ).fetchone()
    if demo is None:
        has_users = auth_db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        if not has_users:
            pw_hash = bcrypt.hashpw(b"coach1234", bcrypt.gensalt()).decode()
            auth_db.execute(
                "INSERT INTO users (email, password_hash, name, role, status, country) VALUES (?,?,?,?,?,?)",
                (DEMO_COACH_EMAIL, pw_hash, "Rahul Coach", "coach", "Active", "India"),
            )
            auth_db.commit()
    elif demo["status"] != "Active":
        # Repairs databases migrated before the backfill above existed. This is
        # the documented demo login (see backend/README.md) — it is only ever
        # useful in the "Active" state, so keep it that way on every boot.
        auth_db.execute("UPDATE users SET status = 'Active' WHERE id = ?", (demo["id"],))
        auth_db.commit()

    has_fixtures = app_db.execute("SELECT COUNT(*) AS n FROM fixtures").fetchone()["n"]
    if not has_fixtures:
        app_db.executemany(
            "INSERT INTO fixtures (team1, team2, venue, date, format, gender) "
            "VALUES (?,?,?,?,?,?)",
            [
                ("India", "Australia", "Wankhede Stadium, Mumbai", "2026-08-02", "T20I", "female"),
                ("India", "England", "Lord's, London", "2026-08-10", "T20I", "female"),
                ("India", "New Zealand", "Eden Park, Auckland", "2026-08-21", "T20I", "female"),
            ],
        )
    app_db.commit()


seed()

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import DB_PATH


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Read-only connection to the data-collection SQLite DB.

    This module never writes to criiq.db — it owns its own derived
    artifacts (models, feature tables) under artifacts/player_recommendation.
    """
    path = Path(db_path or DB_PATH)
    if not path.exists():
        raise FileNotFoundError(
            f"criiq.db not found at {path}. Run data-collection's pipeline first, "
            "or set CRIIQ_DB to point at an existing database."
        )
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn

"""ground-name -> venue_id resolution for the CLI's --venue argument.

matches against venues.canonical_name (the human-readable form) instead of
requiring the raw venue_id slug. match quality varies by ground since only
some have curated aliases, so every candidate is surfaced rather than
silently picking the top LIKE hit.
"""
from __future__ import annotations

import sqlite3


def find_venues(conn: sqlite3.Connection, name: str, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        "SELECT DISTINCT venue_id, canonical_name FROM venues "
        "WHERE canonical_name LIKE ? ORDER BY canonical_name LIMIT ?",
        (f"%{name}%", limit)).fetchall()
    return [dict(r) for r in rows]


def resolve_venue(conn: sqlite3.Connection, name: str | None) -> tuple[str | None, list[dict]]:
    """(resolved venue_id or None, candidates).

    - no name: (None, []), no venue specified.
    - exactly one fuzzy match: resolved automatically.
    - zero matches: falls back to treating name as already a raw venue_id
      (backward-compatible with callers passing the slug directly).
    - multiple matches: unresolved, candidates lists every match so the
      caller can show a "did you mean" prompt instead of guessing.
    """
    if not name:
        return None, []
    candidates = find_venues(conn, name)
    if len(candidates) == 1:
        return candidates[0]["venue_id"], candidates
    if len(candidates) == 0:
        return name, []
    return None, candidates

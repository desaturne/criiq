"""Ground-name -> venue_id resolution for the CLI's `--venue` argument.

`--venue` used to require the pre-computed slug (`venue_id`) directly -- a
value nobody typing a ground name by hand would know. `venues.canonical_name`
(data-collection's `identity.normalise_venues`) is the human-readable form to
match against instead.

Known quality caveat, not papered over: `normalise_venues` only has curated
aliases for a small set of grounds (`identity._VENUE_ALIASES`); everything
else gets a crude `raw.split(",")[0]` canonical name, so fuzzy match quality
varies by ground. Surfacing every candidate (not silently picking the top
LIKE hit) is the mitigation -- the same lesson as the CLI's `_find_player`
picking an unintended same-named player earlier in this project's history.
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

    - No `name`: (None, []) -- no venue specified, unchanged behaviour.
    - Exactly one fuzzy match: resolved automatically.
    - Zero matches: falls back to treating `name` as already a raw
      `venue_id` (backward-compatible with anyone already passing the slug
      directly, e.g. scripts/tests) -- `candidates` stays empty either way.
    - Multiple matches: unresolved (`None`), `candidates` lists every match
      so the caller can show a "did you mean" prompt instead of silently
      guessing one.
    """
    if not name:
        return None, []
    candidates = find_venues(conn, name)
    if len(candidates) == 1:
        return candidates[0]["venue_id"], candidates
    if len(candidates) == 0:
        return name, []
    return None, candidates

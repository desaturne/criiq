"""
roster_index.py — one-time index of "who currently plays for which team,
and in which gender" derived from real match appearances (match_players/
matches), built once at import time and kept in memory as plain dicts.

Why this exists: players.nationality / player_cards.nationality can be
plain wrong, not just missing. A real case found live: "ER Oza", 107 real
United Arab Emirates appearances 2018-2026, tagged nationality="India" in
both stored columns (an upstream heritage/name mixup, not a genuinely
uncovered player). model-training/criiq_models/roster.py already solves the
identical problem for its own purposes by deriving "current team" from
match participation instead of trusting the stored column; this mirrors
that same logic for the backend's player list/filter/detail endpoints.

Recomputing this per-request via SQL window-function subqueries (the first
version of this fix) cost several seconds per /players call, since it ran
2-3 times per request (count query, page query, display-correction query).
A single full scan at import time costs ~0.2s for ~120k appearance rows and
turns every per-request lookup into an O(1) dict/set operation.
"""

from database import criiq_db

_current_team: dict[str, str] = {}
_team_members: dict[str, set[str]] = {}
_gender_members: dict[str, set[str]] = {}


def _build() -> None:
    rows = criiq_db.execute(
        """SELECT im.identifier AS identifier, mp.team AS team, m.date AS date, m.gender AS gender
           FROM match_players mp
           JOIN matches m ON mp.match_id = m.match_id
           JOIN identifier_map im ON im.player_name = mp.player_name
           WHERE m.team_type = 'international' AND m.date IS NOT NULL"""
    ).fetchall()

    best_date: dict[str, str] = {}
    for r in rows:
        ident, team, date, gender = r["identifier"], r["team"], r["date"], r["gender"]
        if gender:
            _gender_members.setdefault(gender, set()).add(ident)
        if date > best_date.get(ident, ""):
            best_date[ident] = date
            _current_team[ident] = team

    for ident, team in _current_team.items():
        _team_members.setdefault(team, set()).add(ident)


_build()


def current_team(identifier: str | None) -> str | None:
    """The team of this player's most recent international appearance, or
    None if they've never appeared in one (or the identifier is unknown)."""
    return _current_team.get(identifier) if identifier else None


def team_members(team: str) -> set[str]:
    """cricsheet_identifiers whose current team is exactly `team`."""
    return _team_members.get(team, set())


def gender_members(gender: str) -> set[str]:
    """cricsheet_identifiers who have ever appeared in a match tagged this gender."""
    return _gender_members.get(gender, set())

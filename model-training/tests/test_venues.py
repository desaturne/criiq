from __future__ import annotations

from criiq_models.venues import resolve_venue
from tests.conftest import add_venue


def test_resolve_venue_single_match(conn):
    add_venue(conn, "lords-london", "Lord's, London")
    conn.commit()

    venue_id, candidates = resolve_venue(conn, "Lord's")
    assert venue_id == "lords-london"
    assert len(candidates) == 1


def test_resolve_venue_no_match_falls_back_to_raw_input(conn):
    # backward-compatible with anyone already passing the slug directly.
    venue_id, candidates = resolve_venue(conn, "some-existing-slug")
    assert venue_id == "some-existing-slug"
    assert candidates == []


def test_resolve_venue_ambiguous_returns_none_with_candidates(conn):
    add_venue(conn, "mcg", "Melbourne Cricket Ground")
    add_venue(conn, "scg", "Sydney Cricket Ground")
    conn.commit()

    venue_id, candidates = resolve_venue(conn, "Cricket Ground")
    assert venue_id is None
    assert len(candidates) == 2


def test_resolve_venue_none_input(conn):
    assert resolve_venue(conn, None) == (None, [])

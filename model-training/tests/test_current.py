from __future__ import annotations

from criiq_models.features.current import resolve_role
from tests.conftest import register_player, set_final_role


def test_resolve_role_prefers_player_role_final_over_registry(conn):
    # registry says "bowler" (noisy Wikidata-derived), but the finalized,
    # data-driven role (batting position + Wikipedia keeper lookup) says
    # she's actually a wicket-keeper batter — the final source must win.
    register_player(conn, "p1", "A Player", role="bowler")
    set_final_role(conn, "p1", "batter", is_keeper=True, batting_position_median=5.0)
    conn.commit()

    bucket, is_keeper, position = resolve_role(conn, "p1", "T20")
    assert bucket == "batter"
    assert is_keeper is True
    assert position == 5.0


def test_resolve_role_falls_back_to_registry_when_no_final_role(conn):
    register_player(conn, "p1", "A Player", role="bowler")
    conn.commit()

    bucket, is_keeper, position = resolve_role(conn, "p1", "T20")
    assert bucket == "bowler"
    assert is_keeper is False
    assert position is None

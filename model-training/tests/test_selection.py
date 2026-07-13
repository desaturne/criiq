from __future__ import annotations

import dataclasses

from criiq_models.config import SETTINGS
from criiq_models.selection.optimize import select_xi


def _player(pid, score, bucket, is_keeper=False, batting_position_median=None):
    return {"player_id": pid, "name": pid, "score": score, "role_bucket": bucket,
            "is_keeper": is_keeper, "batting_position_median": batting_position_median}


def test_select_xi_respects_role_quotas_and_maximizes_score():
    # 4 batters, 4 bowlers, 2 all-rounders — pick 6 total, >=3 batting-capable, >=3 bowling-capable.
    players = [
        _player("bat1", 90, "batter"), _player("bat2", 80, "batter"),
        _player("bat3", 70, "batter"), _player("bat4", 10, "batter"),
        _player("bowl1", 85, "bowler"), _player("bowl2", 75, "bowler"),
        _player("bowl3", 65, "bowler"), _player("bowl4", 5, "bowler"),
        _player("ar1", 60, "all-rounder"), _player("ar2", 1, "all-rounder"),
    ]
    settings = dataclasses.replace(SETTINGS, xi_size=6, min_batting_capable=3,
                                    min_bowling_capable=3, pool_size=20)

    result = select_xi(players, settings)
    xi_ids = {p["player_id"] for p in result["xi"]}

    assert len(xi_ids) == 6
    bat_count = sum(1 for p in result["xi"] if p["role_bucket"] in ("batter", "all-rounder"))
    bowl_count = sum(1 for p in result["xi"] if p["role_bucket"] in ("bowler", "all-rounder"))
    assert bat_count >= 3
    assert bowl_count >= 3
    # the weakest players (bat4, bowl4, ar2) should be dropped in favour of higher scores
    assert "bat4" not in xi_ids and "bowl4" not in xi_ids and "ar2" not in xi_ids
    # top scorer must always be included
    assert "bat1" in xi_ids


def test_select_xi_handles_empty_pool():
    settings = dataclasses.replace(SETTINGS, xi_size=11)
    result = select_xi([], settings)
    assert result["xi"] == [] and result["pool"] == []


def test_select_xi_forces_in_a_keeper_when_one_exists_in_the_pool():
    # the only keeper is the lowest scorer — a plain top-N pick would drop her.
    players = [
        _player("bat1", 90, "batter"), _player("bat2", 80, "batter"),
        _player("bat3", 70, "batter"),
        _player("bowl1", 85, "bowler"), _player("bowl2", 75, "bowler"),
        _player("bowl3", 65, "bowler"),
        _player("keeper1", 5, "batter", is_keeper=True),
    ]
    settings = dataclasses.replace(SETTINGS, xi_size=6, min_batting_capable=2,
                                    min_bowling_capable=2, min_keepers=1, pool_size=20)

    result = select_xi(players, settings)
    xi_ids = {p["player_id"] for p in result["xi"]}
    assert "keeper1" in xi_ids
    assert result["constraints"]["min_keepers"] == 1


def test_select_xi_skips_keeper_constraint_when_pool_has_no_keeper_data():
    players = [_player(f"p{i}", 100 - i, "batter") for i in range(8)]
    settings = dataclasses.replace(SETTINGS, xi_size=6, min_batting_capable=0,
                                    min_bowling_capable=0, min_keepers=1, pool_size=20)

    result = select_xi(players, settings)
    assert len(result["xi"]) == 6
    assert result["constraints"]["min_keepers"] == 0


def test_select_xi_finds_keeper_even_outside_the_display_pool_cutoff():
    # regression test: a real bug had the top-`pool_size` truncation happen
    # BEFORE the MILP ran, so a keeper scoring below the display cutoff was
    # invisible to the constraint by the time it was applied, silently
    # degrading min_keepers to 0. 30 batters score above the sole keeper,
    # who must still be pulled in from outside the pool_size=20 cutoff.
    players = [_player(f"bat{i}", 100 - i, "batter") for i in range(30)]
    players.append(_player("keeper1", 1, "batter", is_keeper=True))
    settings = dataclasses.replace(SETTINGS, xi_size=11, min_batting_capable=0,
                                    min_bowling_capable=0, min_keepers=1, pool_size=20)

    result = select_xi(players, settings)
    xi_ids = {p["player_id"] for p in result["xi"]}
    pool_ids = {p["player_id"] for p in result["pool"]}

    assert result["constraints"]["min_keepers"] == 1
    assert "keeper1" in xi_ids
    # the XI must always be a subset of the returned display pool
    assert xi_ids <= pool_ids


def test_select_xi_orders_output_like_a_team_sheet_not_by_score():
    # opener2 (position 2) scores lowest of all but must still lead the XI
    # (locked opener slot); bowlers trail the core batting order, ranked by
    # their OWN score (bowler_no_pos outscores bowler_late, so bats higher
    # in the tail) rather than by a raw historical position number.
    players = [
        _player("opener1", 90, "batter", batting_position_median=1),
        _player("opener2", 20, "batter", batting_position_median=2),
        _player("middle1", 70, "batter", batting_position_median=4),
        _player("allrounder1", 60, "all-rounder", batting_position_median=6),
        _player("bowler_no_pos", 50, "bowler", batting_position_median=None),
        _player("bowler_late", 40, "bowler", batting_position_median=9),
    ]
    settings = dataclasses.replace(SETTINGS, xi_size=6, min_batting_capable=0,
                                    min_bowling_capable=0, min_keepers=0, min_openers=2)

    result = select_xi(players, settings)
    order = [p["player_id"] for p in result["xi"]]
    assert order == ["opener1", "opener2", "middle1", "allrounder1", "bowler_no_pos", "bowler_late"]


def test_select_xi_forces_in_openers_even_outside_the_display_pool_cutoff():
    # the only two recognized openers score the lowest — a plain top-N pick
    # would leave the team with no opener at all.
    players = [_player(f"mid{i}", 100 - i, "batter", batting_position_median=4) for i in range(9)]
    players.append(_player("opener1", 5, "batter", batting_position_median=1))
    players.append(_player("opener2", 4, "batter", batting_position_median=2))
    settings = dataclasses.replace(SETTINGS, xi_size=6, min_batting_capable=0,
                                    min_bowling_capable=0, min_keepers=0, min_openers=2)

    result = select_xi(players, settings)
    order = [p["player_id"] for p in result["xi"]]
    assert result["constraints"]["min_openers"] == 2
    assert order[0] == "opener1" and order[1] == "opener2"


def test_select_xi_overflow_opener_competes_on_score_not_locked_to_slot_three():
    # three players score high enough and are opener-capable, but only 2
    # opener slots exist. The 3rd opener (opener3) should NOT be forced into
    # "position 3" just because she's opener-tagged -- she competes purely
    # on score against the core batting order, and here she beats everyone
    # in that pool, so she still bats at 3, but ahead of a *higher-scoring*
    # nominal top-order player she must fall behind on merit.
    players = [
        _player("opener1", 95, "batter", batting_position_median=1),
        _player("opener2", 90, "batter", batting_position_median=2),
        _player("opener3", 55, "batter", batting_position_median=1),  # overflow opener, mid score
        _player("core_high", 80, "batter", batting_position_median=4),
        _player("core_low", 40, "batter", batting_position_median=5),
    ]
    settings = dataclasses.replace(SETTINGS, xi_size=5, min_batting_capable=0,
                                    min_bowling_capable=0, min_keepers=0, min_openers=2)

    result = select_xi(players, settings)
    order = [p["player_id"] for p in result["xi"]]
    # locked opener slots: the top-2 scoring openers only
    assert order[0] == "opener1" and order[1] == "opener2"
    # the overflow opener (55) ranks below core_high (80) on pure merit
    assert order.index("core_high") < order.index("opener3")
    assert order.index("opener3") < order.index("core_low")

from __future__ import annotations

from criiq_models.features.current import build_extra_context
from criiq_models.recommend.matchup_matrix import head_to_head_matrix
from criiq_models.recommend.strength import strength_context
from tests.conftest import add_appearance, add_bowler_matchup, add_match, register_player


def test_head_to_head_matrix_finds_bogey_best_and_ignores_tiny_samples(conn):
    # my batter faces two of their bowlers: one dismisses him often, one he
    # scores freely off. And my bowler dominates one of their batters.
    add_bowler_matchup(conn, bowler_id="oppX", batter_id="myB", balls=30, runs=20, dismissals=3,
                       batter_name="My Batter", bowler_name="Opp Xavier")
    add_bowler_matchup(conn, bowler_id="oppY", batter_id="myB", balls=40, runs=70, dismissals=0,
                       batter_name="My Batter", bowler_name="Opp Yusuf")
    add_bowler_matchup(conn, bowler_id="myP", batter_id="oppZ", balls=24, runs=18, dismissals=2,
                       batter_name="Opp Zed", bowler_name="My Pacer")
    # a sub-6-ball pairing must be excluded, not surfaced as a "matchup"
    add_bowler_matchup(conn, bowler_id="oppX", batter_id="myB2", balls=3, runs=5, dismissals=1,
                       batter_name="My Batter Two", bowler_name="Opp Xavier")
    conn.commit()

    m = head_to_head_matrix(conn, my_ids=["myB", "myB2", "myP"],
                            opponent_ids=["oppX", "oppY", "oppZ"])
    bat = m["batting"]["My Batter"]
    assert bat["bogey"]["opponent"] == "Opp Xavier" and bat["bogey"]["dismissals"] == 3
    assert bat["best"]["opponent"] == "Opp Yusuf"          # most runs scored
    assert "My Batter Two" not in m["batting"]             # 3 balls, filtered out

    bowl = m["bowling"]["My Pacer"]
    assert bowl["best"]["opponent"] == "Opp Zed" and bowl["best"]["dismissals"] == 2


def test_opponent_players_scopes_batting_matchup_by_bowler_id_not_team(conn):
    # The batting matchup is normally scoped by bowler_team; when a specific
    # opponent XI is named it must instead scope by those bowlers' ids, so it
    # counts a bowler regardless of which team string the row was stored under.
    register_player(conn, "myB", "My Batter", role="batter")
    add_bowler_matchup(conn, bowler_id="oppX", batter_id="myB", balls=30, runs=20, dismissals=2,
                       batter_name="My Batter", bowler_name="Opp Xavier", bowler_team="Australia")
    conn.commit()

    # opponent team is "England" (so bowler_team='Australia' would NOT match),
    # but oppX is named in the opponent XI -> the matchup is still picked up.
    ctx = build_extra_context(conn, "myB", "England", "T20", "female", opponent_players=["oppX"])
    assert ctx.matchup_balls == 30
    assert ctx.matchup_dismissal_rate == 2 / 30

    # without the named XI, "England" doesn't match the stored bowler_team -> no matchup.
    ctx_team = build_extra_context(conn, "myB", "England", "T20", "female", opponent_roster=[])
    assert ctx_team.matchup_balls == 0


def test_strength_context_flags_lopsided_matchup_only_for_the_stronger_side(conn):
    # Bigland fields 4 ICC-ranked players, Smalland none. The matchup is
    # lopsided when asked from Bigland's side (they can rest players), and not
    # from Smalland's -- mirroring "India vs Nepal": ICC-ranked count, not
    # padded importance, is the strength signal.
    add_match(conn, "m1", "2026-01-01", "Bigland", "Smalland")
    for i in range(4):
        register_player(conn, f"big{i}", f"Big {i}", role="batter")
        add_appearance(conn, "m1", "Bigland", f"Big {i}")
        conn.execute("UPDATE player_registry SET icc_rank=? WHERE player_id=?", (i + 1, f"big{i}"))
    for i in range(4):
        register_player(conn, f"small{i}", f"Small {i}", role="batter")
        add_appearance(conn, "m1", "Smalland", f"Small {i}")
    conn.commit()

    ctx = strength_context(conn, "Bigland", "Smalland", "T20", "female")
    assert ctx["team"]["icc_ranked"] == 4 and ctx["opponent"]["icc_ranked"] == 0
    assert ctx["lopsided"] is True
    assert ctx["stronger_side"] == "Bigland"

    # the weaker side must NOT be told it can rotate
    ctx_rev = strength_context(conn, "Smalland", "Bigland", "T20", "female")
    assert ctx_rev["lopsided"] is False

from __future__ import annotations

from criiq_models.features.style_matchup import opponent_bowling_mix, style_matchup_edge
from tests.conftest import (add_appearance, add_match, register_player,
                            set_advanced_profile, set_bowling_style)


def _seed_opponent_attack(conn):
    # Australia's eligible bowlers: 2 spin, 1 pace -> a spin-heavy attack.
    register_player(conn, "spin1", "Spin One", role="bowler")
    register_player(conn, "spin2", "Spin Two", role="bowler")
    register_player(conn, "pace1", "Pace One", role="bowler")
    set_bowling_style(conn, "spin1", "spin")
    set_bowling_style(conn, "spin2", "spin")
    set_bowling_style(conn, "pace1", "pace")
    add_match(conn, "m1", "2023-01-01", "Australia", "India")
    for pid, name in [("spin1", "Spin One"), ("spin2", "Spin Two"), ("pace1", "Pace One")]:
        add_appearance(conn, "m1", "Australia", name)
    conn.commit()


def test_opponent_bowling_mix_reflects_attack_composition(conn):
    _seed_opponent_attack(conn)
    mix = opponent_bowling_mix(conn, "Australia", "T20", "female")
    assert mix is not None
    assert mix["spin"] == 2 / 3
    assert mix["pace"] == 1 / 3


def test_opponent_bowling_mix_none_when_too_thin(conn):
    register_player(conn, "solo", "Solo Bowler", role="bowler")
    set_bowling_style(conn, "solo", "pace")
    add_match(conn, "m1", "2023-01-01", "Australia", "India")
    add_appearance(conn, "m1", "Australia", "Solo Bowler")
    conn.commit()
    assert opponent_bowling_mix(conn, "Australia", "T20", "female") is None


def test_style_matchup_edge_penalizes_weakness_against_dominant_style(conn):
    _seed_opponent_attack(conn)
    register_player(conn, "star", "Star Batter", role="batter")
    # strong vs pace (low dismissal rate), weak vs spin (high dismissal rate)
    set_advanced_profile(conn, "star", {
        "pace": {"balls": 100, "dismissals": 2, "runs": 150, "strike_rate": 150.0, "average": 75.0},
        "spin": {"balls": 100, "dismissals": 10, "runs": 80, "strike_rate": 80.0, "average": 8.0},
    })
    conn.commit()

    result = style_matchup_edge(conn, "star", "Australia", career_dismissal_rate=0.05,
                                 fmt="T20", gender="female")
    # Australia leans spin-heavy (2/3) and she's worse vs spin -> a tough matchup
    assert result["available"] is True
    assert result["edge_part"] < 0
    assert result["opponent_bowling_mix"]["spin"] == 2 / 3


def test_style_matchup_edge_unavailable_without_data(conn):
    register_player(conn, "star", "Star Batter", role="batter")
    conn.commit()
    result = style_matchup_edge(conn, "star", "Australia", career_dismissal_rate=0.05,
                                 fmt="T20", gender="female")
    assert result == {"available": False, "edge_part": 0.0}


def test_style_matchup_edge_requires_career_baseline(conn):
    result = style_matchup_edge(conn, "star", "Australia", career_dismissal_rate=None,
                                 fmt="T20", gender="female")
    assert result == {"available": False, "edge_part": 0.0}

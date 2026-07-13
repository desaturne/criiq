from __future__ import annotations

from criiq_models.recommend.team_need import compute_team_need, player_team_need_bonus


def _seed_phase_wpa(conn, player_id, phase, batting=0.0, bowling=0.0, matches=10):
    conn.execute(
        "INSERT INTO player_phase_wpa(player_id, format, phase, matches, "
        "batting_wpa_per_match, bowling_wpa_per_match) VALUES(?,'T20',?,?,?,?)",
        (player_id, phase, matches, batting, bowling))


def test_compute_team_need_identifies_pool_weak_phase(conn):
    # format-wide benchmark: a mix of strong and weak death performers
    _seed_phase_wpa(conn, "benchmark1", "death", batting=0.05)
    _seed_phase_wpa(conn, "benchmark2", "death", batting=-0.03)
    _seed_phase_wpa(conn, "benchmark1", "powerplay", batting=0.01)
    _seed_phase_wpa(conn, "benchmark2", "powerplay", batting=0.01)
    # this pool (p1, p2) is weak at death specifically, average at powerplay
    _seed_phase_wpa(conn, "p1", "death", batting=-0.05)
    _seed_phase_wpa(conn, "p2", "death", batting=-0.06)
    _seed_phase_wpa(conn, "p1", "powerplay", batting=0.01)
    _seed_phase_wpa(conn, "p2", "powerplay", batting=0.01)
    conn.commit()

    team_need = compute_team_need(conn, ["p1", "p2"], "T20")
    assert team_need["neediest_phase"] == "death"


def test_compute_team_need_none_when_pool_is_not_below_benchmark(conn):
    _seed_phase_wpa(conn, "benchmark1", "death", batting=-0.05)
    _seed_phase_wpa(conn, "p1", "death", batting=0.05)  # pool is ABOVE benchmark
    conn.commit()

    team_need = compute_team_need(conn, ["p1"], "T20")
    assert team_need["neediest_phase"] is None


def test_player_team_need_bonus_rewards_strength_in_neediest_phase(conn):
    _seed_phase_wpa(conn, "benchmark1", "death", batting=0.0)
    # pool average (-0.10 + 0.02) / 2 = -0.04, still below the 0.0 benchmark,
    # even though the specialist herself is individually above it.
    _seed_phase_wpa(conn, "weak_team_member", "death", batting=-0.10)
    _seed_phase_wpa(conn, "death_specialist", "death", batting=0.02)
    conn.commit()

    team_need = compute_team_need(conn, ["weak_team_member", "death_specialist"], "T20")
    assert team_need["neediest_phase"] == "death"

    specialist_bonus = player_team_need_bonus(conn, "death_specialist", team_need, "T20")
    weak_member_bonus = player_team_need_bonus(conn, "weak_team_member", team_need, "T20")

    assert specialist_bonus["bonus"] > 0
    assert specialist_bonus["phase"] == "death"
    # never a penalty -- a player below the benchmark simply gets nothing
    assert weak_member_bonus["bonus"] == 0.0


def test_player_team_need_bonus_zero_when_no_neediest_phase(conn):
    result = player_team_need_bonus(conn, "anyone", {"neediest_phase": None}, "T20")
    assert result == {"bonus": 0.0, "phase": None}

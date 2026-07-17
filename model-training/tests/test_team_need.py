from __future__ import annotations

from criiq_models.recommend.team_need import compute_team_need, player_team_need_bonus
from tests.conftest import add_match, add_match_wpa


def _seed_phase_wpa(conn, player_id, phase, batting=0.0, bowling=0.0, matches=10):
    conn.execute(
        "INSERT INTO player_phase_wpa(player_id, format, phase, matches, "
        "batting_wpa_per_match, bowling_wpa_per_match) VALUES(?,'T20',?,?,?,?)",
        (player_id, phase, matches, batting, bowling))


def _seed_benchmark_gender(conn, player_id, gender="female"):
    """The format-wide benchmark is scoped to one gender (see team_need.py's
    docstring) via each player's real match participation, not a `gender`
    column on `player_phase_wpa` itself (it has none) -- so a benchmark
    player needs a `player_match_wpa`/`matches` row of the right gender to be
    included in `_phase_benchmarks` at all.
    """
    mid = f"m_{player_id}"
    add_match(conn, mid, "2024-01-01", "Team A", "Team B", gender=gender)
    add_match_wpa(conn, player_id, mid, batting_wpa=0.0)


def test_compute_team_need_identifies_pool_weak_phase(conn):
    # format-wide benchmark: a mix of strong and weak death performers
    _seed_phase_wpa(conn, "benchmark1", "death", batting=0.05)
    _seed_phase_wpa(conn, "benchmark2", "death", batting=-0.03)
    _seed_phase_wpa(conn, "benchmark1", "powerplay", batting=0.01)
    _seed_phase_wpa(conn, "benchmark2", "powerplay", batting=0.01)
    _seed_benchmark_gender(conn, "benchmark1")
    _seed_benchmark_gender(conn, "benchmark2")
    # this pool (p1, p2) is weak at death specifically, average at powerplay
    _seed_phase_wpa(conn, "p1", "death", batting=-0.05)
    _seed_phase_wpa(conn, "p2", "death", batting=-0.06)
    _seed_phase_wpa(conn, "p1", "powerplay", batting=0.01)
    _seed_phase_wpa(conn, "p2", "powerplay", batting=0.01)
    conn.commit()

    team_need = compute_team_need(conn, ["p1", "p2"], "T20", "female")
    assert team_need["neediest_phase"] == "death"


def test_compute_team_need_ignores_the_other_genders_benchmark(conn):
    # A men's-only benchmark of very strong death hitters must not drag a
    # women's pool's own (perfectly average, 0.0) death performance below
    # its correctly-scoped (also 0.0) benchmark -- the exact bug this fix
    # guards against: before it, this format-wide benchmark blended both
    # genders, so a men's benchmark of +0.20 could wrongly make a genuinely
    # average women's pool look "weak" by comparison.
    _seed_phase_wpa(conn, "male_star", "death", batting=0.20)
    _seed_benchmark_gender(conn, "male_star", gender="male")
    _seed_phase_wpa(conn, "p1", "death", batting=0.0)
    conn.commit()

    team_need = compute_team_need(conn, ["p1"], "T20", "female")
    # No female benchmark data exists at all -- "death" isn't even a key,
    # so it can't be flagged as the neediest phase.
    assert team_need["neediest_phase"] is None
    assert "death" not in team_need["benchmarks"]


def test_compute_team_need_none_when_pool_is_not_below_benchmark(conn):
    _seed_phase_wpa(conn, "benchmark1", "death", batting=-0.05)
    _seed_benchmark_gender(conn, "benchmark1")
    _seed_phase_wpa(conn, "p1", "death", batting=0.05)  # pool is ABOVE benchmark
    conn.commit()

    team_need = compute_team_need(conn, ["p1"], "T20", "female")
    assert team_need["neediest_phase"] is None


def test_player_team_need_bonus_rewards_strength_in_neediest_phase(conn):
    _seed_phase_wpa(conn, "benchmark1", "death", batting=0.0)
    _seed_benchmark_gender(conn, "benchmark1")
    # pool average (-0.10 + 0.02) / 2 = -0.04, still below the 0.0 benchmark,
    # even though the specialist herself is individually above it.
    _seed_phase_wpa(conn, "weak_team_member", "death", batting=-0.10)
    _seed_phase_wpa(conn, "death_specialist", "death", batting=0.02)
    conn.commit()

    team_need = compute_team_need(conn, ["weak_team_member", "death_specialist"], "T20", "female")
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

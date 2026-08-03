from __future__ import annotations

from criiq_models.simulate.outcomes import build_bowler_profile


def test_build_bowler_profile_reports_phase_rank_and_size(conn):
    conn.execute(
        "INSERT INTO player_phase(player_id, format, phase, bowl_economy, bowl_team_rank, bowl_team_size) "
        "VALUES('p1','T20','powerplay',6.5,3,12)")
    conn.execute(
        "INSERT INTO player_phase(player_id, format, phase, bowl_economy, bowl_team_rank, bowl_team_size) "
        "VALUES('p1','T20','death',9.0,40,45)")
    conn.commit()

    profile = build_bowler_profile(conn, "p1", "T20")

    assert profile.phase_rank == {"powerplay": 3, "death": 40}
    assert profile.phase_rank_size == {"powerplay": 12, "death": 45}


def test_build_bowler_profile_skips_phases_with_no_rank(conn):
    conn.execute(
        "INSERT INTO player_phase(player_id, format, phase, bowl_economy, bowl_team_rank, bowl_team_size) "
        "VALUES('p1','T20','middle',7.0,NULL,NULL)")
    conn.commit()

    profile = build_bowler_profile(conn, "p1", "T20")

    assert profile.phase_rank == {}
    assert profile.phase_rank_size == {}

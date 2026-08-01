from __future__ import annotations

from criiq_models.roster import known_teams, player_current_teams, team_pool
from tests.conftest import add_appearance, add_match, register_player


def test_current_team_uses_most_recent_appearance(conn):
    register_player(conn, "p1", "A Player")
    add_match(conn, "m1", "2023-01-01", "India", "Australia")
    add_appearance(conn, "m1", "India", "A Player")
    add_match(conn, "m2", "2024-06-01", "England", "India")
    add_appearance(conn, "m2", "England", "A Player")  # switched teams (transfer/eligibility case)
    conn.commit()

    teams = player_current_teams(conn, "T20", "female")
    row = teams[teams["player_id"] == "p1"].iloc[0]
    assert row["team"] == "England"
    assert row["last_appearance_date"] == "2024-06-01"


def test_current_team_ignores_domestic_franchise_appearances(conn):
    # once domestic league matches share this same table shape, a player's
    # most recent appearance can be a franchise game, not international.
    # `player_current_teams` must still resolve her real country from
    # international history, or she'd vanish from her own team_pool().
    register_player(conn, "p1", "A Player")
    add_match(conn, "m1", "2023-01-01", "India", "Australia")
    add_appearance(conn, "m1", "India", "A Player")
    add_match(conn, "m2", "2025-01-01", "Some Franchise", "Other Franchise",
              team_type="club")
    add_appearance(conn, "m2", "Some Franchise", "A Player")
    conn.commit()

    teams = player_current_teams(conn, "T20", "female")
    row = teams[teams["player_id"] == "p1"].iloc[0]
    assert row["team"] == "India"

    pool = team_pool(conn, "India", "T20", "female")
    assert "p1" in pool


def test_team_pool_includes_inactive_player_with_recent_domestic_activity(conn):
    # `retirement_status=INACTIVE` stays a true, unmodified fact (an earlier
    # version wrongly flipped it to "ACTIVE" for domestically-active players).
    # pool inclusion is driven by the separate `recent_domestic_activity` flag.
    register_player(conn, "p1", "Domestically Active")
    conn.execute("UPDATE player_registry SET retirement_status='INACTIVE', "
                 "recent_domestic_activity=1 WHERE player_id='p1'")
    register_player(conn, "p2", "Genuinely Gone")
    conn.execute("UPDATE player_registry SET retirement_status='INACTIVE', "
                 "recent_domestic_activity=0 WHERE player_id='p2'")
    add_match(conn, "m1", "2023-01-01", "India", "Australia")
    add_appearance(conn, "m1", "India", "Domestically Active")
    add_appearance(conn, "m1", "India", "Genuinely Gone")
    conn.commit()

    pool = team_pool(conn, "India", "T20", "female")
    assert "p1" in pool
    assert "p2" not in pool


def test_team_pool_excludes_retired(conn):
    register_player(conn, "p1", "Active Player")
    register_player(conn, "p2", "Retired Player")
    conn.execute("UPDATE player_registry SET retirement_status='RETIRED_ALL' WHERE player_id='p2'")
    add_match(conn, "m1", "2023-01-01", "India", "Australia")
    add_appearance(conn, "m1", "India", "Active Player")
    add_appearance(conn, "m1", "India", "Retired Player")
    conn.commit()

    pool = team_pool(conn, "India", "T20", "female")
    assert "p1" in pool
    assert "p2" not in pool


def test_known_teams_lists_both_sides(conn):
    add_match(conn, "m1", "2023-01-01", "India", "Australia")
    conn.commit()
    teams = known_teams(conn, "T20", "female")
    assert "India" in teams and "Australia" in teams


def test_cross_gender_identifier_collision_resolves_to_the_right_person(conn):
    # real bug: a shared Cricsheet identifier can map to two different
    # players (one per gender). data-collection splits these into distinct
    # player rows, so `_player_id_map` must resolve each gender's appearances
    # to its own id, not silently pick one or exclude both.
    register_player(conn, "shared_female", "A Shared", identifier="shared_ident", gender="female")
    register_player(conn, "shared_male", "A Shared", identifier="shared_ident", gender="male")
    add_match(conn, "m1", "2023-01-01", "India", "Australia", gender="female")
    add_appearance(conn, "m1", "India", "A Shared")
    add_match(conn, "m2", "2024-01-01", "Pakistan", "UAE", gender="male")
    add_appearance(conn, "m2", "UAE", "A Shared")
    conn.commit()

    female_teams = player_current_teams(conn, "T20", "female")
    row = female_teams[female_teams["player_id"] == "shared_female"]
    assert len(row) == 1 and row.iloc[0]["team"] == "India"
    assert "shared_male" not in female_teams["player_id"].tolist()

    male_teams = player_current_teams(conn, "T20", "male")
    row = male_teams[male_teams["player_id"] == "shared_male"]
    assert len(row) == 1 and row.iloc[0]["team"] == "UAE"
    assert "shared_female" not in male_teams["player_id"].tolist()

    pool = team_pool(conn, "India", "T20", "female")
    assert "shared_female" in pool
    assert "shared_male" not in pool

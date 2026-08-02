from __future__ import annotations

import pytest

from criiq_models.features.current import build_extra_context, build_model_features, resolve_role
from tests.conftest import (add_domestic_form, add_match, add_match_impact,
                            add_match_wpa, add_venue_matchup, add_venue_record,
                            register_player, set_final_role)


def test_resolve_role_prefers_player_role_final_over_registry(conn):
    # registry says "bowler" but the finalized role data says she's actually
    # a wicket-keeper batter, so the final source must win.
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


def test_domestic_form_shrinks_toward_international_career_baseline(conn):
    # no leakage concern here (unlike historical.py), player_domestic_form is
    # read as-is. her international WPA is low but domestic form is strong,
    # so the blended feature should land between the two.
    register_player(conn, "p1", "A Player")
    add_match(conn, "m0", "2020-01-01", "India", "Australia")
    add_match_impact(conn, "p1", "m0", "2020-01-01", "India", "Australia", won=1)
    add_match_wpa(conn, "p1", "m0", batting_wpa=0.01, date="2020-01-01")
    add_domestic_form(conn, "p1", matches=5, batting_wpa_per_match=0.20,
                       last_match_date="2025-12-01")
    conn.commit()

    feats = build_model_features(conn, "p1", "Australia", None, "T20")
    assert feats["domestic_form_matches"] == 5
    # shrink(5 domestic matches toward career_batting_wpa=0.01, k=8):
    # (5*0.20 + 8*0.01) / 13
    assert feats["domestic_form_batting_wpa"] == pytest.approx((5 * 0.20 + 8 * 0.01) / 13)
    assert feats["career_batting_wpa"] == pytest.approx(0.01)
    # blended value sits strictly between the two, neither dominates outright.
    assert 0.01 < feats["domestic_form_batting_wpa"] < 0.20


def test_domestic_form_absent_defaults_to_zero_not_none(conn):
    register_player(conn, "p1", "A Player")
    add_match(conn, "m0", "2020-01-01", "India", "Australia")
    add_match_impact(conn, "p1", "m0", "2020-01-01", "India", "Australia", won=1)
    conn.commit()

    feats = build_model_features(conn, "p1", "Australia", None, "T20")
    assert feats["domestic_form_matches"] == 0
    assert feats["domestic_form_batting_wpa"] is None


def test_venue_context_includes_setting_chasing_and_bogey_bowler(conn):
    register_player(conn, "p1", "A Player")
    add_venue_record(conn, "p1", "lords-london", "Lord's, London", matches=3,
                      setting_average=45.0, setting_strike_rate=130.0,
                      chasing_average=20.0, chasing_strike_rate=110.0)
    # two Australian bowlers dismissed her at Lord's: Bowler X twice (the
    # real bogey, by count not rate), Bowler Y once at a higher rate.
    add_venue_matchup(conn, "p1", "bx", "lords-london", "Bowler X", "Australia",
                       balls=20, runs=25, dismissals=2)
    add_venue_matchup(conn, "p1", "by", "lords-london", "Bowler Y", "Australia",
                       balls=6, runs=5, dismissals=1)
    conn.commit()

    ctx = build_extra_context(conn, "p1", "Australia", "T20", "female", venue_id="lords-london")
    assert ctx.venue_name == "Lord's, London"
    assert ctx.venue_setting_average == 45.0
    assert ctx.venue_chasing_average == 20.0
    assert ctx.venue_bogey_bowler["bowler_name"] == "Bowler X"
    assert ctx.venue_bogey_bowler["dismissals"] == 2


def test_venue_context_no_bogey_bowler_when_no_venue_specified(conn):
    register_player(conn, "p1", "A Player")
    add_venue_record(conn, "p1", "lords-london", "Lord's, London", matches=3)
    conn.commit()

    ctx = build_extra_context(conn, "p1", "Australia", "T20", "female", venue_id=None)
    assert ctx.venue_name is None
    assert ctx.venue_bogey_bowler is None

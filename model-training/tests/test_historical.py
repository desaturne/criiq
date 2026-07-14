from __future__ import annotations

import pandas as pd
import pytest

from criiq_models.features.historical import build_training_table
from tests.conftest import add_match, add_match_impact, add_match_wpa, register_player


def test_career_features_are_strictly_pre_match(conn):
    register_player(conn, "p1", "A Player")
    dates = ["2023-01-01", "2023-02-01", "2023-03-01"]
    contribs = [10.0, 20.0, 30.0]
    for i, (d, c) in enumerate(zip(dates, contribs)):
        mid = f"m{i}"
        add_match(conn, mid, d, "India", "Australia")
        add_match_impact(conn, "p1", mid, d, "India", "Australia", won=1, bat_contrib=c)
    conn.commit()

    table = build_training_table(conn, "T20", "female").sort_values("date").reset_index(drop=True)
    assert len(table) == 3

    assert table.loc[0, "career_matches"] == 0
    assert pd.isna(table.loc[0, "career_bat_contribution_pct"])

    assert table.loc[1, "career_matches"] == 1
    assert table.loc[1, "career_bat_contribution_pct"] == 10.0

    assert table.loc[2, "career_matches"] == 2
    assert table.loc[2, "career_bat_contribution_pct"] == 15.0

    # the row's own (same-match) contribution must never leak into its own feature
    assert table.loc[2, "career_bat_contribution_pct"] != 30.0


def test_venue_and_opponent_history_isolated_per_group(conn):
    register_player(conn, "p1", "A Player")
    add_match(conn, "m0", "2023-01-01", "India", "England", venue_id="ground-a")
    add_match_impact(conn, "p1", "m0", "2023-01-01", "India", "England", won=1, bat_contrib=40.0)
    add_match(conn, "m1", "2023-02-01", "India", "Australia", venue_id="ground-b")
    add_match_impact(conn, "p1", "m1", "2023-02-01", "India", "Australia", won=0, bat_contrib=5.0)
    conn.commit()

    table = build_training_table(conn, "T20", "female").sort_values("date").reset_index(drop=True)
    # the Australia/ground-b row has no prior history vs Australia or at ground-b,
    # even though the player has overall career history (vs England, at ground-a)
    row = table.loc[1]
    assert row["career_matches"] == 1
    assert row["vs_opp_matches"] == 0
    assert row["venue_matches"] == 0
    # zero-sample vs-opponent/venue records shrink fully to the career prior
    # (40.0, her only prior match) rather than going missing — a raw NaN at
    # n=0 is exactly the out-of-distribution pattern that caused live-scoring
    # queries with no venue specified to produce wildly unstable predictions
    # (see features/current.py and features/common.shrink_series).
    assert row["vs_opp_bat_contribution_pct"] == pytest.approx(40.0)
    assert row["venue_bat_contribution_pct"] == pytest.approx(40.0)


def test_wpa_target_and_career_wpa_feature_are_strictly_pre_match(conn):
    # Mirrors test_career_features_are_strictly_pre_match, for the new
    # WPA-based target/feature: the whole point of switching off
    # contribution-share is that WPA reflects actual match-winning value
    # (see criiq_data/wpa.py), so its leakage-safety matters just as much.
    register_player(conn, "p1", "A Player")
    dates = ["2023-01-01", "2023-02-01", "2023-03-01"]
    wpas = [0.05, 0.10, -0.02]
    for i, (d, w) in enumerate(zip(dates, wpas)):
        mid = f"m{i}"
        add_match(conn, mid, d, "India", "Australia")
        add_match_impact(conn, "p1", mid, d, "India", "Australia", won=1)
        add_match_wpa(conn, "p1", mid, batting_wpa=w)
    conn.commit()

    table = build_training_table(conn, "T20", "female").sort_values("date").reset_index(drop=True)

    assert table.loc[0, "batting_wpa"] == 0.05          # target: this match's own WPA
    assert pd.isna(table.loc[0, "career_batting_wpa"])   # no prior matches yet

    assert table.loc[1, "batting_wpa"] == 0.10
    assert table.loc[1, "career_batting_wpa"] == 0.05    # only the first match's WPA

    assert table.loc[2, "batting_wpa"] == -0.02
    assert table.loc[2, "career_batting_wpa"] == pytest.approx(0.075)  # mean(0.05, 0.10)
    # the row's own (same-match) WPA must never leak into its own feature
    assert table.loc[2, "career_batting_wpa"] != -0.02


def test_domestic_form_attaches_by_date_not_by_row_alignment(conn):
    # Two international rows (m0, m1) and one domestic-only match (d0) dated
    # between them. An international row isn't a member of the domestic
    # subgroup, so this specifically exercises the merge_asof bridge in
    # `_attach_domestic_form` rather than a plain groupby/transform.
    register_player(conn, "p1", "A Player")
    add_match(conn, "m0", "2023-01-01", "India", "Australia")
    add_match_impact(conn, "p1", "m0", "2023-01-01", "India", "Australia", won=1)
    add_match_wpa(conn, "p1", "m0", batting_wpa=0.05, date="2023-01-01")

    add_match_wpa(conn, "p1", "d0", batting_wpa=0.20, date="2023-02-01", team_type="club")

    add_match(conn, "m1", "2023-03-01", "India", "Australia")
    add_match_impact(conn, "p1", "m1", "2023-03-01", "India", "Australia", won=1)
    add_match_wpa(conn, "p1", "m1", batting_wpa=0.10, date="2023-03-01")
    conn.commit()

    table = build_training_table(conn, "T20", "female").sort_values("date").reset_index(drop=True)
    assert len(table) == 2   # d0 has no player_match_impact row -- domestic
                              # matches never become training rows themselves

    m0 = table.loc[0]
    assert m0["domestic_form_matches"] == 0   # d0 (Feb) is after m0 (Jan) -- not yet known
    assert pd.isna(m0["domestic_form_batting_wpa"])

    m1 = table.loc[1]
    assert m1["domestic_form_matches"] == 1   # d0 (Feb) is before m1 (Mar) -- now known
    # shrink_series((1*0.20 + 8*0.05) / (1+8)) toward m1's own prior
    # career_batting_wpa (0.05, from m0 alone) -- capped_n=min(1,10)=1,
    # k=shrinkage_prior_matches=8.
    assert m1["domestic_form_batting_wpa"] == pytest.approx((1 * 0.20 + 8 * 0.05) / 9)

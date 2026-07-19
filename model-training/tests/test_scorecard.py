"""Scorecard + coach-perspective tests (`simulate/scorecard.py`) against
small, hand-built synthetic ball logs -- generic by construction (operates
purely on a ball log + name map), so no team-specific behavior to test here.
"""
from __future__ import annotations

import pandas as pd

from criiq_models.simulate.scorecard import (batting_scorecard, bowling_phase_summary, bowling_rotation,
                                              bowling_scorecard, coach_perspective)


def _row(**kw):
    base = {"innings": 1, "over": 0, "ball_in_over": 1, "phase": "powerplay", "striker": "b0", "bowler": "w0",
            "outcome": "1", "runs_off_bat": 1, "extras": 0, "runs_total": 1, "is_legal": True,
            "is_wicket": False, "dismissed": None}
    base.update(kw)
    return base


def test_batting_scorecard_computes_real_strike_rate_and_excludes_wides_from_balls_faced():
    rows = [
        _row(striker="b0", outcome="4", runs_off_bat=4, runs_total=4),
        _row(striker="b0", outcome="wide", runs_off_bat=0, extras=1, runs_total=1, is_legal=False),
        _row(striker="b0", outcome="1", runs_off_bat=1, runs_total=1),
    ]
    df = pd.DataFrame(rows)
    card = batting_scorecard(df, name_map={"b0": "Test Batter"})
    assert len(card) == 1
    row = card[0]
    assert row["runs"] == 5
    assert row["balls"] == 2  # the wide is excluded from balls faced
    assert row["strike_rate"] == 250.0
    assert row["status"] == "not out"


def test_batting_scorecard_flags_century_and_out_status():
    rows = [_row(striker="b0", outcome="4", runs_off_bat=4, runs_total=4) for _ in range(25)]
    rows.append(_row(striker="b0", outcome="wicket", runs_off_bat=0, runs_total=0, is_wicket=True, dismissed="b0"))
    df = pd.DataFrame(rows)
    card = batting_scorecard(df, name_map={"b0": "Century Maker"})
    row = card[0]
    assert row["runs"] == 100
    assert row["status"] == "out"
    assert "Century" in row["highlight"]


def test_bowling_scorecard_excludes_byes_from_runs_conceded_and_computes_economy():
    rows = [
        _row(bowler="w0", outcome="4", runs_off_bat=4, runs_total=4),
        _row(bowler="w0", outcome="bye", runs_off_bat=0, extras=1, runs_total=1),
        _row(bowler="w0", outcome="0", runs_off_bat=0, runs_total=0),
    ]
    df = pd.DataFrame(rows)
    card = bowling_scorecard(df, name_map={"w0": "Test Bowler"})
    row = card[0]
    assert row["runs_conceded"] == 4  # bye excluded (rulebook-cricket.md sec 4.3/6)
    assert row["overs"] == "0.3"
    assert row["economy"] == 8.0


def test_bowling_scorecard_flags_best_bowler():
    rows = []
    for i in range(3):
        rows.append(_row(bowler="w0", outcome="wicket", runs_off_bat=0, runs_total=0,
                          is_wicket=True, dismissed=f"b{i}"))
    rows.append(_row(bowler="w1", outcome="4", runs_off_bat=4, runs_total=4))
    df = pd.DataFrame(rows)
    card = bowling_scorecard(df, name_map={"w0": "Star Bowler", "w1": "Other Bowler"})
    best = next(r for r in card if r["player_id"] == "w0")
    assert best["wickets"] == 3
    assert "Pick of the bowlers" in best["highlight"]


def test_coach_perspective_generalizes_to_either_side_of_any_named_teams():
    key_moments = [
        {"innings": 1, "over": 8, "ball": 4, "type": "batting_milestone",
         "description": "X reaches 50", "win_prob_before": 0.5, "win_prob_after": 0.55},
        {"innings": 2, "over": 19, "ball": 3, "type": "turning_point",
         "description": "Big six wins it", "win_prob_before": 0.4, "win_prob_after": 0.9},
    ]
    rep = {"batting_first_team": "Nepal", "bowling_first_team": "Oman",
           "first_innings_score": 150, "first_innings_wickets": 4,
           "second_innings_score": 151, "second_innings_wickets": 6,
           "target": 151, "winner": "Oman"}
    for coach_team in ("Nepal", "Oman"):
        narrative = coach_perspective(rep, key_moments, coach_team)
        assert coach_team in narrative
        assert "Result:" in narrative


def test_bowling_rotation_reports_one_row_per_over_with_its_own_phase_and_figures():
    rows = [
        _row(over=0, ball_in_over=1, bowler="w0", phase="powerplay", outcome="4", runs_off_bat=4, runs_total=4),
        _row(over=0, ball_in_over=2, bowler="w0", phase="powerplay", outcome="0", runs_off_bat=0, runs_total=0),
        _row(over=6, ball_in_over=1, bowler="w1", phase="middle", outcome="wicket", runs_off_bat=0,
             runs_total=0, is_wicket=True, dismissed="b0"),
        _row(over=15, ball_in_over=1, bowler="w2", phase="death", outcome="6", runs_off_bat=6, runs_total=6),
    ]
    df = pd.DataFrame(rows)
    rotation = bowling_rotation(df)
    assert len(rotation) == 3  # one row per distinct over
    powerplay_over = next(r for r in rotation if r["over"] == 1)
    assert powerplay_over["phase"] == "powerplay"
    assert powerplay_over["runs_conceded"] == 4
    death_over = next(r for r in rotation if r["over"] == 16)
    assert death_over["phase"] == "death"
    assert death_over["runs_conceded"] == 6
    middle_over = next(r for r in rotation if r["over"] == 7)
    assert middle_over["wickets"] == 1


def test_bowling_phase_summary_aggregates_by_bowler_within_each_phase():
    rows = [
        _row(over=0, ball_in_over=1, bowler="w0", phase="powerplay", outcome="4", runs_off_bat=4, runs_total=4),
        _row(over=1, ball_in_over=1, bowler="w1", phase="powerplay", outcome="0", runs_off_bat=0, runs_total=0),
        _row(over=15, ball_in_over=1, bowler="w0", phase="death", outcome="6", runs_off_bat=6, runs_total=6),
    ]
    df = pd.DataFrame(rows)
    rotation = bowling_rotation(df)
    summary = bowling_phase_summary(rotation)
    assert set(summary["powerplay"]) == {"w0", "w1"}
    assert summary["powerplay"]["w0"]["runs"] == 4
    assert summary["death"]["w0"]["runs"] == 6
    assert "w1" not in summary["death"]

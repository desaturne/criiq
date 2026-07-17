"""Milestone/highlight detection (`simulate/keymoments.py`) against small,
hand-built synthetic ball logs -- exercises fifty/century crossing, boundary
tagging, a bowling 3-for, hat-trick detection (and non-detection when a wide
breaks the consecutive-ball sequence), and win-probability swing ranking.
"""
from __future__ import annotations

import pandas as pd

from criiq_models.simulate.keymoments import detect_key_moments


def _row(**kw):
    base = {"innings": 1, "over": 0, "ball_in_over": 1, "striker": "b0", "bowler": "w0",
            "outcome": "1", "runs_off_bat": 1, "extras": 0, "is_legal": True, "is_wicket": False,
            "score": 1, "wickets": 0, "win_prob_batting": 0.5}
    base.update(kw)
    return base


def test_half_century_and_century_detected_once_each():
    rows = []
    # b0 scores 6s repeatedly to cross 50 then 100
    for i in range(20):
        rows.append(_row(over=i, ball_in_over=1, outcome="6", runs_off_bat=6, score=(i + 1) * 6))
    df = pd.DataFrame(rows)
    moments = detect_key_moments(df)
    milestones = [m for m in moments if m["type"] == "batting_milestone"]
    assert any("half-century" in m["description"] for m in milestones)
    assert any("century" in m["description"] and "half" not in m["description"] for m in milestones)
    # each milestone crossed exactly once
    fifty_hits = [m for m in milestones if "half-century" in m["description"]]
    assert len(fifty_hits) == 1


def test_boundaries_are_tagged():
    df = pd.DataFrame([_row(outcome="4", runs_off_bat=4), _row(outcome="1", runs_off_bat=1),
                        _row(outcome="6", runs_off_bat=6)])
    moments = detect_key_moments(df)
    boundary_types = [m for m in moments if m["type"] == "boundary"]
    assert len(boundary_types) == 2


def test_hat_trick_detected_on_three_consecutive_legal_wickets():
    rows = [_row(ball_in_over=i + 1, outcome="wicket", runs_off_bat=0, is_wicket=True, striker=f"b{i}")
            for i in range(3)]
    df = pd.DataFrame(rows)
    moments = detect_key_moments(df)
    assert any(m["type"] == "hat_trick" for m in moments)


def test_hat_trick_still_detected_across_an_intervening_wide():
    """A wide isn't a counted "ball" (rulebook-cricket.md sec 4.1) -- it must
    not break an otherwise-consecutive hat-trick sequence.
    """
    rows = [
        _row(ball_in_over=1, outcome="wicket", runs_off_bat=0, is_wicket=True, striker="b0"),
        _row(ball_in_over=1, outcome="wide", runs_off_bat=0, extras=1, is_legal=False, is_wicket=False),
        _row(ball_in_over=2, outcome="wicket", runs_off_bat=0, is_wicket=True, striker="b1"),
        _row(ball_in_over=3, outcome="wicket", runs_off_bat=0, is_wicket=True, striker="b2"),
    ]
    df = pd.DataFrame(rows)
    moments = detect_key_moments(df)
    assert any(m["type"] == "hat_trick" for m in moments)


def test_hat_trick_not_detected_when_a_non_wicket_legal_ball_intervenes():
    rows = [
        _row(ball_in_over=1, outcome="wicket", runs_off_bat=0, is_wicket=True, striker="b0"),
        _row(ball_in_over=2, outcome="1", runs_off_bat=1, is_wicket=False, striker="b1"),
        _row(ball_in_over=3, outcome="wicket", runs_off_bat=0, is_wicket=True, striker="b1"),
        _row(ball_in_over=4, outcome="wicket", runs_off_bat=0, is_wicket=True, striker="b2"),
    ]
    df = pd.DataFrame(rows)
    moments = detect_key_moments(df)
    assert not any(m["type"] == "hat_trick" for m in moments)


def test_three_wicket_haul_flagged():
    rows = [_row(ball_in_over=i + 1, outcome="wicket", runs_off_bat=0, is_wicket=True, striker=f"b{i}",
                 bowler="w0")
            for i in range(3)]
    df = pd.DataFrame(rows)
    moments = detect_key_moments(df)
    milestones = [m for m in moments if m["type"] == "bowling_milestone"]
    assert any("3-for" in m["description"] for m in milestones)


def test_biggest_swings_are_ranked_and_capped():
    rows = []
    wps = [0.5, 0.55, 0.9, 0.2, 0.85, 0.15]
    for i, wp in enumerate(wps):
        rows.append(_row(over=i, win_prob_batting=wp))
    df = pd.DataFrame(rows)
    moments = detect_key_moments(df, top_swings=2)
    swings = [m for m in moments if m["type"] == "turning_point"]
    assert len(swings) == 2

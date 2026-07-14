from __future__ import annotations

from criiq_models.recommend.render import render_team_sheet, render_xi_analysis


def _explained(pid, name, score, bucket, is_keeper=False, reasoning=None):
    return {"player_id": pid, "name": name, "role_bucket": bucket, "is_keeper": is_keeper,
            "batting_position_median": None, "score": score,
            "reasoning": reasoning or [f"{name} rates {score}/100 for this matchup."]}


def test_render_team_sheet_shows_pool_and_xi_with_reasoning():
    pool = [
        _explained("p1", "Star Batter", 40.0, "batter",
                   reasoning=["Star Batter rates 40.0/100.", "A proven track record backs this up."]),
        _explained("p2", "Keeper Option", 5.0, "batter", is_keeper=True,
                   reasoning=["Keeper Option rates 5.0/100 — a wicket-keeper option."]),
        _explained("p3", "Bench Bowler", 12.0, "bowler",
                   reasoning=["Bench Bowler rates 12.0/100."]),
    ]
    # XI includes p1 and p2 (keeper forced in by constraints) but not p3 --
    # exercises the "XI is not simply the pool's top N" case directly.
    xi = [
        _explained("p1", "Star Batter", 40.0, "batter",
                   reasoning=["Star Batter rates 40.0/100.",
                              "Picked for the opening slot ahead of Bench Bowler (score 12.0)."]),
        _explained("p2", "Keeper Option", 5.0, "batter", is_keeper=True,
                   reasoning=["Keeper Option rates 5.0/100 — a wicket-keeper option.",
                              "No close alternative in the pool for the keeper slot."]),
    ]
    constraints = {"min_batting_capable": 1, "min_bowling_capable": 1, "min_keepers": 1, "min_openers": 1}

    text = render_team_sheet("India", "Australia", None, xi, pool,
                              {"trained_at": "2026-01-01", "n_rows_total": 100,
                               "format": "T20", "gender": "female"},
                              constraints)

    # The roster header + both role-pool sections present (2 batters incl.
    # the keeper, 1 bowler -- no all-rounders in this fixture, so that
    # section is omitted entirely rather than shown empty), before the XI.
    assert "ROSTER — 3 PLAYERS ACROSS 3 ROLE POOLS" in text
    assert "BATTING POOL (2)" in text
    assert "BOWLING POOL (1)" in text
    assert "ALL-ROUNDER POOL" not in text
    assert "PLAYING XI" in text
    assert text.index("BATTING POOL") < text.index("PLAYING XI")

    # Every pool member appears with her own reasoning, including the one
    # who didn't make the XI.
    assert "Bench Bowler" in text
    assert "Bench Bowler rates 12.0/100." in text

    # Pool members who *did* make the XI are tagged, the one who didn't isn't.
    lines = text.splitlines()
    star_line = next(l for l in lines if "Star Batter" in l and "rates" not in l)
    bench_line = next(l for l in lines if "Bench Bowler" in l and "rates" not in l)
    assert "[XI]" in star_line
    assert "[XI]" not in bench_line

    # The XI section itself carries its own (different, slot-aware) reasoning.
    assert "Picked for the opening slot ahead of Bench Bowler" in text
    assert "No close alternative in the pool for the keeper slot" in text


def test_render_xi_analysis_shows_violations_and_optimal_comparison():
    xi = [
        _explained("bat1", "Bat One", 90.0, "batter"),
        _explained("bat2", "Bat Two", 80.0, "batter"),
    ]
    analysis = {
        "missing_player_ids": ["typo-id"],
        "total_score": 170.0, "average_score": 85.0,
        "counts": {"size": 2, "batting_capable": 2, "bowling_capable": 0, "keepers": 0, "openers": 0},
        "requirements": {"xi_size": 2, "min_batting_capable": 1, "min_bowling_capable": 1,
                          "min_keepers": 0, "min_openers": 0},
        "violations": ["only 0 bowling-capable, need 1"],
        "comparison_to_optimal": {
            "optimal_total_score": 175.0, "score_gap": 5.0,
            "in_optimal_not_chosen": [{"player_id": "bowl1", "name": "Bowl One", "score": 85.0}],
            "in_chosen_not_optimal": [{"player_id": "bat2", "name": "Bat Two", "score": 80.0}],
        },
    }

    text = render_xi_analysis("India", "Australia", None, xi, analysis)
    assert "CUSTOM XI ANALYSIS" in text
    assert "typo-id" in text  # missing-id warning surfaced, not silently dropped
    assert "only 0 bowling-capable, need 1" in text
    assert "5.0 points below the AI's own optimal XI" in text
    assert "Bowl One" in text  # what the coach's pick is missing, named explicitly
    assert "Bat Two" in text  # in this XI but not the optimal one


def test_render_xi_analysis_no_violations_reads_as_meeting_constraints():
    xi = [_explained("bat1", "Bat One", 90.0, "batter")]
    analysis = {
        "missing_player_ids": [],
        "total_score": 90.0, "average_score": 90.0,
        "counts": {"size": 1, "batting_capable": 1, "bowling_capable": 0, "keepers": 0, "openers": 0},
        "requirements": {"xi_size": 1, "min_batting_capable": 1, "min_bowling_capable": 0,
                          "min_keepers": 0, "min_openers": 0},
        "violations": [],
        "comparison_to_optimal": {
            "optimal_total_score": 90.0, "score_gap": 0.0,
            "in_optimal_not_chosen": [], "in_chosen_not_optimal": [],
        },
    }

    text = render_xi_analysis("India", "Australia", None, xi, analysis)
    assert "Meets every selection constraint" in text
    assert "Matches or beats the AI's own optimal XI" in text

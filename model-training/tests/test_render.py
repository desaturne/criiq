from __future__ import annotations

from criiq_models.recommend.render import render_team_sheet


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

    # Both section headers present, in the right order (shortlist before XI).
    assert "TOP 3 RECOMMENDED PLAYERS" in text
    assert "PLAYING XI" in text
    assert text.index("TOP 3 RECOMMENDED PLAYERS") < text.index("PLAYING XI")

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

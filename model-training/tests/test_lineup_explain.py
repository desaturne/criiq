from __future__ import annotations

import numpy as np

from criiq_models.simulate.lineup_explain import explain_batting_order, explain_bowling_rotation
from criiq_models.simulate.outcomes import BatterProfile, BowlerProfile, PHASES, PlayerAdjustedOutcomeModel

BATTERS = [f"b{i}" for i in range(11)]
BOWLERS5 = [f"w{i}" for i in range(5)]

_RATES = {"0": 0.35, "1": 0.3, "2": 0.08, "3": 0.02, "4": 0.12, "6": 0.05,
          "wicket": 0.03, "wide": 0.03, "noball": 0.01, "bye": 0.01}


def _model():
    return PlayerAdjustedOutcomeModel({phase: dict(_RATES) for phase in PHASES},
                                       league_sr=120.0, league_economy=7.5)


def _batter_profiles(strike_rates: dict) -> dict:
    return {pid: BatterProfile(strike_rate=sr) for pid, sr in strike_rates.items()}


def _bowler_profiles(ids, phase_ranks: dict | None = None, phase_rank_sizes: dict | None = None) -> dict:
    phase_ranks = phase_ranks or {}
    phase_rank_sizes = phase_rank_sizes or {}
    return {pid: BowlerProfile(economy=7.5, wickets_per_match=1.0,
                                phase_rank=phase_ranks.get(pid, {}),
                                phase_rank_size=phase_rank_sizes.get(pid, {})) for pid in ids}


def test_explain_batting_order_reports_slots_matching_the_order():
    strike_rates = {b: 100.0 + i * 5 for i, b in enumerate(BATTERS)}
    batter_profiles = _batter_profiles(strike_rates)
    bowler_profiles = _bowler_profiles(BOWLERS5)

    order = list(reversed(BATTERS))
    result = explain_batting_order(order, [BATTERS], BOWLERS5, _model(), batter_profiles, bowler_profiles,
                                    target=None, chosen_metric=123.0, metric_name="expected_score",
                                    rng_seed=1, n_reps=4)

    assert [s["player_id"] for s in result["slots"]] == order
    for slot in result["slots"]:
        pid = slot["player_id"]
        assert slot["strike_rate"] == round(strike_rates[pid], 1)
    assert result["metric_name"] == "expected_score"
    assert result["chosen_metric"] == 123.0
    assert result["improvement_over_baseline"] == round(123.0 - result["baseline_metric"], 4)


def test_explain_batting_order_never_swaps_across_group_boundaries():
    openers = BATTERS[:2]
    top_middle = BATTERS[2:7]
    tail = BATTERS[7:]
    batter_profiles = _batter_profiles({b: 120.0 for b in BATTERS})
    bowler_profiles = _bowler_profiles(BOWLERS5)

    result = explain_batting_order(BATTERS, [openers, top_middle, tail], BOWLERS5, _model(),
                                    batter_profiles, bowler_profiles, target=None, chosen_metric=100.0,
                                    metric_name="expected_score", rng_seed=2, n_reps=4)

    bounds = [(0, 1), (2, 6), (7, 10)]
    for swap in result["adjacent_swaps"]:
        i, j = swap["positions"][0] - 1, swap["positions"][1] - 1
        assert any(lo <= i <= hi and lo <= j <= hi for lo, hi in bounds)
    assert len(result["adjacent_swaps"]) == 1 + 4 + 3


def test_explain_batting_order_most_costly_swap_is_the_minimum_delta():
    batter_profiles = _batter_profiles({b: 120.0 for b in BATTERS})
    bowler_profiles = _bowler_profiles(BOWLERS5)

    result = explain_batting_order(BATTERS, [BATTERS], BOWLERS5, _model(), batter_profiles, bowler_profiles,
                                    target=None, chosen_metric=100.0, metric_name="expected_score",
                                    rng_seed=3, n_reps=4)

    deltas = [s["delta"] for s in result["adjacent_swaps"]]
    assert result["most_costly_adjacent_swap"]["delta"] == min(deltas)


def test_explain_batting_order_with_target_uses_chasing_strike_rate():
    batter_profiles = {
        "b0": BatterProfile(strike_rate=100.0, chasing_strike_rate=150.0),
        "b1": BatterProfile(strike_rate=200.0, chasing_strike_rate=90.0),
    }
    bowler_profiles = _bowler_profiles(BOWLERS5)

    result = explain_batting_order(["b0", "b1"], [["b0", "b1"]], BOWLERS5, _model(), batter_profiles,
                                    bowler_profiles, target=140, chosen_metric=0.5,
                                    metric_name="win_probability", rng_seed=4, n_reps=4)

    slot_map = {s["player_id"]: s["strike_rate"] for s in result["slots"]}
    assert slot_map["b0"] == 150.0
    assert slot_map["b1"] == 90.0


def test_explain_batting_order_contingency_never_promotes_an_opener_or_the_tail():
    openers = BATTERS[:2]
    top_middle = BATTERS[2:7]
    tail = BATTERS[7:]
    # openers highest, tail lowest -- a global min/max would wrongly pick them.
    strike_rates = {**{b: 200.0 for b in openers}, **{b: 120.0 for b in top_middle}, **{b: 60.0 for b in tail}}
    batter_profiles = _batter_profiles(strike_rates)
    bowler_profiles = _bowler_profiles(BOWLERS5)

    result = explain_batting_order(BATTERS, [openers, top_middle, tail], BOWLERS5, _model(),
                                    batter_profiles, bowler_profiles, target=None, chosen_metric=100.0,
                                    metric_name="expected_score", rng_seed=6, n_reps=4)

    contingency = result["contingency"]
    assert contingency["early_collapse"]["player_id"] in top_middle
    assert contingency["quick_chase"]["player_id"] in top_middle


def test_explain_batting_order_contingency_picks_lowest_and_highest_strike_rate():
    batter_profiles = {
        "b0": BatterProfile(strike_rate=150.0, chasing_strike_rate=100.0),
        "b1": BatterProfile(strike_rate=90.0, chasing_strike_rate=180.0),
        "b2": BatterProfile(strike_rate=120.0, chasing_strike_rate=130.0),
    }
    bowler_profiles = _bowler_profiles(BOWLERS5)

    result = explain_batting_order(["b0", "b1", "b2"], [["b0", "b1", "b2"]], BOWLERS5, _model(),
                                    batter_profiles, bowler_profiles, target=None, chosen_metric=100.0,
                                    metric_name="expected_score", rng_seed=7, n_reps=4)

    contingency = result["contingency"]
    # b1 has the lowest base strike rate -- the anchor to send in after early wickets
    assert contingency["early_collapse"]["player_id"] == "b1"
    # b1 also has the highest chasing strike rate -- the accelerant for a quick chase
    assert contingency["quick_chase"]["player_id"] == "b1"
    assert contingency["quick_chase"]["chasing_strike_rate"] == 180.0


def test_explain_bowling_rotation_reports_phase_overs_and_rank():
    rotation = (["w0", "w1", "w2", "w3", "w4"] * 4)[:20]
    overs_per_bowler = {b: rotation.count(b) for b in dict.fromkeys(rotation)}
    phase_ranks = {"w0": {"powerplay": 1, "middle": 2, "death": 3}}
    phase_rank_sizes = {"w0": {"powerplay": 12, "middle": 15, "death": 10}}
    batter_profiles = _batter_profiles({b: 120.0 for b in BATTERS})
    bowler_profiles = _bowler_profiles(BOWLERS5, phase_ranks, phase_rank_sizes)

    result = explain_bowling_rotation(rotation, BATTERS, _model(), batter_profiles, bowler_profiles,
                                       overs_per_bowler, expected_runs_conceded=140.0, rng_seed=5, n_reps=4)

    assert result["expected_runs_conceded"] == 140.0
    w0 = next(b for b in result["bowlers"] if b["player_id"] == "w0")
    assert w0["overs"] == overs_per_bowler["w0"]
    assert set(w0["phase_overs"]) <= {"powerplay", "middle", "death"}
    assert w0["phase_rank"] == {p: {"rank": phase_ranks["w0"][p], "size": phase_rank_sizes["w0"][p]}
                                 for p in w0["phase_overs"]}
    assert isinstance(result["baseline_runs_conceded"], float)
    assert result["improvement_over_baseline"] == round(
        result["baseline_runs_conceded"] - 140.0, 2)

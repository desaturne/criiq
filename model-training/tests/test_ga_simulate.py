"""Legality + basic-convergence checks for the two GA optimizers
(`simulate/ga_bowling.py`, `simulate/ga_batting.py`) -- every individual must
always be a rules-legal rotation/order after repair, fitness should not get
worse from the first generation to the last on a fixed seed, and the
role-structure preferences (locked batting bands, primary-bowler quota bias)
must actually hold.
"""
from __future__ import annotations

import pytest

import numpy as np

from criiq_models.simulate.engine import MAX_OVERS, MAX_OVERS_PER_BOWLER
from criiq_models.simulate.ga_batting import optimize_batting_order
from criiq_models.simulate.ga_bowling import _quotas, _repair, optimize_bowling_rotation
from criiq_models.simulate.outcomes import BatterProfile, BowlerProfile, PHASES, PlayerAdjustedOutcomeModel

BATTERS = [f"b{i}" for i in range(11)]
BOWLERS5 = [f"w{i}" for i in range(5)]

_RATES = {"0": 0.35, "1": 0.3, "2": 0.08, "3": 0.02, "4": 0.12, "6": 0.05,
          "wicket": 0.03, "wide": 0.03, "noball": 0.01, "bye": 0.01}


def _model():
    return PlayerAdjustedOutcomeModel({phase: dict(_RATES) for phase in PHASES},
                                       league_sr=120.0, league_economy=7.5)


def _profiles(ids):
    return ({pid: BatterProfile(strike_rate=120.0) for pid in ids},
            {pid: BowlerProfile(economy=7.5, wickets_per_match=1.0) for pid in ids})


def _assert_legal_rotation(rotation):
    assert len(rotation) == MAX_OVERS
    counts = {}
    for i, bowler in enumerate(rotation):
        counts[bowler] = counts.get(bowler, 0) + 1
        if i > 0:
            assert rotation[i] != rotation[i - 1]
    assert all(c <= MAX_OVERS_PER_BOWLER for c in counts.values())


def test_bowling_rotation_ga_always_returns_a_legal_rotation():
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    result = optimize_bowling_rotation(BOWLERS5, BATTERS, _model(), batter_profiles, bowler_profiles,
                                        pop_size=6, generations=3, n_reps=1, rng_seed=42)
    _assert_legal_rotation(result["rotation"])
    assert len(result["fitness_history"]) == 3
    assert result["expected_runs_conceded"] >= 0


def test_bowling_rotation_ga_fitness_history_never_regresses():
    """`fitness_history` logs the running best-known fitness (elitism +
    verify-before-accept guard it against Monte Carlo noise) -- it must be
    monotonically non-decreasing by construction, not just "usually" improve.
    """
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    result = optimize_bowling_rotation(BOWLERS5, BATTERS, _model(), batter_profiles, bowler_profiles,
                                        pop_size=6, generations=8, n_reps=2, rng_seed=7)
    history = result["fitness_history"]
    assert all(b >= a for a, b in zip(history, history[1:]))


def test_bowling_rotation_ga_raises_for_too_small_a_pool():
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5[:4])
    with pytest.raises(ValueError):
        optimize_bowling_rotation(BOWLERS5[:4], BATTERS, _model(), batter_profiles, bowler_profiles,
                                   pop_size=4, generations=2, n_reps=1, rng_seed=42)


def test_repair_fixes_a_badly_skewed_post_crossover_rotation_in_a_razor_tight_pool():
    """Real bug, caught live: with exactly 5 bowlers (zero slack -- 5 x 4 =
    20, no room to spare), a crossover child can badly skew per-bowler over-
    counts (here: 10 overs each for just 2 of the 5 bowlers) before repair
    ever runs. The old left-to-right patch could paint itself into a corner
    on inputs like this even though the *pool as a whole* can legally cover
    20 overs -- `_repair` must always succeed here, not raise.
    """
    skewed = ["w0"] * 10 + ["w1"] * 10
    rng = np.random.default_rng(3)
    fixed = _repair(skewed, BOWLERS5, rng)
    _assert_legal_rotation(fixed)


def test_repair_prefers_primary_bowlers_when_reassigning_a_shortfall():
    skewed = ["w0"] * 10 + ["w1"] * 10
    rng = np.random.default_rng(3)
    fixed = _repair(skewed, BOWLERS5, rng, primary_bowlers=["w2", "w3", "w4"])
    _assert_legal_rotation(fixed)
    counts = {b: fixed.count(b) for b in set(fixed)}
    # w0/w1 already contributed their capped 4 each; the remaining 12 overs'
    # worth of shortfall must have gone to the (non-skewed) primary bowlers.
    assert sum(counts.get(b, 0) for b in ("w2", "w3", "w4")) == MAX_OVERS - 2 * MAX_OVERS_PER_BOWLER


def test_bowling_rotation_ga_gives_primary_bowlers_the_full_quota_by_default():
    """With exactly 5 recognized specialists in a 5-bowler pool, the default
    (`primary_bowlers` given) rotation should still be legal, and -- since
    there's no slack pool member to dilute the quota with -- every over goes
    to one of the 5 primaries, each getting exactly 4.
    """
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    result = optimize_bowling_rotation(BOWLERS5, BATTERS, _model(), batter_profiles, bowler_profiles,
                                        primary_bowlers=BOWLERS5, pop_size=6, generations=3,
                                        n_reps=1, rng_seed=42)
    _assert_legal_rotation(result["rotation"])
    assert result["overs_per_bowler"] == {b: MAX_OVERS_PER_BOWLER for b in BOWLERS5}


def test_bowling_rotation_ga_lets_primary_bowlers_absorb_a_shortfall():
    """Only 4 recognized specialists (16 overs of capacity) in a 6-bowler
    pool -- the *default* (pre-evolution) quota construction gives the
    primaries their full quota and puts only the shortfall (the remaining 4
    overs) on the other 2 pool members, matching a real captain's forced
    situation. Checked directly against `_quotas` (the initial-population/
    repair-fallback building block) -- not the fully-evolved GA result,
    since ordinary mutation is deliberately free to drift away from this
    default over generations if the fitness landscape rewards it (see
    "sometimes others can be introduced" in this module's docstring).
    """
    pool = BOWLERS5 + ["w5"]
    primary = BOWLERS5[:4]
    quotas = _quotas(pool, np.random.default_rng(1), primary_bowlers=primary)
    for b in primary:
        assert quotas[b] == MAX_OVERS_PER_BOWLER
    shortfall_overs = sum(n for b, n in quotas.items() if b not in primary)
    assert shortfall_overs == MAX_OVERS - len(primary) * MAX_OVERS_PER_BOWLER
    assert sum(quotas.values()) == MAX_OVERS


def test_bowling_rotation_ga_with_shortfall_still_produces_a_legal_rotation():
    """The full evolved GA run over a primary-shortfall pool must still
    always produce a legal rotation (the actual, unconditional guarantee),
    even though the exact quota split may drift from the default via
    mutation.
    """
    pool = BOWLERS5 + ["w5"]
    primary = BOWLERS5[:4]
    batter_profiles, bowler_profiles = _profiles(BATTERS + pool)
    result = optimize_bowling_rotation(pool, BATTERS, _model(), batter_profiles, bowler_profiles,
                                        primary_bowlers=primary, pop_size=6, generations=3,
                                        n_reps=1, rng_seed=42)
    _assert_legal_rotation(result["rotation"])


def test_batting_order_ga_returns_a_permutation_of_the_input_players():
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    result = optimize_batting_order([BATTERS], BOWLERS5, _model(), batter_profiles, bowler_profiles,
                                     pop_size=6, generations=3, n_reps=1, rng_seed=42)
    assert sorted(result["batting_order"]) == sorted(BATTERS)
    assert len(result["fitness_history"]) == 3
    assert "expected_score" in result


def test_batting_order_ga_with_target_reports_win_probability():
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    result = optimize_batting_order([BATTERS], BOWLERS5, _model(), batter_profiles, bowler_profiles,
                                     target=50, pop_size=6, generations=3, n_reps=1, rng_seed=42)
    assert "win_probability" in result
    assert 0.0 <= result["win_probability"] <= 1.0


def test_batting_order_ga_fitness_history_never_regresses():
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    result = optimize_batting_order([BATTERS], BOWLERS5, _model(), batter_profiles, bowler_profiles,
                                     pop_size=6, generations=8, n_reps=2, rng_seed=7)
    history = result["fitness_history"]
    assert all(b >= a for a, b in zip(history, history[1:]))


def test_batting_order_ga_respects_group_bands_but_permutes_within_them():
    """The two openers can interchange (1 vs 2), the top/middle band can
    reorder among itself, and the tail can reorder among itself -- but no
    player ever crosses a band boundary.
    """
    openers = [BATTERS[0], BATTERS[1]]
    top_middle = BATTERS[2:7]
    tail = BATTERS[7:]
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    result = optimize_batting_order([openers, top_middle, tail], BOWLERS5, _model(), batter_profiles,
                                     bowler_profiles, pop_size=6, generations=3, n_reps=1, rng_seed=42)
    order = result["batting_order"]
    assert set(order[:2]) == set(openers)
    assert set(order[2:7]) == set(top_middle)
    assert set(order[7:]) == set(tail)
    assert result["batting_groups"][0] and set(result["batting_groups"][0]) == set(openers)


def test_batting_order_ga_rejects_empty_or_overlapping_groups():
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    with pytest.raises(ValueError):
        optimize_batting_order([], BOWLERS5, _model(), batter_profiles, bowler_profiles,
                                pop_size=6, generations=2, n_reps=1, rng_seed=1)
    with pytest.raises(ValueError):
        optimize_batting_order([BATTERS[:3], BATTERS[2:5]], BOWLERS5, _model(), batter_profiles,
                                bowler_profiles, pop_size=6, generations=2, n_reps=1, rng_seed=1)

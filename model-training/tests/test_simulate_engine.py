"""Rules-compliance tests for the ball-by-ball T20 engine (`simulate/engine.py`),
checked directly against rulebook-cricket.md's cited clauses -- synthetic
outcome models/profiles throughout, no DB dependency (mirrors this test
suite's existing convention of a tiny fixture DB or none at all).
"""
from __future__ import annotations

import numpy as np
import pytest

from criiq_models.simulate.engine import (
    MAX_OVERS, MAX_OVERS_PER_BOWLER, MAX_SUPER_OVER_ROUNDS, SUPER_OVER_MAX_WICKETS, TOTAL_LEGAL_BALLS,
    select_bowler, simulate_ball, simulate_innings, simulate_match, simulate_super_over, MatchState,
)
from criiq_models.simulate.outcomes import BatterProfile, BowlerProfile, PHASES, PlayerAdjustedOutcomeModel

BATTERS = [f"b{i}" for i in range(11)]
BOWLERS5 = [f"w{i}" for i in range(5)]


def _profiles(ids):
    return {pid: BatterProfile(strike_rate=120.0) for pid in ids}, {pid: BowlerProfile(economy=7.5, wickets_per_match=1.0) for pid in ids}


def _model(rates: dict):
    baseline = {phase: dict(rates) for phase in PHASES}
    return PlayerAdjustedOutcomeModel(baseline, league_sr=120.0, league_economy=7.5)


NO_EXTRAS_NO_WICKET = {"0": 0.4, "1": 0.3, "2": 0.1, "3": 0.02, "4": 0.13, "6": 0.05,
                        "wicket": 0.0, "wide": 0.0, "noball": 0.0, "bye": 0.0}
ALL_WIDE = {"0": 0.0, "1": 0.0, "2": 0.0, "3": 0.0, "4": 0.0, "6": 0.0,
            "wicket": 0.0, "wide": 1.0, "noball": 0.0, "bye": 0.0}
ALL_NOBALL = {**ALL_WIDE, "wide": 0.0, "noball": 1.0}
ALL_BYE = {**ALL_WIDE, "wide": 0.0, "bye": 1.0}
ALWAYS_WICKET = {**ALL_WIDE, "wide": 0.0, "wicket": 1.0}


def test_innings_bowls_exactly_120_legal_balls_with_no_extras_or_wickets():
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    model = _model(NO_EXTRAS_NO_WICKET)
    state, log = simulate_innings(BATTERS, BOWLERS5, model, batter_profiles, bowler_profiles,
                                   rng=np.random.default_rng(1))
    assert state.balls_bowled == TOTAL_LEGAL_BALLS
    assert len(log) == TOTAL_LEGAL_BALLS
    assert log["is_legal"].all()
    assert state.over == MAX_OVERS


def test_no_bowler_exceeds_max_overs_and_no_consecutive_overs():
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    model = _model(NO_EXTRAS_NO_WICKET)
    state, log = simulate_innings(BATTERS, BOWLERS5, model, batter_profiles, bowler_profiles,
                                   rng=np.random.default_rng(2))
    for bowler, balls in state.bowler_balls.items():
        assert balls <= MAX_OVERS_PER_BOWLER * 6

    bowler_per_over = log.groupby("over")["bowler"].first().tolist()
    for i in range(1, len(bowler_per_over)):
        assert bowler_per_over[i] != bowler_per_over[i - 1], "bowler bowled two consecutive overs (Law 17.6)"


def test_bowler_selection_prefers_a_real_phase_specialist_over_least_used():
    """A captain's proven death-overs bowler should actually bowl the death
    overs (and the powerplay specialist the powerplay), not whichever
    bowler simply has bowled fewest overs so far -- the realistic default
    scheduling `select_bowler`'s docstring describes. Needs real squad depth
    (6+ bowling options, one more than the bare minimum) for this preference
    to be safe to apply at all -- see `select_bowler`'s `min_required` guard.
    """
    bowlers6 = BOWLERS5 + ["w5"]
    batter_profiles, bowler_profiles = _profiles(BATTERS + bowlers6)
    # Only rank each specialist in their own phase -- otherwise a bowler
    # ranked (even mediocrely) in every phase would out-prioritize the
    # "no data" bowlers everywhere and exhaust their 4-over cap in the
    # middle overs before ever reaching their actual specialty phase.
    bowler_profiles["w0"].phase_rank = {"powerplay": 1}
    bowler_profiles["w1"].phase_rank = {"death": 1}
    model = _model(NO_EXTRAS_NO_WICKET)
    state, log = simulate_innings(BATTERS, bowlers6, model, batter_profiles, bowler_profiles,
                                   rng=np.random.default_rng(11))

    powerplay_bowlers = log[log["over"] <= 5].groupby("over")["bowler"].first()
    death_bowlers = log[log["over"] >= 15].groupby("over")["bowler"].first()
    assert (powerplay_bowlers == "w0").sum() >= 2
    assert (death_bowlers == "w1").sum() >= 2
    for bowler, balls in state.bowler_balls.items():
        assert balls <= MAX_OVERS_PER_BOWLER * 6
    bowler_per_over = log.groupby("over")["bowler"].first().tolist()
    for i in range(1, len(bowler_per_over)):
        assert bowler_per_over[i] != bowler_per_over[i - 1]


def test_bowler_selection_ignores_phase_tiering_at_exact_minimum_pool_size():
    """Exactly 5 bowlers (the bare minimum for a 20-over innings at 4 overs
    each) has zero slack -- phase-tiering must not apply here at all (see
    `select_bowler`'s `min_required` guard), since holding any bowler back
    from a phase they're needed in risks a legal deadlock.
    """
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    bowler_profiles["w0"].phase_rank = {"powerplay": 1}
    bowler_profiles["w1"].phase_rank = {"death": 1}
    model = _model(NO_EXTRAS_NO_WICKET)
    # Must not raise -- with no slack, the engine falls back to the
    # provably-safe least-used-first schedule regardless of phase data.
    state, log = simulate_innings(BATTERS, BOWLERS5, model, batter_profiles, bowler_profiles,
                                   rng=np.random.default_rng(11))
    assert state.balls_bowled == TOTAL_LEGAL_BALLS
    for bowler, balls in state.bowler_balls.items():
        assert balls <= MAX_OVERS_PER_BOWLER * 6


def test_bowler_selection_without_phase_data_falls_back_to_least_used():
    """No `bowler_profiles` phase-rank data anywhere -> identical to the
    pre-existing least-used-first behaviour (no regression).
    """
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    balls = {"w0": 6, "w1": 0, "w2": 12}
    chosen = select_bowler(BOWLERS5, balls, last_over_bowler="w1", over_idx=3,
                            bowler_profiles=bowler_profiles)
    assert chosen not in ("w1",)
    assert balls.get(chosen, 0) == min(balls.get(b, 0) for b in BOWLERS5 if b != "w1")


def test_bowling_pool_too_small_raises_clear_error():
    """4 bowlers x 4 overs max = 16 overs of capacity, short of the 20 an
    innings needs -- must raise rather than silently violate Law 17.6/ICC PC
    cl. 13.9.1.
    """
    small_pool = BOWLERS5[:4]
    batter_profiles, bowler_profiles = _profiles(BATTERS + small_pool)
    model = _model(NO_EXTRAS_NO_WICKET)
    with pytest.raises(ValueError):
        simulate_innings(BATTERS, small_pool, model, batter_profiles, bowler_profiles,
                          rng=np.random.default_rng(3))


def test_explicit_illegal_rotation_raises():
    balls = {"w0": 0, "w1": 0}
    with pytest.raises(ValueError):
        select_bowler(["w0", "w1"], balls, last_over_bowler="w0", rotation=["w0"], over_idx=0)


def test_wide_is_not_legal_and_does_not_advance_the_over():
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    model = _model(ALL_WIDE)
    state = MatchState(innings=1, batting_order=BATTERS)
    rec = simulate_ball(state, "w0", model, batter_profiles, bowler_profiles, np.random.default_rng(4))
    assert rec["outcome"] == "wide"
    assert rec["is_legal"] is False
    assert state.balls_bowled == 0
    assert state.ball_in_over == 0
    assert state.score == 1  # 1-run wide penalty
    assert state.bowler_runs_conceded["w0"] == 1  # debited to the bowler (rulebook sec 4.1)


def test_noball_sets_free_hit_and_is_not_legal():
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    model = _model(ALL_NOBALL)
    state = MatchState(innings=1, batting_order=BATTERS)
    rec = simulate_ball(state, "w0", model, batter_profiles, bowler_profiles, np.random.default_rng(5))
    assert rec["outcome"] == "noball"
    assert rec["is_legal"] is False
    assert state.balls_bowled == 0
    assert state.free_hit is True
    assert state.score == 1


def test_bye_is_legal_but_not_credited_to_batter_or_debited_to_bowler():
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    model = _model(ALL_BYE)
    state = MatchState(innings=1, batting_order=BATTERS)
    rec = simulate_ball(state, "w0", model, batter_profiles, bowler_profiles, np.random.default_rng(6))
    assert rec["outcome"] == "bye"
    assert rec["is_legal"] is True
    assert state.balls_bowled == 1
    assert state.score == 1
    assert batter_profiles  # sanity: profiles untouched
    assert "b0" not in state.batter_runs  # bye run not credited to the striker
    assert "w0" not in state.bowler_runs_conceded  # bye not debited to the bowler (rulebook sec 4.3/6)


def test_free_hit_suppresses_wicket_probability():
    model = _model(ALWAYS_WICKET)
    dist = model.distribution("middle", BatterProfile(120.0), BowlerProfile(7.5, 1.0), free_hit=True)
    assert dist["wicket"] == 0.0


def test_wicket_brings_in_next_batter_and_all_out_ends_innings_early():
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    model = _model(ALWAYS_WICKET)
    state, log = simulate_innings(BATTERS, BOWLERS5, model, batter_profiles, bowler_profiles,
                                   rng=np.random.default_rng(7))
    assert state.wickets == 10
    assert state.all_out is True
    assert state.over < MAX_OVERS  # ended early, well before 120 legal balls


def test_forced_dismissal_overrides_sampled_outcome():
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    model = _model(NO_EXTRAS_NO_WICKET)  # would never naturally produce a wicket
    forced = {"player_id": "b0", "over": 0, "ball": 1}
    state, log = simulate_innings(BATTERS, BOWLERS5, model, batter_profiles, bowler_profiles,
                                   forced_dismissal=forced, rng=np.random.default_rng(8))
    first_ball = log.iloc[0]
    assert bool(first_ball["is_wicket"]) is True
    assert first_ball["dismissed"] == "b0"


def test_chase_ends_immediately_on_reaching_target():
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    model = _model(NO_EXTRAS_NO_WICKET)
    state, log = simulate_innings(BATTERS, BOWLERS5, model, batter_profiles, bowler_profiles,
                                   target=5, rng=np.random.default_rng(9))
    assert state.score >= 5
    assert state.balls_bowled < TOTAL_LEGAL_BALLS


class _StubWinProb:
    """A fixed-probability stand-in for `WinProbLookup` -- these tests exercise
    match/Super-Over *rules mechanics*, not the win-probability model itself,
    so no real persisted model file is needed.
    """
    def predict_one(self, **kwargs):
        return 0.5


def test_super_over_is_capped_at_one_over():
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    model = _model(NO_EXTRAS_NO_WICKET)
    team_a = {"name": "A", "batting_order": BATTERS, "bowling_pool": BOWLERS5}
    team_b = {"name": "B", "batting_order": list(reversed(BATTERS)), "bowling_pool": BOWLERS5}
    so = simulate_super_over(team_a, team_b, model, batter_profiles, bowler_profiles, np.random.default_rng(1))
    assert (so["bat_first_log"]["balls_bowled"] <= 6).all()
    assert (so["bowl_first_log"]["balls_bowled"] <= 6).all()


def test_super_over_ends_early_on_two_wickets_not_all_out():
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    model = _model(ALWAYS_WICKET)
    team_a = {"name": "A", "batting_order": BATTERS, "bowling_pool": BOWLERS5}
    team_b = {"name": "B", "batting_order": list(reversed(BATTERS)), "bowling_pool": BOWLERS5}
    so = simulate_super_over(team_a, team_b, model, batter_profiles, bowler_profiles, np.random.default_rng(2))
    assert so["bat_first_wickets"] == SUPER_OVER_MAX_WICKETS
    assert so["bowl_first_wickets"] == SUPER_OVER_MAX_WICKETS


def test_a_tied_run_chase_is_resolved_by_super_over_not_reported_as_a_bare_tie():
    """T20Is have no draw (rulebook-cricket.md sec 7.1): with a model where
    every ball scores exactly 1 run and both sides face the same 120 legal
    balls, the second innings always finishes exactly one run short (target -
    1) -- a guaranteed tie -- which must trigger at least one Super Over
    rather than reporting `winner == "Tie"` outright.
    """
    batter_profiles, bowler_profiles = _profiles(BATTERS + BOWLERS5)
    always_one = {"0": 0.0, "1": 1.0, "2": 0.0, "3": 0.0, "4": 0.0, "6": 0.0,
                  "wicket": 0.0, "wide": 0.0, "noball": 0.0, "bye": 0.0}
    model = _model(always_one)
    team1 = {"name": "Team1", "batting_order": BATTERS, "bowling_pool": BOWLERS5}
    team2 = {"name": "Team2", "batting_order": list(reversed(BATTERS)), "bowling_pool": BOWLERS5}
    reps = simulate_match(team1, team2, "team1", model, batter_profiles, bowler_profiles,
                           _StubWinProb(), n_reps=1, rng_seed=10)
    rep = reps[0]
    assert rep["second_innings_score"] == rep["target"] - 1
    assert len(rep["super_over_rounds"]) >= 1
    # deterministic always-1-run model -> every Super Over ties too (6 balls
    # each side, target = 7, unreachable in 6 balls) -> exhausts the bounded
    # retry loop and correctly falls back to "Tie", never hangs.
    assert len(rep["super_over_rounds"]) == MAX_SUPER_OVER_ROUNDS
    assert rep["winner"] == "Tie"
    assert all(so["winner"] == "Tie" for so in rep["super_over_rounds"])

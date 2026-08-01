"""ball-by-ball T20 match engine.

follows rulebook-cricket.md: 20 overs, wides/no-balls replayed and not
counted, bowler capped at 4 overs with no consecutive overs, free hit after
a no-ball, byes not credited to the bowler. doesn't model DLS or
rain-shortened innings, and a wicket never coincides with a wide/no-ball
(see outcomes.py).

default bowler rotation picks whoever's proven best for the current phase
(powerplay/middle/death) by real per-phase economy rank, falling back to
fewest overs bowled so far when there's no phase data.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .outcomes import _phase

MAX_OVERS = 20
MAX_OVERS_PER_BOWLER = 4
BALLS_PER_OVER = 6
TOTAL_LEGAL_BALLS = MAX_OVERS * BALLS_PER_OVER

# super over: one over per side, innings ends early on 2 wickets.
# MAX_SUPER_OVER_ROUNDS bounds the repeat-until-decided real rule so we
# don't risk hanging on a pathological outcome model.
SUPER_OVER_OVERS = 1
SUPER_OVER_MAX_WICKETS = 2
MAX_SUPER_OVER_ROUNDS = 10


@dataclass
class MatchState:
    innings: int
    batting_order: list
    target: int | None = None
    max_wickets: int | None = None
    striker_idx: int = 0
    non_striker_idx: int = 1
    next_batter_idx: int = 2
    score: int = 0
    wickets: int = 0
    over: int = 0
    ball_in_over: int = 0
    balls_bowled: int = 0
    free_hit: bool = False
    all_out: bool = False
    out: set = field(default_factory=set)
    bowler_balls: dict = field(default_factory=dict)
    bowler_runs_conceded: dict = field(default_factory=dict)
    bowler_wickets: dict = field(default_factory=dict)
    batter_runs: dict = field(default_factory=dict)
    batter_balls: dict = field(default_factory=dict)
    last_over_bowler: str | None = None

    @property
    def striker(self) -> str:
        return self.batting_order[self.striker_idx]

    @property
    def balls_remaining(self) -> int:
        return TOTAL_LEGAL_BALLS - self.balls_bowled

    def chase_won(self) -> bool:
        return self.target is not None and self.score >= self.target

    def wickets_exhausted(self) -> bool:
        return self.max_wickets is not None and self.wickets >= self.max_wickets

    def is_over(self) -> bool:
        return self.all_out or self.chase_won() or self.wickets_exhausted()


def select_bowler(bowler_pool: list, bowler_balls: dict, last_over_bowler: str | None,
                   rotation: list | None = None, over_idx: int | None = None,
                   max_overs_per_bowler: int = MAX_OVERS_PER_BOWLER,
                   bowler_profiles: dict | None = None, max_overs: int = MAX_OVERS) -> str:
    """picks the next over's bowler. an explicit `rotation` is validated
    (raises if illegal) rather than silently broken.

    without one, prefers whoever ranks best for the current over's phase
    via `bowler_profiles`, falling back to fewest overs bowled so far.
    """
    if rotation is not None:
        bowler = rotation[over_idx]
        if bowler == last_over_bowler:
            raise ValueError(f"illegal rotation: {bowler} cannot bowl consecutive overs "
                              f"(over {over_idx}) -- Law 17.6 / rulebook-cricket.md §2.1")
        if bowler_balls.get(bowler, 0) >= max_overs_per_bowler * BALLS_PER_OVER:
            raise ValueError(f"illegal rotation: {bowler} would exceed {max_overs_per_bowler} overs "
                              f"(over {over_idx}) -- ICC PC cl. 13.9.1 / rulebook-cricket.md §2.2")
        return bowler

    eligible = [b for b in bowler_pool if b != last_over_bowler
                and bowler_balls.get(b, 0) < max_overs_per_bowler * BALLS_PER_OVER]
    if not eligible:
        raise ValueError(
            "no eligible bowler can legally bowl the next over -- this bowling pool cannot "
            "complete a 20-over innings under Law 17.6 (no consecutive overs) and ICC PC "
            "cl. 13.9.1 (max 4 overs each); supply a larger bowling-capable pool "
            f"(need at least {-(-MAX_OVERS // max_overs_per_bowler)} bowlers).")

    # only prefer a phase specialist when there's real spare capacity left,
    # recomputed every over. a static pool-size check isn't safe since slack
    # can be unevenly spent already or the pool can contain duplicates.
    overs_remaining = max_overs - over_idx if over_idx is not None else None
    total_remaining_capacity = sum(
        max(0, max_overs_per_bowler * BALLS_PER_OVER - bowler_balls.get(b, 0)) for b in set(bowler_pool))
    has_slack = (overs_remaining is not None
                 and total_remaining_capacity > overs_remaining * BALLS_PER_OVER)
    if bowler_profiles is not None and has_slack:
        phase = _phase(over_idx)

        def _key(b):
            profile = bowler_profiles.get(b)
            ranks = profile.phase_rank if profile is not None else None
            rank_here = ranks.get(phase) if ranks else None
            if ranks and rank_here is not None and rank_here == min(ranks.values()):
                # proven best for this phase, use them now
                tier = 0
            elif not ranks:
                # no phase signal, safe neutral option
                tier = 1
            else:
                # specialist in a different phase, hold them back if possible
                tier = 2
            return (tier, rank_here if rank_here is not None else float("inf"), bowler_balls.get(b, 0))

        eligible.sort(key=_key)
        return eligible[0]

    eligible.sort(key=lambda b: bowler_balls.get(b, 0))
    return eligible[0]


def _classify_and_apply(outcome: str, sampled_runs: int) -> dict:
    is_legal, extras, is_wicket, next_free_hit, runs_off_bat = True, 0, False, False, 0
    if outcome == "wide":
        is_legal, extras = False, 1
    elif outcome == "noball":
        is_legal, extras, next_free_hit = False, 1, True
    elif outcome == "bye":
        extras = 1
    elif outcome == "wicket":
        is_wicket = True
    else:
        runs_off_bat = int(outcome)
    return {"is_legal": is_legal, "extras": extras, "is_wicket": is_wicket,
            "next_free_hit": next_free_hit, "runs_off_bat": runs_off_bat}


def simulate_ball(state: MatchState, bowler_id: str, outcome_model, batter_profiles: dict,
                   bowler_profiles: dict, rng: np.random.Generator,
                   forced_dismissal: dict | None = None) -> dict:
    striker = state.striker
    phase = _phase(state.over)
    force = (forced_dismissal is not None
             and forced_dismissal.get("player_id") == striker
             and forced_dismissal.get("over") == state.over
             and forced_dismissal.get("ball") == state.ball_in_over + 1)
    outcome = "wicket" if force else outcome_model.sample(
        phase, batter_profiles[striker], bowler_profiles[bowler_id], rng,
        batter_id=striker, bowler_id=bowler_id, free_hit=state.free_hit, innings=state.innings)

    applied = _classify_and_apply(outcome, 0)
    runs_off_bat, extras = applied["runs_off_bat"], applied["extras"]
    total_runs = runs_off_bat + extras

    state.score += total_runs
    if applied["is_legal"]:
        state.balls_bowled += 1
        state.ball_in_over += 1
        state.bowler_balls[bowler_id] = state.bowler_balls.get(bowler_id, 0) + 1
        state.batter_balls[striker] = state.batter_balls.get(striker, 0) + 1

    if runs_off_bat:
        state.batter_runs[striker] = state.batter_runs.get(striker, 0) + runs_off_bat
    if outcome != "bye":
        # byes/leg-byes aren't credited to the bowler, but wide/no-ball
        # penalty runs and runs off the bat are.
        state.bowler_runs_conceded[bowler_id] = state.bowler_runs_conceded.get(bowler_id, 0) + total_runs

    dismissed = None
    if applied["is_wicket"]:
        dismissed = striker
        state.wickets += 1
        state.out.add(striker)
        state.bowler_wickets[bowler_id] = state.bowler_wickets.get(bowler_id, 0) + 1

    record = {
        "innings": state.innings, "over": state.over, "ball_in_over": state.ball_in_over,
        "phase": phase, "striker": striker, "non_striker": state.batting_order[state.non_striker_idx],
        "bowler": bowler_id, "outcome": outcome, "runs_off_bat": runs_off_bat, "extras": extras,
        "runs_total": total_runs, "is_legal": applied["is_legal"], "is_wicket": applied["is_wicket"],
        "dismissed": dismissed, "free_hit": state.free_hit,
        "score": state.score, "wickets": state.wickets, "balls_bowled": state.balls_bowled,
    }

    # odd runs off a legal, non-wicket delivery swaps the striker
    if applied["is_legal"] and not applied["is_wicket"] and total_runs % 2 == 1:
        state.striker_idx, state.non_striker_idx = state.non_striker_idx, state.striker_idx

    if applied["is_wicket"]:
        if state.next_batter_idx < len(state.batting_order):
            state.striker_idx = state.next_batter_idx
            state.next_batter_idx += 1
        else:
            state.all_out = True

    state.free_hit = applied["next_free_hit"]
    return record


def simulate_over(state: MatchState, bowler_id: str, outcome_model, batter_profiles: dict,
                   bowler_profiles: dict, rng: np.random.Generator, ball_log: list,
                   forced_dismissal: dict | None = None) -> None:
    state.ball_in_over = 0
    while state.ball_in_over < BALLS_PER_OVER and not state.is_over():
        ball_log.append(simulate_ball(state, bowler_id, outcome_model, batter_profiles,
                                       bowler_profiles, rng, forced_dismissal))
    if not state.is_over():
        # ends swap every completed over regardless of the last ball's runs
        state.striker_idx, state.non_striker_idx = state.non_striker_idx, state.striker_idx
    state.over += 1
    state.last_over_bowler = bowler_id


def simulate_innings(batting_order: list, bowling_pool: list, outcome_model, batter_profiles: dict,
                      bowler_profiles: dict, target: int | None = None, rotation: list | None = None,
                      forced_dismissal: dict | None = None, rng: np.random.Generator | None = None,
                      max_overs: int = MAX_OVERS, max_overs_per_bowler: int = MAX_OVERS_PER_BOWLER,
                      max_wickets: int | None = None):
    rng = rng if rng is not None else np.random.default_rng()
    if rotation is not None and len(rotation) != max_overs:
        raise ValueError(f"rotation must specify exactly {max_overs} overs, got {len(rotation)}")
    if len(batting_order) < 2:
        raise ValueError("batting_order needs at least 2 players")

    state = MatchState(innings=2 if target is not None else 1,
                        batting_order=list(batting_order), target=target, max_wickets=max_wickets)
    ball_log: list = []
    for over_idx in range(max_overs):
        if state.is_over():
            break
        bowler_id = select_bowler(bowling_pool, state.bowler_balls, state.last_over_bowler,
                                   rotation, over_idx, max_overs_per_bowler, bowler_profiles=bowler_profiles,
                                   max_overs=max_overs)
        simulate_over(state, bowler_id, outcome_model, batter_profiles, bowler_profiles, rng,
                      ball_log, forced_dismissal)

    ball_log_df = pd.DataFrame(ball_log)
    if not ball_log_df.empty:
        ball_log_df["ball_seq"] = range(len(ball_log_df))
    return state, ball_log_df


def simulate_super_over(bat_first: dict, bowl_first: dict, outcome_model, batter_profiles: dict,
                         bowler_profiles: dict, rng: np.random.Generator) -> dict:
    """one super over each side, max 1 over, ends early on 2 wickets.

    simplification: uses each side's full XI/bowling pool instead of the
    real nominated-players rule, so a repeated (re-tied) super over is less
    strict than real eligibility rules.
    """
    s1, log1 = simulate_innings(bat_first["batting_order"], bowl_first["bowling_pool"], outcome_model,
                                 batter_profiles, bowler_profiles, rng=rng,
                                 max_overs=SUPER_OVER_OVERS, max_overs_per_bowler=SUPER_OVER_OVERS,
                                 max_wickets=SUPER_OVER_MAX_WICKETS)
    target = s1.score + 1
    s2, log2 = simulate_innings(bowl_first["batting_order"], bat_first["bowling_pool"], outcome_model,
                                 batter_profiles, bowler_profiles, target=target, rng=rng,
                                 max_overs=SUPER_OVER_OVERS, max_overs_per_bowler=SUPER_OVER_OVERS,
                                 max_wickets=SUPER_OVER_MAX_WICKETS)
    if s2.score > s1.score:
        winner = bowl_first["name"]
    elif s2.score < s1.score:
        winner = bat_first["name"]
    else:
        winner = "Tie"
    return {"bat_first_team": bat_first["name"], "bowl_first_team": bowl_first["name"],
            "bat_first_score": s1.score, "bat_first_wickets": s1.wickets,
            "bowl_first_score": s2.score, "bowl_first_wickets": s2.wickets,
            "winner": winner, "bat_first_log": log1, "bowl_first_log": log2}


def super_over_win_probabilities(team1: dict, team2: dict, batting_first: str, outcome_model,
                                  batter_profiles: dict, bowler_profiles: dict,
                                  n_reps: int = 200, rng_seed: int | None = None) -> dict:
    """estimates which side is more likely to win a super over between the
    two teams, independent of whether a full match actually tied.
    """
    rng = np.random.default_rng(rng_seed)
    bat_first, bowl_first = (team1, team2) if batting_first == "team1" else (team2, team1)
    winners = [simulate_super_over(bat_first, bowl_first, outcome_model, batter_profiles,
                                    bowler_profiles, rng)["winner"] for _ in range(n_reps)]
    counts = {name: winners.count(name) / n_reps for name in (bat_first["name"], bowl_first["name"], "Tie")}
    return {"bats_first": bat_first["name"], "n_reps": n_reps, "win_probability": counts}


def _attach_win_prob(ball_log_df: pd.DataFrame, winprob, innings: int,
                      target: int | None = None) -> pd.DataFrame:
    if ball_log_df.empty:
        return ball_log_df
    df = ball_log_df.copy()
    df["balls_remaining"] = TOTAL_LEGAL_BALLS - df["balls_bowled"]
    if target is not None:
        df["runs_required"] = (target - df["score"]).clip(lower=0)
    wp = []
    for _, r in df.iterrows():
        wp.append(winprob.predict_one(
            innings=innings, wickets=int(r["wickets"]), balls_remaining=int(r["balls_remaining"]),
            runs_required=(int(r["runs_required"]) if target is not None else None),
            balls_bowled=int(r["balls_bowled"]), score=int(r["score"])))
    df["win_prob_batting"] = wp
    return df


def simulate_match(team1: dict, team2: dict, batting_first: str, outcome_model, batter_profiles: dict,
                    bowler_profiles: dict, winprob, forced_dismissal: dict | None = None,
                    n_reps: int = 1, rng_seed: int | None = None) -> list:
    """`team1`/`team2`: `{"name", "batting_order", "bowling_pool", "rotation"}`.
    `batting_first` is `"team1"` or `"team2"`, the toss winner's choice.

    returns one summary dict per Monte Carlo rep, with both innings' logs,
    final scores, and the winner. a tied chase is resolved via super overs
    (`super_over_rounds`); "Tie" only shows up if MAX_SUPER_OVER_ROUNDS gets
    exhausted.
    """
    rng = np.random.default_rng(rng_seed)
    bat_first, bowl_first = (team1, team2) if batting_first == "team1" else (team2, team1)

    reps = []
    for _ in range(n_reps):
        s1, log1 = simulate_innings(bat_first["batting_order"], bowl_first["bowling_pool"],
                                     outcome_model, batter_profiles, bowler_profiles,
                                     rotation=bowl_first.get("rotation"),
                                     forced_dismissal=forced_dismissal, rng=rng)
        log1 = _attach_win_prob(log1, winprob, innings=1)

        target = s1.score + 1
        s2, log2 = simulate_innings(bowl_first["batting_order"], bat_first["bowling_pool"],
                                     outcome_model, batter_profiles, bowler_profiles,
                                     target=target, rotation=bat_first.get("rotation"),
                                     forced_dismissal=forced_dismissal, rng=rng)
        log2 = _attach_win_prob(log2, winprob, innings=2, target=target)

        super_over_rounds: list = []
        if s2.score >= target:
            winner = bowl_first["name"]
        elif s2.score == target - 1:
            # tied run-chase: side that batted second bats first in the
            # super over, any repeat swaps who bats first.
            winner = "Tie"
            so_bat_first, so_bowl_first = bowl_first, bat_first
            for _ in range(MAX_SUPER_OVER_ROUNDS):
                so = simulate_super_over(so_bat_first, so_bowl_first, outcome_model,
                                          batter_profiles, bowler_profiles, rng)
                super_over_rounds.append(so)
                if so["winner"] != "Tie":
                    winner = so["winner"]
                    break
                so_bat_first, so_bowl_first = so_bowl_first, so_bat_first
        else:
            winner = bat_first["name"]

        reps.append({
            "batting_first_team": bat_first["name"], "bowling_first_team": bowl_first["name"],
            "first_innings_score": s1.score, "first_innings_wickets": s1.wickets,
            "second_innings_score": s2.score, "second_innings_wickets": s2.wickets,
            "target": target, "winner": winner,
            "first_innings_log": log1, "second_innings_log": log2,
            "super_over_rounds": super_over_rounds,
        })
    return reps

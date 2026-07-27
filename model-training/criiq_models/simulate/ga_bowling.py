"""Genetic algorithm: search over legal bowler-to-over rotations.

The repo's existing optimizer (`selection/optimize.py`) is exact MILP for a
single "pick 11 from a pool" decision -- it can't express an *in-match
sequence* subject to Law 17.6 (no consecutive overs) and ICC PC cl. 13.9.1
(max 4 overs each) cleanly, since which bowler is legal to bowl a given over
depends on every earlier choice in the sequence. A GA searches this
combinatorial space instead, with every candidate repaired back to a
rules-legal rotation after crossover/mutation (never merely penalized), so
fitness always reflects an actually-playable match.

**The recognized bowlers take the full quota between them by default, not
an even spread across everyone bowling-capable.** A real T20 side has (in
the ordinary case) exactly 5 specialist bowlers who share all 20 overs, 4
each -- an all-rounder or part-timer chips in only occasionally, not as an
equal competitor for overs. `primary_bowlers` (the up to 5 recognized
specialists, passed in by the caller) gets this default treatment: initial
rotations and the repair fallback both prefer them, so the search starts
from -- and stays close to -- a realistic default, while ordinary mutation
(which reassigns a slot to *any* eligible bowler, uniformly) still lets a
part-timer be "introduced" and evolve into the result if that's genuinely
better for this specific matchup. Omitting `primary_bowlers` recovers the
old even-spread-across-everyone behaviour.

Fitness is the (negative) mean runs conceded across a handful of
`simulate_innings` Monte Carlo reps -- a single completed innings with no
chase target. This is the tractable, correct proxy for bowling-side win
probability: restricting the opposition to fewer runs is exactly what a
captain choosing a bowling rotation controls, without needing a full two-
innings match simulated per fitness evaluation (an order of magnitude more
expensive, for no extra signal about the rotation itself).

**Fitness is noisy** (a Monte Carlo mean over a handful of reps), so the
tracked "best" is protected against that noise the same way `ga_batting.py`
protects its own: elitism (the best-known rotation always stays in the gene
pool, never dropped for scoring worse on an unrelated noisy re-evaluation)
and a re-verification step (extra reps) before accepting an apparent new
best. `fitness_history` logs the running best-known fitness, monotonically
non-decreasing by construction, not each generation's raw top score.
"""
from __future__ import annotations

import numpy as np

from .engine import MAX_OVERS, MAX_OVERS_PER_BOWLER, simulate_innings

_VERIFY_REP_MULTIPLIER = 3  # extra reps used to confirm an apparent new best


def _even_quotas(bowler_pool: list, rng: np.random.Generator,
                  max_overs_per_bowler: int, total_overs: int) -> dict:
    """Distributes `total_overs` as evenly as possible across `bowler_pool`
    (each capped at `max_overs_per_bowler`), randomizing *which* bowlers get
    the leftover "extra" over so repeated calls explore different quota
    splits.
    """
    n = len(bowler_pool)
    if n == 0:
        if total_overs == 0:
            return {}
        raise ValueError("no bowlers available to cover the remaining overs")
    base, remainder = divmod(total_overs, n)
    if base > max_overs_per_bowler:
        raise ValueError(f"bowler pool of {n} cannot legally bowl {total_overs} overs at max "
                          f"{max_overs_per_bowler} overs each")
    quotas = {b: base for b in bowler_pool}
    order = list(bowler_pool)
    rng.shuffle(order)
    for b in order[:remainder]:
        quotas[b] += 1
    return quotas


def _quotas(bowler_pool: list, rng: np.random.Generator, primary_bowlers: list | None = None,
            max_overs_per_bowler: int = MAX_OVERS_PER_BOWLER, total_overs: int = MAX_OVERS) -> dict:
    primary = [b for b in (primary_bowlers or []) if b in bowler_pool]
    if not primary:
        return _even_quotas(bowler_pool, rng, max_overs_per_bowler, total_overs)

    others = [b for b in bowler_pool if b not in primary]
    quotas = {b: 0 for b in bowler_pool}
    primary_capacity = len(primary) * max_overs_per_bowler
    if primary_capacity >= total_overs:
        quotas.update(_even_quotas(primary, rng, max_overs_per_bowler, total_overs))
        return quotas
    # Fewer recognized bowlers than needed to cover the innings alone (a real
    # captain's forced situation) -- each bowls a full quota, and the
    # shortfall goes to the next-best options.
    for b in primary:
        quotas[b] = max_overs_per_bowler
    quotas.update(_even_quotas(others, rng, max_overs_per_bowler, total_overs - primary_capacity))
    return quotas


def _sequence(quotas: dict, rng: np.random.Generator) -> list:
    """Greedy "most overs remaining, excluding the previous over's bowler"
    scheduling -- the standard, provably-correct algorithm for arranging
    items with a no-two-adjacent-equal constraint (equivalent to the classic
    "task scheduler"/"reorganize string" problem), guaranteed to succeed
    whenever the largest quota is at most half the total (always true here:
    a single bowler's 4-over cap is well under half of 20 overs).
    """
    remaining = {b: q for b, q in quotas.items() if q > 0}
    last = None
    rotation = []
    for _ in range(sum(quotas.values())):
        candidates = [b for b, q in remaining.items() if q > 0 and b != last]
        if not candidates:
            raise ValueError("bowler pool cannot legally complete the innings under Law 17.6 "
                              "(no consecutive overs) + ICC PC cl. 13.9.1 (max 4 overs each)")
        max_q = max(remaining[b] for b in candidates)
        top = [b for b in candidates if remaining[b] == max_q]
        choice = top[rng.integers(len(top))]
        rotation.append(choice)
        remaining[choice] -= 1
        last = choice
    return rotation


def _random_valid_rotation(bowler_pool: list, rng: np.random.Generator,
                            primary_bowlers: list | None = None) -> list:
    return _sequence(_quotas(bowler_pool, rng, primary_bowlers), rng)


def _repair(rotation: list, bowler_pool: list, rng: np.random.Generator,
            primary_bowlers: list | None = None) -> list:
    """Rebuilds a possibly-illegal post-crossover/mutation rotation into a
    guaranteed-legal one. A naive left-to-right patch (walk the rotation,
    swap in any *currently* eligible bowler wherever a slot is illegal) is
    NOT safe in general: crossover recombines two 20-length parents without
    any regard for the resulting per-bowler over-counts, and with a
    razor-tight pool (exactly 5 bowlers at 4 overs each, zero slack -- a
    real case, not hypothetical: confirmed live with a men's T20I side that
    had only 5 bowling-capable players) that can skew several bowlers past
    4 overs before repair even starts, painting a left-to-right walk into a
    corner with no eligible bowler left for a later slot even though the
    *pool as a whole* can legally cover 20 overs.

    Instead: count how many overs each bowler already has in the candidate
    (capped at the legal maximum), reassign any overs lost to that cap (or
    to a bowler no longer in `bowler_pool`) to whichever bowler has spare
    capacity -- preferring a recognized `primary_bowlers` option, mirroring
    a real captain reaching for a part-timer only once the frontline attack
    is exhausted -- and then re-derive the actual over-by-over sequence with
    `_sequence`, the same provably-safe "most overs remaining, excluding the
    previous over's bowler" algorithm a fresh rotation is built with. This
    preserves crossover's real genetic content (which bowlers survive, and
    roughly how many overs each), just not the exact original slot
    positions, and can never fail for a pool that can legally bowl 20 overs
    at all.
    """
    total_overs = len(rotation)
    counts: dict = {}
    for b in rotation:
        if b in bowler_pool:
            counts[b] = counts.get(b, 0) + 1

    quotas = {b: min(n, MAX_OVERS_PER_BOWLER) for b, n in counts.items()}
    shortfall = total_overs - sum(quotas.values())
    if shortfall > 0:
        primary_set = set(b for b in (primary_bowlers or []) if b in bowler_pool)
        candidates = sorted(bowler_pool, key=lambda b: (b not in primary_set, quotas.get(b, 0)))
        for b in candidates:
            if shortfall <= 0:
                break
            room = MAX_OVERS_PER_BOWLER - quotas.get(b, 0)
            take = min(room, shortfall)
            if take > 0:
                quotas[b] = quotas.get(b, 0) + take
                shortfall -= take
    if shortfall > 0:
        raise ValueError("bowler pool cannot legally complete 20 overs during GA repair")

    return _sequence({b: q for b, q in quotas.items() if q > 0}, rng)


def _fitness(rotation: list, batting_order: list, outcome_model, batter_profiles: dict,
             bowler_profiles: dict, rng: np.random.Generator, n_reps: int) -> float:
    bowling_pool = list(dict.fromkeys(rotation))
    totals = []
    for _ in range(n_reps):
        state, _ = simulate_innings(batting_order, bowling_pool, outcome_model, batter_profiles,
                                     bowler_profiles, rotation=rotation, rng=rng)
        totals.append(state.score)
    return -float(np.mean(totals))


def _crossover(a: list, b: list, rng: np.random.Generator) -> list:
    point = int(rng.integers(1, MAX_OVERS))
    return a[:point] + b[point:]


def _mutate(rotation: list, bowler_pool: list, rng: np.random.Generator, rate: float = 0.15) -> list:
    out = list(rotation)
    for i in range(len(out)):
        if rng.random() < rate:
            out[i] = bowler_pool[rng.integers(len(bowler_pool))]
    return out


def optimize_bowling_rotation(bowler_pool: list, batting_order: list, outcome_model, batter_profiles: dict,
                               bowler_profiles: dict, primary_bowlers: list | None = None,
                               pop_size: int = 40, generations: int = 60,
                               n_reps: int = 8, rng_seed: int | None = None) -> dict:
    """`primary_bowlers`: the up to 5 recognized specialist bowlers in
    `bowler_pool` -- if given, they default to taking the full quota (4
    overs each) between them; other pool members are only introduced via
    mutation or when the primary group runs short (see module docstring).
    `None` recovers the old even-spread-across-everyone behaviour.
    """
    if len(bowler_pool) * MAX_OVERS_PER_BOWLER < MAX_OVERS:
        raise ValueError(
            f"bowler pool of {len(bowler_pool)} cannot legally bowl {MAX_OVERS} overs at "
            f"max {MAX_OVERS_PER_BOWLER} overs each -- need at least "
            f"{-(-MAX_OVERS // MAX_OVERS_PER_BOWLER)} bowling-capable players")

    rng = np.random.default_rng(rng_seed)
    population = [_random_valid_rotation(bowler_pool, rng, primary_bowlers) for _ in range(pop_size)]
    history: list = []
    best = population[0]
    best_fitness = _fitness(best, batting_order, outcome_model, batter_profiles, bowler_profiles, rng, n_reps)

    for _ in range(generations):
        scored = [(rot, _fitness(rot, batting_order, outcome_model, batter_profiles, bowler_profiles,
                                  rng, n_reps)) for rot in population]
        scored.sort(key=lambda x: -x[1])

        top_rot, top_fitness = scored[0]
        if top_fitness > best_fitness:
            verified_fitness = _fitness(top_rot, batting_order, outcome_model, batter_profiles,
                                         bowler_profiles, rng, n_reps * _VERIFY_REP_MULTIPLIER)
            if verified_fitness > best_fitness:
                best, best_fitness = top_rot, verified_fitness
        history.append(best_fitness)

        survivors = [rot for rot, _ in scored[:max(2, pop_size // 2 - 1)]]
        survivors.append(best)  # elitism: the true best-known never drops out of the gene pool
        children = []
        while len(survivors) + len(children) < pop_size:
            a = survivors[rng.integers(len(survivors))]
            b = survivors[rng.integers(len(survivors))]
            child = _repair(_mutate(_crossover(a, b, rng), bowler_pool, rng), bowler_pool, rng, primary_bowlers)
            children.append(child)
        population = survivors + children

    final_fitness = _fitness(best, batting_order, outcome_model, batter_profiles, bowler_profiles,
                              rng, n_reps=max(30, n_reps * _VERIFY_REP_MULTIPLIER * 2))
    overs_per_bowler = {b: best.count(b) for b in dict.fromkeys(best)}
    return {"rotation": best, "expected_runs_conceded": round(-final_fitness, 2),
            "overs_per_bowler": overs_per_bowler, "fitness_history": history}

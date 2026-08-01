"""genetic algorithm that searches for the best batting order.

given a fixed XI, finds the order that maximizes the outcome against a
specific opposition. `batting_groups` keeps the search realistic: openers,
middle order and tail are searched as separate permutation groups so a
bowler never ends up opening.

fitness is a noisy Monte Carlo mean, so the best-known individual is kept
via elitism and re-verified with extra reps before being replaced.
"""
from __future__ import annotations

import numpy as np

from .engine import simulate_innings

_VERIFY_REP_MULTIPLIER = 3  # extra reps used to confirm an apparent new best


def _fitness(order: list, bowler_pool: list, outcome_model, batter_profiles: dict, bowler_profiles: dict,
             target: int | None, rng: np.random.Generator, n_reps: int) -> float:
    results = []
    for _ in range(n_reps):
        state, _ = simulate_innings(order, bowler_pool, outcome_model, batter_profiles, bowler_profiles,
                                     target=target, rng=rng)
        results.append(state.score)
    if target is not None:
        return float(np.mean([1.0 if s >= target else 0.0 for s in results]))
    return float(np.mean(results))


def _ox_crossover(a: list, b: list, rng: np.random.Generator) -> list:
    n = len(a)
    if n < 2:
        return list(a)
    i, j = sorted(rng.choice(n, size=2, replace=False))
    child: list = [None] * n
    child[i:j] = a[i:j]
    fill = [x for x in b if x not in child]
    pos = 0
    for k in range(n):
        if child[k] is None:
            child[k] = fill[pos]
            pos += 1
    return child


def _swap_mutate(order: list, rng: np.random.Generator, rate: float = 0.2) -> list:
    out = list(order)
    if len(out) >= 2 and rng.random() < rate:
        i, j = rng.choice(len(out), size=2, replace=False)
        out[i], out[j] = out[j], out[i]
    return out


def _validate_groups(batting_groups: list) -> list:
    groups = [list(g) for g in batting_groups if g]
    if not groups:
        raise ValueError("batting_groups must contain at least one non-empty group")
    all_ids = [p for g in groups for p in g]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("batting_groups must not repeat a player across groups")
    if len(all_ids) < 2:
        raise ValueError("need at least 2 players to order a batting lineup")
    return groups


def optimize_batting_order(batting_groups: list, bowler_pool: list, outcome_model, batter_profiles: dict,
                            bowler_profiles: dict, target: int | None = None, pop_size: int = 40,
                            generations: int = 60, n_reps: int = 8, rng_seed: int | None = None) -> dict:
    """`batting_groups`: ordered list of player-id groups, e.g.
    `[[opener_a, opener_b], [top_middle_1..N], [tail_1..M]]` (see module
    docstring). for the simplest fully-unconstrained search, pass a single
    group containing all players: `[[p1, p2, ..., p11]]`.
    """
    groups = _validate_groups(batting_groups)
    rng = np.random.default_rng(rng_seed)

    def _full_order(group_perms: list) -> list:
        order: list = []
        for perm in group_perms:
            order.extend(perm)
        return order

    def _fitness_of(group_perms: list, reps: int) -> float:
        return _fitness(_full_order(group_perms), bowler_pool, outcome_model, batter_profiles, bowler_profiles,
                         target, rng, reps)

    def _random_individual() -> list:
        perms = []
        for g in groups:
            p = list(g)
            rng.shuffle(p)
            perms.append(p)
        return perms

    def _crossover(a: list, b: list) -> list:
        return [_ox_crossover(ga, gb, rng) for ga, gb in zip(a, b)]

    def _mutate(perms: list) -> list:
        return [_swap_mutate(g, rng) for g in perms]

    population = [_random_individual() for _ in range(pop_size)]
    history: list = []
    best = [list(g) for g in groups]
    best_fitness = _fitness_of(best, n_reps)

    for _ in range(generations):
        scored = [(ind, _fitness_of(ind, n_reps)) for ind in population]
        scored.sort(key=lambda x: -x[1])

        top_ind, top_fitness = scored[0]
        if top_fitness > best_fitness:
            verified_fitness = _fitness_of(top_ind, n_reps * _VERIFY_REP_MULTIPLIER)
            if verified_fitness > best_fitness:
                best, best_fitness = top_ind, verified_fitness
        history.append(best_fitness)

        survivors = [ind for ind, _ in scored[:max(2, pop_size // 2 - 1)]]
        survivors.append(best)  # elitism: keep the best-known individual in the pool
        children = []
        while len(survivors) + len(children) < pop_size:
            a = survivors[rng.integers(len(survivors))]
            b = survivors[rng.integers(len(survivors))]
            children.append(_mutate(_crossover(a, b)))
        population = survivors + children

    final_fitness = _fitness_of(best, max(30, n_reps * _VERIFY_REP_MULTIPLIER * 2))
    metric_name = "win_probability" if target is not None else "expected_score"
    return {"batting_order": _full_order(best), "batting_groups": [list(g) for g in best],
            metric_name: round(final_fitness, 3), "fitness_history": history}

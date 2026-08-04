from __future__ import annotations

import numpy as np

from .engine import MAX_OVERS, MAX_OVERS_PER_BOWLER, simulate_innings
from .ga_bowling import _even_quotas, _sequence
from .outcomes import PHASES

_BASELINE_N_REPS = 24
_SWAP_N_REPS = 12


def _phase_of_over(over_idx: int) -> str:
    if over_idx <= 5:
        return "powerplay"
    if over_idx <= 14:
        return "middle"
    return "death"


def _effective_strike_rate(profile, target: int | None) -> float | None:
    if target is not None and profile.chasing_strike_rate is not None:
        return profile.chasing_strike_rate
    if target is None and profile.setting_strike_rate is not None:
        return profile.setting_strike_rate
    return profile.strike_rate


def _batting_metric(order: list, bowler_pool: list, outcome_model, batter_profiles: dict,
                     bowler_profiles: dict, target: int | None, rng: np.random.Generator,
                     n_reps: int) -> float:
    results = []
    for _ in range(n_reps):
        state, _ = simulate_innings(order, bowler_pool, outcome_model, batter_profiles, bowler_profiles,
                                     target=target, rng=rng)
        results.append(state.score)
    if target is not None:
        return float(np.mean([1.0 if s >= target else 0.0 for s in results]))
    return float(np.mean(results))


def _naive_batting_order(batting_groups: list, batter_profiles: dict, target: int | None) -> list:
    order = []
    for group in batting_groups:
        ranked = sorted(group, key=lambda pid: -(_effective_strike_rate(batter_profiles[pid], target) or 0.0))
        order.extend(ranked)
    return order


def _group_bounds(batting_groups: list) -> list:
    bounds = []
    idx = 0
    for group in batting_groups:
        bounds.append((idx, idx + len(group) - 1))
        idx += len(group)
    return bounds


def explain_batting_order(batting_order: list, batting_groups: list, bowler_pool: list, outcome_model,
                           batter_profiles: dict, bowler_profiles: dict, target: int | None,
                           chosen_metric: float, metric_name: str, rng_seed: int | None = None,
                           n_reps: int = _BASELINE_N_REPS) -> dict:
    rng = np.random.default_rng(rng_seed)

    naive_order = _naive_batting_order(batting_groups, batter_profiles, target)
    baseline_metric = _batting_metric(naive_order, bowler_pool, outcome_model, batter_profiles,
                                       bowler_profiles, target, rng, n_reps)

    slots = []
    for i, pid in enumerate(batting_order):
        sr = _effective_strike_rate(batter_profiles[pid], target)
        slots.append({"position": i + 1, "player_id": pid,
                       "strike_rate": None if sr is None else round(sr, 1)})

    bounds = _group_bounds(batting_groups)

    def _same_group(i: int, j: int) -> bool:
        return any(lo <= i <= hi and lo <= j <= hi for lo, hi in bounds)

    adjacent_swaps = []
    for i in range(len(batting_order) - 1):
        if not _same_group(i, i + 1):
            continue
        swapped = list(batting_order)
        swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
        swapped_metric = _batting_metric(swapped, bowler_pool, outcome_model, batter_profiles,
                                          bowler_profiles, target, rng, max(4, n_reps // 2))
        adjacent_swaps.append({"positions": [i + 1, i + 2],
                                "player_ids": [batting_order[i], batting_order[i + 1]],
                                "delta": round(swapped_metric - chosen_metric, 4)})

    most_costly_swap = min(adjacent_swaps, key=lambda s: s["delta"]) if adjacent_swaps else None

    return {
        "metric_name": metric_name,
        "chosen_metric": chosen_metric,
        "baseline_metric": round(baseline_metric, 4),
        "baseline_description": "each band's players sorted by strike rate alone, highest first",
        "improvement_over_baseline": round(chosen_metric - baseline_metric, 4),
        "slots": slots,
        "adjacent_swaps": adjacent_swaps,
        "most_costly_adjacent_swap": most_costly_swap,
    }


def _bowling_metric(rotation: list, batting_order: list, outcome_model, batter_profiles: dict,
                     bowler_profiles: dict, rng: np.random.Generator, n_reps: int) -> float:
    bowling_pool = list(dict.fromkeys(rotation))
    totals = []
    for _ in range(n_reps):
        state, _ = simulate_innings(batting_order, bowling_pool, outcome_model, batter_profiles,
                                     bowler_profiles, rotation=rotation, rng=rng)
        totals.append(state.score)
    return float(np.mean(totals))


def explain_bowling_rotation(rotation: list, batting_order: list, outcome_model, batter_profiles: dict,
                              bowler_profiles: dict, overs_per_bowler: dict, expected_runs_conceded: float,
                              rng_seed: int | None = None, n_reps: int = _BASELINE_N_REPS) -> dict:
    rng = np.random.default_rng(rng_seed)
    bowler_pool = list(dict.fromkeys(rotation))

    naive_rotation = _sequence(_even_quotas(bowler_pool, rng, MAX_OVERS_PER_BOWLER, MAX_OVERS), rng)
    baseline_runs = _bowling_metric(naive_rotation, batting_order, outcome_model, batter_profiles,
                                     bowler_profiles, rng, n_reps)

    phase_overs: dict = {}
    for over_idx, bowler_id in enumerate(rotation):
        phase_overs.setdefault(bowler_id, []).append(_phase_of_over(over_idx))

    bowlers = []
    for bowler_id, overs in overs_per_bowler.items():
        phases_bowled = phase_overs.get(bowler_id, [])
        phase_counts = {p: phases_bowled.count(p) for p in PHASES if phases_bowled.count(p) > 0}
        ranks = bowler_profiles[bowler_id].phase_rank
        sizes = bowler_profiles[bowler_id].phase_rank_size
        phase_rank_here = {p: {"rank": ranks[p], "size": sizes.get(p)}
                            for p in phase_counts if p in ranks}
        bowlers.append({"player_id": bowler_id, "overs": overs,
                         "phase_overs": phase_counts, "phase_rank": phase_rank_here})

    return {
        "expected_runs_conceded": expected_runs_conceded,
        "baseline_runs_conceded": round(baseline_runs, 2),
        "baseline_description": "an even split of overs across the bowling pool, ignoring phase fit",
        "improvement_over_baseline": round(baseline_runs - expected_runs_conceded, 2),
        "bowlers": bowlers,
    }

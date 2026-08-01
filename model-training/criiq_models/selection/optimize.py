"""constrained playing-XI selection.

picking the top-11 by raw score can produce an unbalanced side (e.g. 9
batters, 2 bowlers, zero openers). formulates the pick as a 0/1 linear
program via scipy.optimize.milp: maximize total score subject to exactly
xi_size players, with minimum batting/bowling-capable, keeper and opener
counts. provably optimal, unlike greedy-with-quotas which can lock in a
suboptimal pick early with no way to backtrack.

the keeper constraint is soft, only added when the pool has a player
flagged is_keeper, since that's unset for most of the player pool. the
opener constraint degrades the same way if too few players have a recorded
opening position. a greedy fallback covers the rare case milp finds no
feasible solution.

once selected, the XI is presented like a real team sheet, see
_team_sheet_order: two best-scoring openers lock slots 1-2, the rest of the
batting-relevant players fill the order by score, bowlers trail the tail.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from ..config import SETTINGS
from ..features.common import batting_capable, bowling_capable


def is_opener(p: dict, threshold: float = SETTINGS.opener_position_threshold) -> bool:
    position = p.get("batting_position_median")
    return position is not None and position <= threshold


def slot_category(p: dict, opener_threshold: float = SETTINGS.opener_position_threshold) -> str:
    """"opener" / "core_batting" / "bowler_tail": the same partition used for
    team-sheet ordering and for finding "the next-best alternative in this
    role" when explaining a selection (see recommend/explain.py).
    """
    if is_opener(p, opener_threshold):
        return "opener"
    if p["role_bucket"] == "bowler":
        return "bowler_tail"
    return "core_batting"


def _capability_masks(scored_players: list[dict],
                       opener_threshold: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    bat = np.array([1.0 if batting_capable(p["role_bucket"]) else 0.0 for p in scored_players])
    bowl = np.array([1.0 if bowling_capable(p["role_bucket"]) else 0.0 for p in scored_players])
    keeper = np.array([1.0 if p.get("is_keeper") else 0.0 for p in scored_players])
    opener = np.array([1.0 if is_opener(p, opener_threshold) else 0.0 for p in scored_players])
    return bat, bowl, keeper, opener


def _greedy_fallback(scored_players: list[dict], xi_size: int, min_bat: int, min_bowl: int,
                      min_keeper: int, min_opener: int, opener_threshold: float) -> list[dict]:
    ranked = sorted(scored_players, key=lambda p: -p["score"])
    xi = ranked[:xi_size]
    bench = ranked[xi_size:]

    def _fix(min_needed: int, capable) -> None:
        nonlocal xi, bench
        have = sum(1 for p in xi if capable(p))
        while have < min_needed:
            candidates = [p for p in bench if capable(p)]
            if not candidates:
                break
            best_candidate = max(candidates, key=lambda p: p["score"])
            worst_incapable = min(
                (p for p in xi if not capable(p)),
                key=lambda p: p["score"], default=None)
            if worst_incapable is None:
                break
            xi = [best_candidate if p is worst_incapable else p for p in xi]
            bench = [worst_incapable if p is best_candidate else p for p in bench]
            have += 1

    _fix(min_bat, lambda p: batting_capable(p["role_bucket"]))
    _fix(min_bowl, lambda p: bowling_capable(p["role_bucket"]))
    _fix(min_keeper, lambda p: bool(p.get("is_keeper")))
    _fix(min_opener, lambda p: is_opener(p, opener_threshold))
    return xi


def _team_sheet_order(xi: list[dict], opener_threshold: float) -> list[dict]:
    """orders a selected XI like a real batting lineup.

    openers: the two best-scoring opener-capable players take slots 1-2. any
    additional opener-capable player drops into the same merit-ranked pool
    as the rest of the order instead of being stacked at slot 3.

    slots 3+: every remaining non-bowler, ranked by score.
    tail: specialist bowlers, ranked by score.

    if fewer than 2 opener-capable players exist, the best-scoring remaining
    batting-relevant players fill the gap so slots 1-2 always exist.
    """
    categories = {p["player_id"]: slot_category(p, opener_threshold) for p in xi}
    openers_pool = sorted((p for p in xi if categories[p["player_id"]] == "opener"),
                          key=lambda p: -p["score"])
    bowler_tail = sorted((p for p in xi if categories[p["player_id"]] == "bowler_tail"),
                         key=lambda p: -p["score"])
    core = sorted((p for p in xi if categories[p["player_id"]] == "core_batting"),
                  key=lambda p: -p["score"])

    openers, overflow_openers = openers_pool[:2], openers_pool[2:]
    core = sorted(core + overflow_openers, key=lambda p: -p["score"])

    while len(openers) < 2 and core:
        openers.append(core.pop(0))

    return openers + core + bowler_tail


_ROLE_POOL_KEYS = {"batter": "batters", "all-rounder": "all_rounders", "bowler": "bowlers"}


def role_pools(scored_players: list[dict]) -> dict:
    """splits a scored pool into the three views a coach thinks in: batters,
    all-rounders, bowlers, each ranked by score, plus an unknown bucket.
    purely presentational, doesn't change the XI select_xi produces.
    """
    pools = {"batters": [], "all_rounders": [], "bowlers": [], "unknown": []}
    for p in scored_players:
        key = _ROLE_POOL_KEYS.get(p.get("role_bucket"), "unknown")
        pools[key].append(p)
    for key in pools:
        pools[key] = sorted(pools[key], key=lambda p: -p["score"])
    return pools


SPECIALIST_ARCHETYPES = ("finisher", "power hitter", "anchor")


def _highlight_metric(arch: str, inp: dict) -> float | None:
    """the role-defining quality to rank an archetype's members by: finisher
    = death-overs strike rate, power hitter = six rate. ranking by the
    composite score instead would bury the players this exists to surface,
    since that score undervalues a big-hitting finisher. anchor falls back
    to the composite score.
    """
    if arch == "finisher":
        return inp.get("bat_best_phase_sr")
    if arch == "power hitter":
        return inp.get("bat_six_rate")
    return None


def role_highlights(scored_players: list[dict], archetypes=SPECIALIST_ARCHETYPES) -> dict:
    """best available player of each specialist batting archetype (finisher,
    power hitter, anchor) across the whole scored pool, ranked by that
    role's defining metric rather than the composite score, since a genuine
    finisher can rate low on WPA and fall outside the headline shortlist.
    players without a profile are skipped.
    """
    out = {}
    for arch in archetypes:
        members = [p for p in scored_players
                   if ((p.get("components") or {}).get("inputs") or {}).get("archetype") == arch]
        if members:
            out[arch] = max(members, key=lambda p: (
                _highlight_metric(arch, p["components"]["inputs"]) if _highlight_metric(arch, p["components"]["inputs"]) is not None else -1.0,
                p["score"]))
    return out


def analyze_xi(scored_players: list[dict], player_ids: list[str],
               settings: object = SETTINGS) -> dict:
    """scores and checks a specific, already-chosen XI against the same
    constraints select_xi enforces, and reports how it compares to the
    optimal pick. distinct from select_xi, which finds the best XI, this
    answers "how good is this specific XI".

    player_ids not found in scored_players (typo, retired, wrong scope) are
    reported in missing_player_ids rather than silently dropped or raising.
    """
    by_id = {p["player_id"]: p for p in scored_players}
    chosen, missing = [], []
    for pid in player_ids:
        if pid in by_id:
            chosen.append(by_id[pid])
        else:
            missing.append(pid)

    opener_threshold = settings.opener_position_threshold
    # same soft-degradation select_xi applies, computed from the full pool
    # so the comparison to select_xi's own XI is apples-to-apples.
    full_bat, full_bowl, full_keeper, full_opener = _capability_masks(scored_players, opener_threshold)
    required = {
        "xi_size": min(settings.xi_size, len(scored_players)),
        "min_batting_capable": int(min(settings.min_batting_capable, full_bat.sum())),
        "min_bowling_capable": int(min(settings.min_bowling_capable, full_bowl.sum())),
        "min_keepers": int(min(settings.min_keepers, full_keeper.sum())),
        "min_openers": int(min(settings.min_openers, full_opener.sum())),
    }

    bat_mask, bowl_mask, keeper_mask, opener_mask = _capability_masks(chosen, opener_threshold)
    counts = {
        "size": len(chosen),
        "batting_capable": int(bat_mask.sum()),
        "bowling_capable": int(bowl_mask.sum()),
        "keepers": int(keeper_mask.sum()),
        "openers": int(opener_mask.sum()),
    }

    violations = []
    if counts["size"] != required["xi_size"]:
        violations.append(f"{counts['size']} players selected, not {required['xi_size']}")
    if counts["batting_capable"] < required["min_batting_capable"]:
        violations.append(f"only {counts['batting_capable']} batting-capable, "
                           f"need {required['min_batting_capable']}")
    if counts["bowling_capable"] < required["min_bowling_capable"]:
        violations.append(f"only {counts['bowling_capable']} bowling-capable, "
                           f"need {required['min_bowling_capable']}")
    if counts["keepers"] < required["min_keepers"]:
        violations.append(f"no recognized wicket-keeper (need {required['min_keepers']})")
    if counts["openers"] < required["min_openers"]:
        violations.append(f"only {counts['openers']} recognized opener(s), "
                           f"need {required['min_openers']}")

    total_score = round(sum(p["score"] for p in chosen), 1)
    ordered = (_team_sheet_order(chosen, opener_threshold)
               if counts["size"] == required["xi_size"] else chosen)

    optimal = select_xi(scored_players, settings)
    optimal_ids = {p["player_id"] for p in optimal["xi"]}
    optimal_total = round(sum(p["score"] for p in optimal["xi"]), 1)
    chosen_ids = {p["player_id"] for p in chosen}

    def _brief(p):
        return {"player_id": p["player_id"], "name": p.get("name"), "score": p["score"]}

    return {
        "xi": ordered,
        "missing_player_ids": missing,
        "total_score": total_score,
        "average_score": round(total_score / len(chosen), 1) if chosen else None,
        "counts": counts,
        "requirements": required,
        "violations": violations,
        "comparison_to_optimal": {
            "optimal_total_score": optimal_total,
            "score_gap": round(optimal_total - total_score, 1),
            "in_optimal_not_chosen": [_brief(p) for p in optimal["xi"] if p["player_id"] not in chosen_ids],
            "in_chosen_not_optimal": [_brief(p) for p in chosen if p["player_id"] not in optimal_ids],
        },
    }


def select_xi(scored_players: list[dict], settings: object = SETTINGS) -> dict:
    """scored_players: output of RecommendationScorer.score_many, dicts with
    at least player_id, score, role_bucket, is_keeper,
    batting_position_median. returns the ranked pool plus the constrained,
    team-sheet-ordered XI.

    the MILP runs over the entire candidate list, not a pre-truncated
    top-pool_size slice, since a specialist needed only for a constraint
    (most commonly the keeper) can easily score outside the top 20.
    pool_size is a display cutoff applied after the fact, the XI is always
    included in pool even if a member's score falls outside it.
    """
    if not scored_players:
        return {"xi": [], "pool": [], "method": "none", "note": "empty pool"}

    opener_threshold = settings.opener_position_threshold
    ranked = sorted(scored_players, key=lambda p: -p["score"])
    n = len(ranked)
    xi_size = min(settings.xi_size, n)
    bat_mask, bowl_mask, keeper_mask, opener_mask = _capability_masks(ranked, opener_threshold)
    min_bat = int(min(settings.min_batting_capable, bat_mask.sum()))
    min_bowl = int(min(settings.min_bowling_capable, bowl_mask.sum()))
    min_keeper = int(min(settings.min_keepers, keeper_mask.sum()))
    min_opener = int(min(settings.min_openers, opener_mask.sum()))

    scores = np.array([p["score"] for p in ranked], dtype=float)
    result = milp(
        c=-scores,
        constraints=[
            LinearConstraint(np.ones(n), xi_size, xi_size),
            LinearConstraint(bat_mask, min_bat, np.inf),
            LinearConstraint(bowl_mask, min_bowl, np.inf),
            LinearConstraint(keeper_mask, min_keeper, np.inf),
            LinearConstraint(opener_mask, min_opener, np.inf),
        ],
        bounds=Bounds(0, 1),
        integrality=np.ones(n),
    )

    if result.success:
        xi = [ranked[i] for i in range(n) if result.x[i] > 0.5]
        method = "milp"
    else:
        xi = _greedy_fallback(ranked, xi_size, min_bat, min_bowl, min_keeper, min_opener, opener_threshold)
        method = "greedy_fallback"

    xi = _team_sheet_order(xi, opener_threshold)

    display_pool = ranked[:settings.pool_size]
    display_ids = {p["player_id"] for p in display_pool}
    pool = sorted(display_pool + [p for p in xi if p["player_id"] not in display_ids],
                  key=lambda p: -p["score"])

    return {"xi": xi, "pool": pool, "method": method,
            "constraints": {"xi_size": xi_size, "min_batting_capable": min_bat,
                             "min_bowling_capable": min_bowl, "min_keepers": min_keeper,
                             "min_openers": min_opener}}

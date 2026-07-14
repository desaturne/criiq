"""Constrained playing-XI selection.

Picking the top-11 by raw score can produce an unbalanced side (e.g. 9
batters, 2 bowlers, or zero recognized openers). This formulates the pick as
a small 0/1 linear program via `scipy.optimize.milp` — maximize total score
subject to exactly `xi_size` players, with minimum batting-capable,
bowling-capable, wicket-keeper and **opener** counts — which is provably
optimal for the stated constraints, unlike ad hoc greedy-with-quotas which
can lock in a suboptimal pick early and have no way to backtrack.

The wicket-keeper constraint is soft: it's only added when the pool actually
contains a player flagged `is_keeper` (sourced from data-collection's
`player_role_final.is_keeper` — Wikipedia-verified for major nations' current
squads, see `role_finalize.py`; unset for the rest of the ~7000 players, so
requiring one for those pools would be unenforceable rather than a real
signal). The opener constraint degrades the same way if fewer than
`min_openers` players in the pool have a recorded opening batting position.

A greedy fallback is kept for the (unlikely) case `milp` fails to find a
feasible solution, e.g. too few eligible bowlers in a very thin pool.

Once the XI is selected, it's presented like an actual team sheet — see
`_team_sheet_order`: the two best-scoring openers lock in slots 1-2 (real
teams never play a third opener at 3 just because she has "opener" history;
she competes for the rest of the order on merit like anyone else), the
remaining batting-relevant players (specialist batters, all-rounders, the
keeper) fill the rest of the order by score, and specialist bowlers trail at
the tail, also ordered by score. Selection (who makes the XI) and
presentation (what order they're listed in) are different concerns — this
function only handles the latter.
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
    """"opener" / "core_batting" / "bowler_tail" — the same partition used
    both for team-sheet ordering and for finding "the next-best alternative
    in this role" when explaining a selection (see `recommend/explain.py`
    and `cli.cmd_recommend`'s `--explain`).
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
    """Order a selected XI like a real batting lineup.

    Openers: the two best-scoring opener-capable players take slots 1-2
    outright. Any *additional* opener-capable player in the XI (a squad with
    three strong openers, say) is NOT stacked into slot 3 ahead of everyone
    else just because of her tag — she drops into the same merit-ranked pool
    as the rest of the batting order, exactly matching how a real team
    actually bats a surplus opener whenever her overall output warrants a
    top-order-but-not-opening slot.

    Batting order (slots 3+): every remaining non-bowler (specialist
    batters, all-rounders, the keeper), ranked by score — an all-rounder or
    keeper who scores above a nominal "top order" player bats above her,
    which is exactly the real-world "form dictates the order" rule.

    Tail: specialist bowlers (`role_bucket == "bowler"`), ranked by score —
    the better batting bowler sits higher in the tail than a pure
    last-man specialist.

    If the XI has fewer than 2 opener-capable players (sparse batting
    position data), the best-scoring remaining batting-relevant players fill
    the gap — slots 1-2 always exist, "who opens" is never left undefined.
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
    """Splits a scored pool into the three views a coach actually thinks in
    -- batters / all-rounders / bowlers -- each independently ranked by
    score, plus an `unknown` bucket for the handful of players with no
    reliable ball-count signal to classify from. `select_xi`'s MILP already
    enforces batting/bowling-capable *minimums* under the hood (an
    all-rounder counts toward both); this is the presentation those
    constraints deserve, not a new selection mechanism -- the XI it produces
    is unchanged by this function existing.
    """
    pools = {"batters": [], "all_rounders": [], "bowlers": [], "unknown": []}
    for p in scored_players:
        key = _ROLE_POOL_KEYS.get(p.get("role_bucket"), "unknown")
        pools[key].append(p)
    for key in pools:
        pools[key] = sorted(pools[key], key=lambda p: -p["score"])
    return pools


def analyze_xi(scored_players: list[dict], player_ids: list[str],
               settings: object = SETTINGS) -> dict:
    """Scores and checks a SPECIFIC, already-chosen XI -- e.g. a coach's own
    pick from the roster -- against the identical constraints `select_xi`
    enforces, and reports how it compares to the provably-optimal pick.
    Distinct from `select_xi`, which *finds* the best XI: every real
    selector sometimes overrides the algorithm (form momentum a model can't
    see, a tactical matchup call, team chemistry), and this answers "how
    good is THIS specific XI", not "what's the best one" -- reusing the same
    scoring/constraint logic so the two are directly, fairly comparable.

    `player_ids` not found in `scored_players` (typo, retired, wrong format/
    gender scope) are reported in `missing_player_ids` rather than silently
    dropped or raising.
    """
    by_id = {p["player_id"]: p for p in scored_players}
    chosen, missing = [], []
    for pid in player_ids:
        if pid in by_id:
            chosen.append(by_id[pid])
        else:
            missing.append(pid)

    opener_threshold = settings.opener_position_threshold
    # Same soft-degradation `select_xi` applies (a requirement no player in
    # the *whole eligible pool* can satisfy -- e.g. zero recorded keepers --
    # is unenforceable, not a real violation), computed from the full pool
    # so the comparison to `select_xi`'s own XI is apples-to-apples.
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
    """`scored_players`: output of `RecommendationScorer.score_many` — dicts
    with at least `player_id`, `score`, `role_bucket`, `is_keeper`,
    `batting_position_median`. Returns the ranked pool plus the constrained,
    team-sheet-ordered XI.

    The MILP runs over the *entire* candidate list, not a pre-truncated
    top-`pool_size` slice — a specialist needed only for a constraint (most
    commonly the keeper: often the weakest all-round scorer on the team, by
    design, since a keeper's value isn't captured by the batting/bowling
    contribution model) can easily score outside the top 20 by raw score.
    Truncating before optimizing would silently zero out the very
    constraint it's there to enforce. `pool_size` is purely a *display*
    cutoff, applied after the fact — the XI is always included in `pool`
    even if a member's raw score falls outside that cutoff.
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

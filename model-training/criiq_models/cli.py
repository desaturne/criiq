from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# Windows consoles often default to a legacy codepage (cp1252 etc.), not
# UTF-8 -- without this, the em dashes explain.py's narrative sentences use
# print as "�" (confirmed in both a plain terminal and PowerShell), which
# would look broken in a live demo. Reconfiguring stdout/stderr here makes
# `--pretty`'s output render correctly regardless of the console's default
# codepage. `reconfigure` is Python 3.7+; guarded since some embedding
# contexts (e.g. certain IDE test runners) wrap stdout in a stream that
# doesn't support it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from .config import SETTINGS
from .db import connect
from .evaluate.backtest import backtest
from .evaluate.rank_backtest import rank_backtest
from .features.historical import build_training_table
from .recommend.explain import explain
from .recommend.matchup_matrix import head_to_head_matrix
from .recommend.render import render_team_sheet, render_xi_analysis
from .recommend.score import RecommendationScorer
from .recommend.strength import strength_context
from .recommend.train import load_metadata, train
from .roster import known_teams, team_pool
from .venues import resolve_venue
from .selection.optimize import analyze_xi, role_highlights, role_pools, select_xi, slot_category
from .features.common import bowling_capable
from .features.current import resolve_role
from .simulate.engine import simulate_match
from .simulate.ga_batting import optimize_batting_order
from .simulate.ga_bowling import optimize_bowling_rotation
from .simulate.keymoments import detect_key_moments
from .simulate.outcomes import build_outcome_model, build_player_profiles
from .simulate.report import (SIMULATION_ARTIFACTS_DIR, aggregate_win_probability, plot_win_probability,
                               save_simulation_artifacts)
from .simulate.scorecard import (batting_scorecard, bowling_phase_summary, bowling_rotation, bowling_scorecard,
                                  coach_perspective, render_bowling_rotation_text, render_scorecard_text)
from .simulate.winprob_reader import WinProbLookup


def _pp(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _find_player(conn, name: str):
    rows = conn.execute(
        "SELECT player_id, canonical_name FROM players "
        "WHERE canonical_name LIKE ? OR unique_name LIKE ? LIMIT 10",
        (f"%{name}%", f"%{name}%")).fetchall()
    return [dict(r) for r in rows]


def _resolve_venue_arg(conn, venue_arg: str | None) -> tuple[str | None, bool]:
    """`--venue` takes a ground *name* now, not the raw `venue_id` slug --
    resolves it here so every caller (recommend/explain) gets the same
    ambiguity handling. Returns `(venue_id, ok)`; `ok=False` means an
    ambiguous name was already reported and the caller should abort rather
    than silently score with no venue at all.
    """
    if not venue_arg:
        return None, True
    venue_id, candidates = resolve_venue(conn, venue_arg)
    if venue_id is None and candidates:
        print(f"'{venue_arg}' matches multiple grounds -- be more specific, or pass one of:")
        for c in candidates:
            print(f"  {c['canonical_name']}")
        return None, False
    return venue_id, True


def _resolve_player_name(conn, name: str) -> tuple[str | None, bool]:
    """Fuzzy name -> player_id, with the same "did you mean" ambiguity
    handling `_resolve_venue_arg` uses -- a name matching several real
    players (a genuine, previously-found issue: several distinct real
    players can share one short name) must not silently take the first
    match. Returns `(player_id, ok)`; `ok=False` means already reported.
    """
    matches = _find_player(conn, name)
    if not matches:
        print(f"no player matching {name!r}")
        return None, False
    if len(matches) > 1:
        print(f"'{name}' matches multiple players -- be more specific, or pass one of:")
        for m in matches:
            print(f"  {m['canonical_name']} ({m['player_id']})")
        return None, False
    return matches[0]["player_id"], True


def _resolve_player_list(conn, players: str | None, player_ids: str | None) -> tuple[list[str] | None, bool]:
    """Resolve a comma-separated --players (fuzzy names, with the same "did
    you mean" disambiguation) or --player-ids (raw ids) argument to a list of
    player_ids. Returns `(ids, ok)`; `ok=False` means an unresolved/ambiguous
    name was already reported. `(None, True)` when neither was given.
    """
    if players:
        out = []
        for name in players.split(","):
            pid, ok = _resolve_player_name(conn, name.strip())
            if not ok:
                return None, False
            out.append(pid)
        return out, True
    if player_ids:
        return [x.strip() for x in player_ids.split(",")], True
    return None, True


def cmd_features(args):
    conn = connect()
    table = build_training_table(conn, args.format, args.gender)
    print(f"built {len(table)} training rows "
          f"({table['date'].min()} to {table['date'].max()})" if len(table) else "no rows built")
    conn.close()


def cmd_train(args):
    conn = connect()
    metadata = train(conn, args.format, args.gender)
    _pp(metadata)
    conn.close()


def cmd_backtest(args):
    conn = connect()
    _pp(backtest(conn, args.format, args.gender))
    conn.close()


def cmd_rank_backtest(args):
    conn = connect()
    _pp(rank_backtest(conn, args.format, args.gender))
    conn.close()


def cmd_teams(args):
    conn = connect()
    _pp(known_teams(conn, args.format, args.gender))
    conn.close()


def cmd_winprob(args):
    """Win probability for a single game state, straight from data-collection's
    persisted empirical grids (`simulate.winprob_reader.WinProbLookup`) -- the
    same lookup `simulate` uses per-ball, exposed standalone so a caller (e.g.
    a live-scoring UI) can get one number without running a full match
    simulation. Mirrors the shape of the backend's `ai_stub.get_win_probability`
    stub (innings/wickets/balls_remaining/runs_required) so it's a drop-in
    real replacement.
    """
    try:
        lookup = WinProbLookup.load(args.format, args.gender)
    except FileNotFoundError as exc:
        print(str(exc))
        return
    balls_bowled = (120 - args.balls_remaining) if args.balls_remaining is not None else None
    wp = lookup.predict_one(innings=args.innings, wickets=args.wickets,
                             balls_remaining=args.balls_remaining, runs_required=args.runs_required,
                             balls_bowled=balls_bowled, score=args.score)
    balls_into_innings = 120 - args.balls_remaining if args.innings == 2 and args.balls_remaining is not None \
        else (balls_bowled or 0)
    over = balls_into_innings // 6
    phase = "powerplay" if over < 6 else ("middle" if over < 16 else "death")
    _pp({
        "win_probability_batting": wp,
        "win_probability_bowling": round(1 - wp, 4),
        "phase": phase,
        "model": f"criiq_models/winprob_{args.format}_{args.gender}",
    })


def cmd_recommend(args):
    conn = connect()
    venue_id, ok = _resolve_venue_arg(conn, args.venue)
    if not ok:
        conn.close()
        return
    pool_ids = team_pool(conn, args.team, args.format, args.gender)
    if not pool_ids:
        print(f"no eligible players found for team={args.team!r} "
              f"(format={args.format}, gender={args.gender})")
        conn.close()
        return
    # Optional: the opponent's specific XI, to counter-optimize against (matchups
    # scope to exactly those players) and to build the head-to-head matrix.
    opponent_players, ok = _resolve_player_list(conn, args.opponent_players, args.opponent_player_ids)
    if not ok:
        conn.close()
        return
    scorer = RecommendationScorer(conn, args.format, args.gender)
    scored = scorer.score_many(pool_ids, args.opponent, venue_id, opponent_players=opponent_players)
    result = select_xi(scored)

    def _brief(p):
        return {"player_id": p["player_id"], "name": p["name"], "role_bucket": p["role_bucket"],
                "is_keeper": p["is_keeper"], "batting_position_median": p["batting_position_median"],
                "score": p["score"]}

    # Best available player of each specialist batting role (finisher / power
    # hitter / anchor) across the WHOLE scored pool -- surfaces e.g. the side's
    # strongest finisher even when the win-probability rating leaves them
    # outside the headline shortlist (see selection/optimize.role_highlights).
    def _role_option(arch, p):
        inp = p["components"]["inputs"]
        detail = None
        if inp.get("bat_best_phase") and inp.get("bat_best_phase_sr") is not None:
            detail = f"best in the {inp['bat_best_phase']} (SR {inp['bat_best_phase_sr']:.0f})"
        return {"archetype": arch, "player_id": p["player_id"], "name": p["name"],
                "score": p["score"], "role_bucket": p["role_bucket"],
                "is_keeper": p["is_keeper"], "detail": detail}

    role_options = [_role_option(arch, p) for arch, p in role_highlights(scored).items()]

    # Head-to-head matrix: how the recommended XI matches up against the named
    # opposition, player by player (only when an opponent XI was supplied).
    h2h = None
    if opponent_players:
        xi_ids_for_h2h = [p["player_id"] for p in result["xi"]]
        h2h = head_to_head_matrix(conn, xi_ids_for_h2h, opponent_players, args.format)

    # Lopsided matchup: if this side is much stronger (many more ICC-ranked
    # players), flag it and offer a rotation XI that rests the top performers,
    # so the coach can see a viable bench side rather than fielding stars in a
    # mismatch. Only when *we* are the stronger side.
    sctx = strength_context(conn, args.team, args.opponent, args.format, args.gender)
    rotation_xi = None
    if sctx["lopsided"] and sctx["stronger_side"] == args.team:
        rested = sorted(scored, key=lambda p: -p["score"])[:SETTINGS.rotation_rest_count]
        rested_ids = {p["player_id"] for p in rested}
        remaining = [p for p in scored if p["player_id"] not in rested_ids]
        rot = select_xi(remaining)
        rotation_xi = {
            "rested": [{"player_id": p["player_id"], "name": p["name"], "score": p["score"]} for p in rested],
            "xi": [_brief(p) for p in rot["xi"]],
            "constraints": rot.get("constraints"),
        }

    if args.explain or args.pretty:
        xi_ids = {p["player_id"] for p in result["xi"]}
        not_selected = [p for p in scored if p["player_id"] not in xi_ids]

        def _best_alternative(category):
            same_slot = [p for p in not_selected
                         if slot_category(p, SETTINGS.opener_position_threshold) == category]
            return max(same_slot, key=lambda p: p["score"]) if same_slot else None

        xi_out = []
        for p in result["xi"]:
            category = slot_category(p, SETTINGS.opener_position_threshold)
            alt = _best_alternative(category)
            xi_out.append({**_brief(p), "reasoning": explain(p, alternative=alt, slot=category)["summary"]})

        # Top-`pool_size` recommended players, ranked by raw score -- this is
        # a *shortlist* view (no slot/alternative framing, since "picked
        # ahead of" only makes sense once the XI-constrained selection has
        # actually happened), independent of who made the final constrained
        # XI: a top-ranked keeper-less specialist can rank highly here and
        # still not make the XI if the MILP needed her slot for a keeper.
        pool_out = [{**_brief(p), "reasoning": explain(p)["summary"]} for p in result["pool"]]
    else:
        xi_out = [_brief(p) for p in result["xi"]]
        pool_out = [_brief(p) for p in result["pool"]]

    if args.pretty:
        print(render_team_sheet(args.team, args.opponent, venue_id, xi_out, pool_out,
                                 load_metadata(args.format, args.gender), result.get("constraints"),
                                 role_options=role_options, head_to_head=h2h,
                                 strength_context=sctx, rotation_xi=rotation_xi))
        conn.close()
        return

    # Same players as `pool`, grouped into the three views a coach actually
    # picks from (batting/all-rounder/bowling options) instead of one flat
    # list -- a real frontend's "pick your XI" screen reads from this
    # directly rather than re-deriving the grouping from role_bucket itself.
    pools_out = {k: [p for p in v] for k, v in role_pools(pool_out).items()}

    _pp({
        "team": args.team, "opponent": args.opponent, "venue_id": venue_id,
        "model_metadata": load_metadata(args.format, args.gender),
        "xi": xi_out,
        "pool": pool_out,
        "pools": pools_out,
        "role_options": role_options,
        "opponent_players": opponent_players,
        "head_to_head": h2h,
        "strength_context": sctx,
        "rotation_xi": rotation_xi,
        "selection_method": result["method"], "constraints": result.get("constraints"),
    })
    conn.close()


def cmd_explain(args):
    conn = connect()
    venue_id, ok = _resolve_venue_arg(conn, args.venue)
    if not ok:
        conn.close()
        return
    if args.name:
        matches = _find_player(conn, args.name)
        if not matches:
            print(f"no player matching {args.name!r}")
            conn.close()
            return
        player_id = matches[0]["player_id"]
    else:
        player_id = args.player_id
    scorer = RecommendationScorer(conn, args.format, args.gender)
    scored = scorer.score(player_id, args.opponent, venue_id)
    _pp(explain(scored))
    conn.close()


def cmd_analyze_xi(args):
    """Scores and checks a COACH'S OWN hand-picked XI -- distinct from
    `recommend`, which finds the algorithm's best one. Every real selector
    sometimes overrides the model (form momentum, a tactical call, team
    chemistry); this is the honest scorecard for that specific choice:
    her own score/reasoning for each of the 11, whether the pick satisfies
    the same batting/bowling/keeper/opener constraints `recommend`'s XI is
    held to, and exactly how it compares to the provably-optimal one.
    """
    conn = connect()
    venue_id, ok = _resolve_venue_arg(conn, args.venue)
    if not ok:
        conn.close()
        return
    pool_ids = team_pool(conn, args.team, args.format, args.gender)
    if not pool_ids:
        print(f"no eligible players found for team={args.team!r} "
              f"(format={args.format}, gender={args.gender})")
        conn.close()
        return

    if args.players:
        player_ids = []
        for name in args.players.split(","):
            pid, ok = _resolve_player_name(conn, name.strip())
            if not ok:
                conn.close()
                return
            player_ids.append(pid)
    else:
        player_ids = [x.strip() for x in args.player_ids.split(",")]

    scorer = RecommendationScorer(conn, args.format, args.gender)
    scored = scorer.score_many(pool_ids, args.opponent, venue_id)
    analysis = analyze_xi(scored, player_ids)

    # A bare player_id in this warning is nearly useless for catching a real
    # mistake (e.g. a name that fuzzy-matched to the wrong real person, or a
    # correctly-resolved player who just isn't in *this* team's pool) --
    # resolve to a name here (analyze_xi has no DB access, so it can't) so
    # the warning is actually actionable.
    if analysis["missing_player_ids"]:
        named = []
        for pid in analysis["missing_player_ids"]:
            row = conn.execute("SELECT canonical_name FROM players WHERE player_id=?", (pid,)).fetchone()
            named.append(f"{row['canonical_name']} ({pid})" if row else pid)
        analysis["missing_player_ids"] = named

    def _brief(p):
        return {"player_id": p["player_id"], "name": p["name"], "role_bucket": p["role_bucket"],
                "is_keeper": p["is_keeper"], "batting_position_median": p["batting_position_median"],
                "score": p["score"]}

    if args.explain or args.pretty:
        xi_out = [{**_brief(p), "reasoning": explain(p)["summary"]} for p in analysis["xi"]]
    else:
        xi_out = [_brief(p) for p in analysis["xi"]]

    if args.pretty:
        print(render_xi_analysis(args.team, args.opponent, venue_id, xi_out, analysis))
        conn.close()
        return

    _pp({
        "team": args.team, "opponent": args.opponent, "venue_id": venue_id,
        "xi": xi_out,
        "missing_player_ids": analysis["missing_player_ids"],
        "total_score": analysis["total_score"], "average_score": analysis["average_score"],
        "counts": analysis["counts"], "requirements": analysis["requirements"],
        "violations": analysis["violations"],
        "comparison_to_optimal": analysis["comparison_to_optimal"],
    })
    conn.close()


def _resolve_xi(conn, players_arg: str | None, player_ids_arg: str | None, label: str):
    """Resolves a literal, user-supplied 11-player XI (names or ids, in
    batting order) -- distinct from `_resolve_player_list`'s optional list,
    this requires exactly 11 and reports a specific error otherwise.
    """
    ids, ok = _resolve_player_list(conn, players_arg, player_ids_arg)
    if not ok:
        return None, False
    if not ids:
        print(f"--{label}-players/--{label}-player-ids is required (11 player names/ids, batting order)")
        return None, False
    if len(ids) != 11:
        print(f"{label}: expected exactly 11 players, got {len(ids)}")
        return None, False
    return ids, True


def _batting_groups(conn, player_ids: list, fmt: str) -> list:
    """Splits `player_ids` into role-based bands for `ga_batting.
    optimize_batting_order`'s grouped search (see that module's docstring):
    the two lowest recorded `batting_position_median` as the openers band
    (the GA can still interchange which of the two goes in first), the rest
    of the batting-relevant players (specialist batters, all-rounders, the
    keeper) as the top/middle band, and specialist bowlers (`role_bucket ==
    "bowler"`) as the tail band -- mirrors `selection/optimize.py`'s own
    `_team_sheet_order` categorization. A player with no recorded batting
    position sorts last for the opener cut, so the openers band still
    always gets exactly 2 players even with sparse position data.
    """
    rows = [(pid, *resolve_role(conn, pid, fmt)) for pid in player_ids]
    rows.sort(key=lambda r: r[3] if r[3] is not None else float("inf"))
    openers = [r[0] for r in rows[:2]]
    rest = rows[2:]
    tail = [r[0] for r in rest if r[1] == "bowler"]
    top_middle = [r[0] for r in rest if r[1] != "bowler"]
    return [g for g in (openers, top_middle, tail) if g]


def _primary_bowlers(conn, bowler_pool: list, fmt: str) -> list:
    """The up to 5 recognized specialist bowlers in `bowler_pool`
    (`role_bucket == "bowler"`) -- `ga_bowling.optimize_bowling_rotation`'s
    default assumption that these bowlers take the full quota between them.
    If fewer than 5 true specialists exist, tops up with the next-best
    bowling options (all-rounders) ranked by real bowling workload (matches
    with `balls_bowled > 0`, the same signal `career_bowl_matches` uses
    elsewhere in this repo), mirroring a real captain's forced situation
    when the side is short of frontline bowling options.
    """
    specialists, others = [], []
    for pid in bowler_pool:
        bucket, _, _ = resolve_role(conn, pid, fmt)
        (specialists if bucket == "bowler" else others).append(pid)
    if len(specialists) >= 5:
        return specialists[:5]

    def _bowl_matches(pid):
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM player_match_impact WHERE player_id=? AND format=? AND balls_bowled>0",
            (pid, fmt)).fetchone()
        return row["n"] if row else 0

    ranked_others = sorted(others, key=_bowl_matches, reverse=True)
    return specialists + ranked_others[:max(0, 5 - len(specialists))]


def _bowling_pool(conn, xi_ids: list, fmt: str) -> list:
    pool = []
    for pid in xi_ids:
        bucket, _, _ = resolve_role(conn, pid, fmt)
        if bowling_capable(bucket):
            pool.append(pid)
    return pool


def _name_map(conn, player_ids: list) -> dict:
    out = {}
    for pid in player_ids:
        row = conn.execute("SELECT canonical_name FROM players WHERE player_id=?", (pid,)).fetchone()
        out[pid] = row["canonical_name"] if row and row["canonical_name"] else pid
    return out


def _parse_force_dismissal(conn, spec: str) -> dict:
    """`"NAME_OR_ID:OVER:BALL"` -- the batter, and the (0-indexed over,
    1-indexed ball-in-over) at which they're forced out, for the "what
    happens when this player goes out here" scenario.
    """
    who, over_s, ball_s = spec.rsplit(":", 2)
    matches = _find_player(conn, who)
    player_id = matches[0]["player_id"] if len(matches) == 1 else who
    return {"player_id": player_id, "over": int(over_s), "ball": int(ball_s)}


def cmd_simulate(args):
    conn = connect()
    venue_id, ok = _resolve_venue_arg(conn, args.venue)
    if not ok:
        conn.close()
        return
    team1_ids, ok = _resolve_xi(conn, args.team1_players, args.team1_player_ids, "team1")
    if not ok:
        conn.close()
        return
    team2_ids, ok = _resolve_xi(conn, args.team2_players, args.team2_player_ids, "team2")
    if not ok:
        conn.close()
        return

    team1_bowlers = _bowling_pool(conn, team1_ids, args.format)
    team2_bowlers = _bowling_pool(conn, team2_ids, args.format)
    for label, bowlers in (("team1", team1_bowlers), ("team2", team2_bowlers)):
        if len(bowlers) < 5:
            print(f"warning: {label} has only {len(bowlers)} bowling-capable players in its XI -- "
                  f"may not be able to legally complete 20 overs (max 4 overs/bowler, no consecutive "
                  f"overs, rulebook-cricket.md sec 2)")

    try:
        outcome_model = build_outcome_model(conn, args.format, args.gender, team1_ids, team2_ids)
        winprob = WinProbLookup.load(args.format, args.gender)
    except (FileNotFoundError, ValueError) as exc:
        print(f"cannot simulate: {exc}")
        conn.close()
        return
    batter_profiles, bowler_profiles = build_player_profiles(
        conn, args.format, team1_ids, team2_ids, args.team1, args.team2, venue_id=venue_id)

    forced = _parse_force_dismissal(conn, args.force_dismissal) if args.force_dismissal else None

    team1 = {"name": args.team1, "batting_order": team1_ids, "bowling_pool": team1_bowlers}
    team2 = {"name": args.team2, "batting_order": team2_ids, "bowling_pool": team2_bowlers}
    batting_first = "team1" if args.toss_winner == args.team1 else "team2"

    try:
        reps = simulate_match(team1, team2, batting_first, outcome_model, batter_profiles, bowler_profiles,
                               winprob, n_reps=args.n_simulations, rng_seed=args.seed)
    except ValueError as exc:
        print(f"simulation failed: {exc}")
        conn.close()
        return

    names = _name_map(conn, team1_ids + team2_ids)
    representative = reps[0]
    combined_log = pd.concat([representative["first_innings_log"], representative["second_innings_log"]],
                              ignore_index=True)
    key_moments = detect_key_moments(combined_log, name_map=names)

    if args.json:
        first_bat = batting_scorecard(representative["first_innings_log"], names)
        first_bowl = bowling_scorecard(representative["first_innings_log"], names)
        second_bat = batting_scorecard(representative["second_innings_log"], names)
        second_bowl = bowling_scorecard(representative["second_innings_log"], names)
        first_rotation = bowling_rotation(representative["first_innings_log"], names)
        second_rotation = bowling_rotation(representative["second_innings_log"], names)

        scenario_out = None
        if forced:
            try:
                scenario_reps = simulate_match(team1, team2, batting_first, outcome_model, batter_profiles,
                                                bowler_profiles, winprob, forced_dismissal=forced,
                                                n_reps=args.n_simulations, rng_seed=args.seed)
                scenario_rep = scenario_reps[0]
                scenario_out = {
                    "forced_dismissal": forced,
                    "first_innings_score": scenario_rep["first_innings_score"],
                    "first_innings_wickets": scenario_rep["first_innings_wickets"],
                    "second_innings_score": scenario_rep["second_innings_score"],
                    "second_innings_wickets": scenario_rep["second_innings_wickets"],
                    "winner": scenario_rep["winner"],
                }
            except ValueError as exc:
                scenario_out = {"error": str(exc)}

        win_probability_pct = None
        win_prob_timeline = None
        if len(reps) > 1:
            win_counts = pd.Series([r["winner"] for r in reps]).value_counts(normalize=True) * 100
            win_probability_pct = {k: round(v, 1) for k, v in win_counts.items()}
            win_prob_timeline = aggregate_win_probability(reps).to_dict(orient="records")

        _pp({
            "team1": team1["name"], "team2": team2["name"],
            "batting_first_team": representative["batting_first_team"],
            "bowling_first_team": representative["bowling_first_team"],
            "first_innings": {"team": representative["batting_first_team"],
                               "score": representative["first_innings_score"],
                               "wickets": representative["first_innings_wickets"]},
            "second_innings": {"team": representative["bowling_first_team"],
                                "score": representative["second_innings_score"],
                                "wickets": representative["second_innings_wickets"],
                                "target": representative["target"]},
            "winner": representative["winner"],
            "super_over_rounds": representative.get("super_over_rounds"),
            "n_simulations": args.n_simulations,
            "win_probability_pct": win_probability_pct,
            "win_prob_timeline": win_prob_timeline,
            "key_moments": key_moments,
            "first_innings_scorecard": {"batting": first_bat, "bowling": first_bowl},
            "second_innings_scorecard": {"batting": second_bat, "bowling": second_bowl},
            "first_innings_bowling_rotation": {"overs": first_rotation,
                                                "phase_summary": bowling_phase_summary(first_rotation)},
            "second_innings_bowling_rotation": {"overs": second_rotation,
                                                 "phase_summary": bowling_phase_summary(second_rotation)},
            "scenario": scenario_out,
        })
        conn.close()
        return

    print(f"{team1['name']} vs {team2['name']} -- {args.n_simulations} simulation(s)")
    print(f"  {representative['batting_first_team']}: {representative['first_innings_score']}/"
          f"{representative['first_innings_wickets']}")
    print(f"  {representative['bowling_first_team']}: {representative['second_innings_score']}/"
          f"{representative['second_innings_wickets']} (target {representative['target']})")
    if representative["second_innings_score"] == representative["target"] - 1:
        print(f"  scores level -- tied, resolved by Super Over(s):")
        for i, so in enumerate(representative["super_over_rounds"], 1):
            print(f"    super over {i}: {so['bat_first_team']} {so['bat_first_score']}/{so['bat_first_wickets']} "
                  f"vs {so['bowl_first_team']} {so['bowl_first_score']}/{so['bowl_first_wickets']} "
                  f"-> {so['winner']}")
    print(f"  winner: {representative['winner']}")
    if len(reps) > 1:
        win_counts = pd.Series([r["winner"] for r in reps]).value_counts(normalize=True) * 100
        print(f"  win probability across {len(reps)} simulations: "
              + ", ".join(f"{k} {v:.1f}%" for k, v in win_counts.items()))
    print("\n  key moments:")
    for m in key_moments:
        print(f"    inn{m['innings']} {m['over']}.{m['ball']} -- {m['description']}")

    coach_team = args.coach_team or args.team1
    print(f"\n{'=' * 60}\nCOACH'S PERSPECTIVE -- {coach_team}\n{'=' * 60}")
    print(coach_perspective(representative, key_moments, coach_team, name_map=names))

    print(f"\n{'=' * 60}\nSCORECARD\n{'=' * 60}\n")
    first_bat = batting_scorecard(representative["first_innings_log"], names)
    first_bowl = bowling_scorecard(representative["first_innings_log"], names)
    print(render_scorecard_text(representative["batting_first_team"], first_bat, first_bowl,
                                 representative["bowling_first_team"]))

    print()
    second_bat = batting_scorecard(representative["second_innings_log"], names)
    second_bowl = bowling_scorecard(representative["second_innings_log"], names)
    print(render_scorecard_text(representative["bowling_first_team"], second_bat, second_bowl,
                                 representative["batting_first_team"]))

    print(f"\n{'=' * 60}\nBOWLING ROTATION -- who bowled each over, and each phase\n{'=' * 60}\n")
    first_rotation = bowling_rotation(representative["first_innings_log"], names)
    print(render_bowling_rotation_text(representative["bowling_first_team"], first_rotation,
                                        bowling_phase_summary(first_rotation)))
    print()
    second_rotation = bowling_rotation(representative["second_innings_log"], names)
    print(render_bowling_rotation_text(representative["batting_first_team"], second_rotation,
                                        bowling_phase_summary(second_rotation)))

    scenario_rep = None
    if forced:
        try:
            scenario_reps = simulate_match(team1, team2, batting_first, outcome_model, batter_profiles,
                                            bowler_profiles, winprob, forced_dismissal=forced,
                                            n_reps=args.n_simulations, rng_seed=args.seed)
            scenario_rep = scenario_reps[0]
            print(f"\n  scenario ({names.get(forced['player_id'], forced['player_id'])} forced out at "
                  f"over {forced['over']} ball {forced['ball']}):")
            print(f"    {scenario_rep['batting_first_team']}: {scenario_rep['first_innings_score']}/"
                  f"{scenario_rep['first_innings_wickets']}")
            print(f"    {scenario_rep['bowling_first_team']}: {scenario_rep['second_innings_score']}/"
                  f"{scenario_rep['second_innings_wickets']}, winner: {scenario_rep['winner']}")
        except ValueError as exc:
            print(f"  scenario simulation failed: {exc}")

    out_dir = Path(args.out_dir)
    plot_path = plot_win_probability(representative, out_dir / "win_probability.png",
                                      scenario_rep=scenario_rep, key_moments=key_moments)
    artifact_paths = save_simulation_artifacts(representative, out_dir, key_moments=key_moments)
    print(f"\n  chart: {plot_path}")
    print(f"  artifacts: {artifact_paths['ball_log_path']}, {artifact_paths['summary_path']}")
    conn.close()


def cmd_optimize_bowling(args):
    conn = connect()
    venue_id, ok = _resolve_venue_arg(conn, args.venue)
    if not ok:
        conn.close()
        return
    bowling_ids, ok = _resolve_xi(conn, args.bowling_players, args.bowling_player_ids, "bowling-team")
    if not ok:
        conn.close()
        return
    batting_ids, ok = _resolve_xi(conn, args.batting_players, args.batting_player_ids, "batting-team")
    if not ok:
        conn.close()
        return

    bowler_pool = _bowling_pool(conn, bowling_ids, args.format)
    if len(bowler_pool) < 5:
        print(f"bowling team has only {len(bowler_pool)} bowling-capable players -- "
              f"need at least 5 to legally bowl 20 overs (max 4 each)")
        conn.close()
        return

    try:
        outcome_model = build_outcome_model(conn, args.format, args.gender, bowling_ids, batting_ids)
    except ValueError as exc:
        print(f"cannot optimize: {exc}")
        conn.close()
        return
    batter_profiles, bowler_profiles = build_player_profiles(
        conn, args.format, bowling_ids, batting_ids, args.bowling_team, args.batting_team, venue_id=venue_id)

    primary_bowlers = None if args.no_primary_bowlers else _primary_bowlers(conn, bowler_pool, args.format)
    try:
        result = optimize_bowling_rotation(bowler_pool, batting_ids, outcome_model, batter_profiles,
                                            bowler_profiles, primary_bowlers=primary_bowlers,
                                            pop_size=args.pop_size,
                                            generations=args.generations, rng_seed=args.seed)
    except ValueError as exc:
        print(f"optimization failed: {exc}")
        conn.close()
        return

    names = _name_map(conn, bowling_ids + batting_ids)

    if args.json:
        _pp({
            "bowling_team": args.bowling_team, "batting_team": args.batting_team,
            "rotation": [{"over": i + 1, "player_id": b, "name": names.get(b, b)}
                         for i, b in enumerate(result["rotation"])],
            "overs_per_bowler": [{"player_id": b, "name": names.get(b, b), "overs": n}
                                  for b, n in result["overs_per_bowler"].items()],
            "expected_runs_conceded": result["expected_runs_conceded"],
            "primary_bowlers": [{"player_id": b, "name": names.get(b, b)} for b in (primary_bowlers or [])],
            "fitness_history": result.get("fitness_history"),
        })
        conn.close()
        return

    if primary_bowlers:
        print(f"recognized bowlers (default full quota): {[names.get(b, b) for b in primary_bowlers]}")
    print(f"best bowling rotation vs {args.batting_team} "
          f"(expected runs conceded: {result['expected_runs_conceded']}):")
    for i, bowler in enumerate(result["rotation"]):
        print(f"  over {i + 1:2d}: {names.get(bowler, bowler)}")
    print("overs per bowler:", {names.get(b, b): n for b, n in result["overs_per_bowler"].items()})

    out_path = Path(args.out_dir) / "bowling_rotation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"saved: {out_path}")
    conn.close()


def cmd_optimize_batting(args):
    conn = connect()
    venue_id, ok = _resolve_venue_arg(conn, args.venue)
    if not ok:
        conn.close()
        return
    batting_ids, ok = _resolve_xi(conn, args.batting_players, args.batting_player_ids, "batting-team")
    if not ok:
        conn.close()
        return
    bowling_ids, ok = _resolve_xi(conn, args.bowling_players, args.bowling_player_ids, "bowling-team")
    if not ok:
        conn.close()
        return

    bowler_pool = _bowling_pool(conn, bowling_ids, args.format)
    if len(bowler_pool) < 5:
        print(f"opposition has only {len(bowler_pool)} bowling-capable players -- "
              f"need at least 5 to legally bowl 20 overs (max 4 each)")
        conn.close()
        return

    try:
        outcome_model = build_outcome_model(conn, args.format, args.gender, batting_ids, bowling_ids)
    except ValueError as exc:
        print(f"cannot optimize: {exc}")
        conn.close()
        return
    batter_profiles, bowler_profiles = build_player_profiles(
        conn, args.format, batting_ids, bowling_ids, args.batting_team, args.bowling_team, venue_id=venue_id)

    batting_groups = [batting_ids] if args.no_role_bands else _batting_groups(conn, batting_ids, args.format)
    result = optimize_batting_order(batting_groups, bowler_pool, outcome_model, batter_profiles, bowler_profiles,
                                     target=args.target, pop_size=args.pop_size,
                                     generations=args.generations, rng_seed=args.seed)

    names = _name_map(conn, batting_ids + bowling_ids)
    metric_name = "win_probability" if args.target else "expected_score"

    if args.json:
        _pp({
            "batting_team": args.batting_team, "bowling_team": args.bowling_team,
            "batting_order": [{"position": i + 1, "player_id": pid, "name": names.get(pid, pid)}
                               for i, pid in enumerate(result["batting_order"])],
            "metric_name": metric_name, "metric_value": result[metric_name],
            "target": args.target,
            "batting_groups": None if args.no_role_bands else [
                {"label": label, "player_ids": [{"player_id": p, "name": names.get(p, p)} for p in group]}
                for label, group in zip(["openers", "top/middle order", "tail"], batting_groups)
            ],
            "fitness_history": result.get("fitness_history"),
        })
        conn.close()
        return

    if not args.no_role_bands:
        band_names = ["openers", "top/middle order", "tail"]
        for label, group in zip(band_names, batting_groups):
            print(f"{label}: {[names.get(p, p) for p in group]}")
    print(f"best batting order vs {args.bowling_team} ({metric_name}: {result[metric_name]}):")
    for i, pid in enumerate(result["batting_order"]):
        print(f"  {i + 1:2d}. {names.get(pid, pid)}")

    out_path = Path(args.out_dir) / "batting_order.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"saved: {out_path}")
    conn.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="criiq_models")
    sub = p.add_subparsers(required=True)

    f = sub.add_parser("features", help="build + report the leakage-safe training feature table")
    f.add_argument("--format", default=SETTINGS.format)
    f.add_argument("--gender", default=SETTINGS.gender)
    f.set_defaults(func=cmd_features)

    t = sub.add_parser("train", help="fit + persist the contribution regressors")
    t.add_argument("--format", default=SETTINGS.format)
    t.add_argument("--gender", default=SETTINGS.gender)
    t.set_defaults(func=cmd_train)

    b = sub.add_parser("backtest", help="temporal holdout calibration report")
    b.add_argument("--format", default=SETTINGS.format)
    b.add_argument("--gender", default=SETTINGS.gender)
    b.set_defaults(func=cmd_backtest)

    rb = sub.add_parser("rank-backtest", help="learning-to-rank vs regression-based ranking comparison")
    rb.add_argument("--format", default=SETTINGS.format)
    rb.add_argument("--gender", default=SETTINGS.gender)
    rb.set_defaults(func=cmd_rank_backtest)

    tm = sub.add_parser("teams", help="list known team names")
    tm.add_argument("--format", default=SETTINGS.format)
    tm.add_argument("--gender", default=SETTINGS.gender)
    tm.set_defaults(func=cmd_teams)

    r = sub.add_parser("recommend", help="ranked pool + constrained playing XI")
    r.add_argument("--team", required=True)
    r.add_argument("--opponent", required=True)
    r.add_argument("--venue", default=None)
    r.add_argument("--format", default=SETTINGS.format)
    r.add_argument("--gender", default=SETTINGS.gender)
    r.add_argument("--explain", action="store_true",
                    help="include per-player plain-language reasoning for the XI")
    r.add_argument("--pretty", action="store_true",
                    help="render a human-readable team sheet instead of JSON (implies --explain)")
    r.add_argument("--opponent-players", dest="opponent_players",
                    help="the opponent's specific XI (comma-separated names) to counter-optimize "
                         "against and build a head-to-head matrix for, e.g. \"V Kohli,RG Sharma,...\"")
    r.add_argument("--opponent-player-ids", dest="opponent_player_ids",
                    help="opponent XI as comma-separated player_ids (alternative to --opponent-players)")
    r.set_defaults(func=cmd_recommend)

    e = sub.add_parser("explain", help="component breakdown for one player")
    e.add_argument("--player-id", dest="player_id")
    e.add_argument("--name", help="fuzzy name lookup instead of --player-id")
    e.add_argument("--opponent", required=True)
    e.add_argument("--venue", default=None)
    e.add_argument("--format", default=SETTINGS.format)
    e.add_argument("--gender", default=SETTINGS.gender)
    e.set_defaults(func=cmd_explain)

    a = sub.add_parser("analyze-xi", help="score + check a coach's own hand-picked XI against the same "
                                           "constraints and the AI's optimal pick")
    a.add_argument("--team", required=True)
    a.add_argument("--opponent", required=True)
    a.add_argument("--venue", default=None)
    a.add_argument("--format", default=SETTINGS.format)
    a.add_argument("--gender", default=SETTINGS.gender)
    a.add_argument("--players", help="comma-separated player names, e.g. \"S Mandhana,H Kaur,...\"")
    a.add_argument("--player-ids", dest="player_ids", help="comma-separated player_ids (alternative to --players)")
    a.add_argument("--explain", action="store_true",
                    help="include per-player plain-language reasoning")
    a.add_argument("--pretty", action="store_true",
                    help="render a human-readable analysis instead of JSON (implies --explain)")
    a.set_defaults(func=cmd_analyze_xi)

    s = sub.add_parser("simulate", help="ball-by-ball Monte Carlo match simulation, win-probability "
                                         "chart + key moments, optional 'player goes out' scenario")
    s.add_argument("--team1", required=True, help="team1's display name (used as a label, and to resolve "
                                                    "--toss-winner)")
    s.add_argument("--team2", required=True)
    s.add_argument("--team1-players", dest="team1_players",
                    help="team1's exact Playing XI, comma-separated names, in batting order")
    s.add_argument("--team1-player-ids", dest="team1_player_ids",
                    help="team1's exact Playing XI as comma-separated player_ids (alternative to --team1-players)")
    s.add_argument("--team2-players", dest="team2_players")
    s.add_argument("--team2-player-ids", dest="team2_player_ids")
    s.add_argument("--toss-winner", dest="toss_winner", required=True,
                    help="name of the team that won the toss and elects to bat first (must equal --team1 "
                         "or --team2)")
    s.add_argument("--venue", default=None,
                    help="ground name -- conditions the batters' setting/chasing strike rate "
                         "(player_by_venue), shrunk toward their overall rate by real matches there")
    s.add_argument("--format", default=SETTINGS.format)
    s.add_argument("--gender", default=SETTINGS.gender)
    s.add_argument("--n-simulations", dest="n_simulations", type=int, default=100)
    s.add_argument("--seed", type=int, default=None,
                    help="RNG seed -- omit for a genuinely different Monte Carlo draw every run "
                         "(the default); pass a fixed integer only if you specifically want the exact "
                         "same simulated match reproduced again")
    s.add_argument("--force-dismissal", dest="force_dismissal", default=None,
                    help="\"NAME_OR_ID:OVER:BALL\" -- simulate this batter forced out at that point "
                         "(0-indexed over, 1-indexed ball), alongside the baseline")
    s.add_argument("--coach-team", dest="coach_team", default=None,
                    help="which side to narrate the match from (must equal --team1 or --team2); "
                         "defaults to --team1")
    s.add_argument("--out-dir", dest="out_dir", default=str(SIMULATION_ARTIFACTS_DIR / "latest"))
    s.add_argument("--json", action="store_true",
                    help="print one structured JSON result (scores, scorecards, bowling rotation, key "
                         "moments, win-probability timeline) instead of the human-readable report; skips "
                         "the chart/artifact files since a caller consuming JSON reads the timeline directly")
    s.set_defaults(func=cmd_simulate)

    ob = sub.add_parser("optimize-bowling", help="genetic-algorithm search over legal bowler-to-over "
                                                  "rotations to minimize the opposition's expected runs")
    ob.add_argument("--bowling-team", dest="bowling_team", required=True)
    ob.add_argument("--batting-team", dest="batting_team", required=True, help="the opposition")
    ob.add_argument("--bowling-players", dest="bowling_players")
    ob.add_argument("--bowling-player-ids", dest="bowling_player_ids")
    ob.add_argument("--batting-players", dest="batting_players")
    ob.add_argument("--batting-player-ids", dest="batting_player_ids")
    ob.add_argument("--venue", default=None,
                     help="ground name -- conditions batters' setting/chasing strike rate at this ground")
    ob.add_argument("--format", default=SETTINGS.format)
    ob.add_argument("--gender", default=SETTINGS.gender)
    ob.add_argument("--pop-size", dest="pop_size", type=int, default=40)
    ob.add_argument("--generations", type=int, default=60)
    ob.add_argument("--no-primary-bowlers", dest="no_primary_bowlers", action="store_true",
                     help="search overs freely across every bowling-capable player (default: the up to 5 "
                          "recognized specialist bowlers take the full 4-over quota between them by default, "
                          "same as a real captain would, with others introduced only occasionally or when "
                          "forced -- see optimize_bowling_rotation's primary_bowlers docstring)")
    ob.add_argument("--seed", type=int, default=None,
                     help="RNG seed -- omit for a genuinely different GA search every run (the default); "
                          "pass a fixed integer to reproduce the exact same run again")
    ob.add_argument("--out-dir", dest="out_dir", default=str(SIMULATION_ARTIFACTS_DIR / "latest"))
    ob.add_argument("--json", action="store_true",
                     help="print the rotation result as structured JSON instead of the human-readable "
                          "report; skips writing bowling_rotation.json to --out-dir")
    ob.set_defaults(func=cmd_optimize_bowling)

    obat = sub.add_parser("optimize-batting", help="genetic-algorithm search over the batting order to "
                                                     "maximize expected score (or chase win probability, "
                                                     "with --target)")
    obat.add_argument("--batting-team", dest="batting_team", required=True)
    obat.add_argument("--bowling-team", dest="bowling_team", required=True, help="the opposition")
    obat.add_argument("--batting-players", dest="batting_players")
    obat.add_argument("--batting-player-ids", dest="batting_player_ids")
    obat.add_argument("--bowling-players", dest="bowling_players")
    obat.add_argument("--bowling-player-ids", dest="bowling_player_ids")
    obat.add_argument("--target", type=int, default=None,
                       help="chase target -- optimizes win probability of reaching it instead of raw score")
    obat.add_argument("--no-role-bands", dest="no_role_bands", action="store_true",
                       help="search the full batting order freely, ignoring role (default: the order is "
                            "searched in three bands -- openers, top/middle order, tail -- each independently "
                            "permuted but never crossing band boundaries; see ga_batting.py's batting_groups "
                            "docstring)")
    obat.add_argument("--venue", default=None,
                       help="ground name -- conditions batters' setting/chasing strike rate at this ground")
    obat.add_argument("--format", default=SETTINGS.format)
    obat.add_argument("--gender", default=SETTINGS.gender)
    obat.add_argument("--pop-size", dest="pop_size", type=int, default=40)
    obat.add_argument("--generations", type=int, default=60)
    obat.add_argument("--seed", type=int, default=None,
                       help="RNG seed -- omit for a genuinely different GA search every run (the default); "
                            "pass a fixed integer to reproduce the exact same run again")
    obat.add_argument("--out-dir", dest="out_dir", default=str(SIMULATION_ARTIFACTS_DIR / "latest"))
    obat.add_argument("--json", action="store_true",
                       help="print the batting order result as structured JSON instead of the "
                            "human-readable report; skips writing batting_order.json to --out-dir")
    obat.set_defaults(func=cmd_optimize_batting)

    wp = sub.add_parser("winprob", help="win probability for a single game state, from the persisted "
                                         "empirical grids (fast -- no match simulation)")
    wp.add_argument("--innings", type=int, required=True, choices=[1, 2])
    wp.add_argument("--wickets", type=int, default=0)
    wp.add_argument("--balls-remaining", dest="balls_remaining", type=int, default=None,
                     help="balls left in the innings (second innings: balls left to chase in; "
                          "first innings: used to derive balls bowled so far)")
    wp.add_argument("--runs-required", dest="runs_required", type=int, default=None,
                     help="second innings only -- runs still needed to win")
    wp.add_argument("--score", type=int, default=None,
                     help="first innings only -- current score, for a more precise lookup")
    wp.add_argument("--format", default=SETTINGS.format)
    wp.add_argument("--gender", default=SETTINGS.gender)
    wp.set_defaults(func=cmd_winprob)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

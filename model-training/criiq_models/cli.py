from __future__ import annotations

import argparse
import json
import sys

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
from .recommend.render import render_team_sheet, render_xi_analysis
from .recommend.score import RecommendationScorer
from .recommend.train import load_metadata, train
from .roster import known_teams, team_pool
from .venues import resolve_venue
from .selection.optimize import analyze_xi, role_highlights, role_pools, select_xi, slot_category


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
    scorer = RecommendationScorer(conn, args.format, args.gender)
    scored = scorer.score_many(pool_ids, args.opponent, venue_id)
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
                                 role_options=role_options))
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

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

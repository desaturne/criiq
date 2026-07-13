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
from .recommend.render import render_team_sheet
from .recommend.score import RecommendationScorer
from .recommend.train import load_metadata, train
from .roster import known_teams, team_pool
from .selection.optimize import select_xi, slot_category


def _pp(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _find_player(conn, name: str):
    rows = conn.execute(
        "SELECT player_id, canonical_name FROM players "
        "WHERE canonical_name LIKE ? OR unique_name LIKE ? LIMIT 10",
        (f"%{name}%", f"%{name}%")).fetchall()
    return [dict(r) for r in rows]


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
    pool_ids = team_pool(conn, args.team, args.format, args.gender)
    if not pool_ids:
        print(f"no eligible players found for team={args.team!r} "
              f"(format={args.format}, gender={args.gender})")
        conn.close()
        return
    scorer = RecommendationScorer(conn, args.format, args.gender)
    scored = scorer.score_many(pool_ids, args.opponent, args.venue)
    result = select_xi(scored)

    def _brief(p):
        return {"player_id": p["player_id"], "name": p["name"], "role_bucket": p["role_bucket"],
                "is_keeper": p["is_keeper"], "batting_position_median": p["batting_position_median"],
                "score": p["score"]}

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
        print(render_team_sheet(args.team, args.opponent, args.venue, xi_out, pool_out,
                                 load_metadata(), result.get("constraints")))
        conn.close()
        return

    _pp({
        "team": args.team, "opponent": args.opponent, "venue_id": args.venue,
        "model_metadata": load_metadata(),
        "xi": xi_out,
        "pool": pool_out,
        "selection_method": result["method"], "constraints": result.get("constraints"),
    })
    conn.close()


def cmd_explain(args):
    conn = connect()
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
    scored = scorer.score(player_id, args.opponent, args.venue)
    _pp(explain(scored))
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

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

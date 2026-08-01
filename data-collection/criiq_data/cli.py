from __future__ import annotations

import argparse
import json

from . import advanced, career, download_cricsheet, download_register, identity, impact
from . import ingest, matchups, ml_features, opponents, overrides, phases, player_card
from . import rankings, refresh, registry, role_finalize, rss_monitor, scrape_cricinfo, sheet, styles
from . import venue_stats, winprob, wpa
from .db import connect, get_meta, init_schema, table_count
from .h2h import batter_vs_bowler, names_for_player
from .logging_utils import get_logger

log = get_logger("cli")


def _pp(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _find_player(conn, name: str):
    rows = conn.execute(
        "SELECT player_id, canonical_name, cricsheet_identifier FROM players "
        "WHERE canonical_name LIKE ? OR unique_name LIKE ? LIMIT 10",
        (f"%{name}%", f"%{name}%")).fetchall()
    return [dict(r) for r in rows]


def cmd_init(args):
    conn = connect(); init_schema(conn); conn.close()
    print("schema initialised")


def cmd_download(args):
    conn = connect(); init_schema(conn)
    _pp({"register": download_register.download_register(conn),
         "cricsheet": download_cricsheet.download_all(conn, force=args.force)})
    conn.close()


def cmd_ingest(args):
    conn = connect(); init_schema(conn)
    _pp(ingest.ingest_all(conn)); conn.close()


def cmd_identity(args):
    conn = connect(); init_schema(conn)
    _pp(identity.run(conn)); conn.close()


def cmd_registry(args):
    conn = connect(); init_schema(conn)
    _pp(registry.build_registry(conn)); conn.close()


def cmd_cards(args):
    conn = connect(); init_schema(conn)
    _pp(player_card.build_cards(conn)); conn.close()


def cmd_enrich(args):
    conn = connect(); init_schema(conn)
    _pp(scrape_cricinfo.enrich_players(conn, limit=args.limit, refetch=args.refetch))
    conn.close()


def cmd_rss(args):
    conn = connect(); init_schema(conn)
    _pp(rss_monitor.scan_feeds(conn)); conn.close()


def cmd_alerts(args):
    conn = connect(); init_schema(conn)
    if args.confirm:
        ok = rss_monitor.set_alert_status(conn, args.confirm, "CONFIRMED")
        print("confirmed" if ok else "not found")
    elif args.dismiss:
        ok = rss_monitor.set_alert_status(conn, args.dismiss, "DISMISSED")
        print("dismissed" if ok else "not found")
    else:
        _pp(rss_monitor.list_alerts(conn))
    conn.close()


def cmd_career(args):
    conn = connect(); init_schema(conn)
    _pp(career.build_career(conn)); conn.close()


def cmd_advanced(args):
    conn = connect(); init_schema(conn)
    _pp(advanced.build_advanced(conn)); conn.close()


def cmd_opponents(args):
    conn = connect(); init_schema(conn)
    _pp(opponents.build_vs_opponent(conn)); conn.close()


def cmd_impact(args):
    conn = connect(); init_schema(conn)
    _pp(impact.build_impact(conn)); conn.close()


def cmd_venues(args):
    conn = connect(); init_schema(conn)
    _pp(venue_stats.build_venue_stats(conn)); conn.close()


def cmd_matchups(args):
    conn = connect(); init_schema(conn)
    _pp(matchups.build_matchups(conn)); conn.close()


def cmd_phases(args):
    conn = connect(); init_schema(conn)
    _pp(phases.build_phases(conn)); conn.close()


def cmd_role_finalize(args):
    conn = connect(); init_schema(conn)
    if args.load_external:
        records = role_finalize.load_external_roles_csv(args.load_external)
        _pp(role_finalize.merge_external_roles(conn, records, args.format))
    else:
        _pp(role_finalize.finalize_all_local(conn))
    conn.close()


def cmd_ml(args):
    conn = connect(); init_schema(conn)
    _pp(ml_features.build_all(conn)); conn.close()


def cmd_wpa(args):
    conn = connect(); init_schema(conn)
    _pp(wpa.build_wpa(conn)); conn.close()


def cmd_winprob(args):
    conn = connect(); init_schema(conn)
    if args.state:
        # e.g. --state "innings=2,balls_remaining=30,wickets=4,runs_required=40"
        allowed = {"innings", "wickets", "balls_remaining", "runs_required",
                   "balls_bowled", "score"}
        required = {"innings", "wickets"}
        kv = {}
        for part in args.state.split(","):
            k, _, v = part.partition("=")
            k, v = k.strip(), v.strip()
            if k not in allowed:
                raise SystemExit(f"--state: unknown key '{k}' (allowed: {sorted(allowed)})")
            try:
                kv[k] = int(v)
            except ValueError:
                raise SystemExit(f"--state: '{k}' must be an integer, got '{v}'")
        missing = required - kv.keys()
        if missing:
            raise SystemExit(f"--state: missing required key(s): {sorted(missing)}")
        wp = winprob.probability_for_state(args.format, args.gender, **kv)
        _pp({"format": args.format, "gender": args.gender, "state": kv,
             "win_prob_batting": wp, "win_prob_bowling": round(1 - wp, 4)})
    elif args.match:
        tl = winprob.match_timeline(args.format, args.match)
        if tl.empty:
            print(f"no win-probability rows for match {args.match} "
                  f"(run `winprob` to build the model first)")
        else:
            print(f"win probability timeline - match {args.match} ({args.format})")
            print(f"{'inn':>3} {'ov':>3} {'phase':<10} {'bat team':<18} "
                  f"{'score':>7} {'wk':>2} {'need':>5} {'WP%':>5}")
            for r in tl.itertuples(index=False):
                need = "" if r.runs_required is None or r.runs_required != r.runs_required else int(r.runs_required)
                print(f"{r.innings:>3} {r.over + 1:>3} {r.phase:<10} {str(r.batting_team)[:18]:<18} "
                      f"{int(r.score):>7} {int(r.wickets):>2} {str(need):>5} "
                      f"{round(100 * r.win_prob_batting):>5}")
    else:
        _pp(winprob.build_winprob(conn))
    conn.close()


def cmd_rankings(args):
    conn = connect(); init_schema(conn)
    if args.scaffold:
        print("template written:", rankings.scaffold_csv())
    else:
        loaded = rankings.load_live(conn) if args.fetch else rankings.load(conn)
        rebuilt = {
            "registry": registry.build_registry(conn),
            "cards": player_card.build_cards(conn),
        }
        _pp({"rankings": loaded, "rebuilt": rebuilt})
    conn.close()


def cmd_status_override(args):
    conn = connect(); init_schema(conn)
    if args.scaffold:
        print("template written:", overrides.scaffold_csv())
    else:
        _pp(overrides.load_csv(conn))
    conn.close()


def cmd_sheet(args):
    conn = connect(); init_schema(conn)
    row = sheet.find_player(conn, args.name)
    if not row:
        print(f"no player matching '{args.name}'"); conn.close(); return
    _pp(sheet.get_sheet(conn, row["player_id"], args.format,
                        top_opponents=args.opponents))
    conn.close()


def cmd_styles(args):
    conn = connect(); init_schema(conn)
    if args.scaffold:
        path = styles.scaffold_csv(conn, only_missing=not args.all)
        print(f"template written: {path}")
    elif args.seed:
        _pp(styles.seed_from_wikidata(conn, limit=args.limit))
    elif args.wiki:
        _pp(styles.enrich_from_wikipedia(conn, limit=args.limit))
    elif args.load:
        _pp(styles.load_manual_csv(conn))
    else:
        _pp(styles.coverage(conn))
    conn.close()


def cmd_profile(args):
    conn = connect(); init_schema(conn)
    matches = _find_player(conn, args.name)
    if not matches:
        print(f"no player matching '{args.name}'"); conn.close(); return
    if len(matches) > 1 and not args.first:
        print("multiple matches — narrow the name or pass --first:")
        _pp(matches); conn.close(); return
    prof = advanced.get_advanced(conn, matches[0]["player_id"], args.format)
    _pp(prof or {"error": "no advanced profile for that player/format",
                 "player": matches[0]})
    conn.close()


def cmd_refresh(args):
    _pp(refresh.run(force_download=args.force, enrich=args.enrich,
                    scan_rss=not args.no_rss, seed_styles=args.seed_styles))


def cmd_status(args):
    conn = connect(); init_schema(conn)
    out = {t: table_count(conn, t) for t in
           ["matches", "deliveries", "players", "player_registry",
            "player_career", "player_cards", "player_advanced",
            "player_vs_opponent", "player_impact", "player_by_venue",
            "dismissal_matchup", "player_phase", "match_features",
            "player_match_impact", "icc_rankings", "retirement_alerts"]}
    out["retirement_status_breakdown"] = {r["retirement_status"]: r["n"] for r in conn.execute(
        "SELECT retirement_status, COUNT(*) n FROM player_registry GROUP BY retirement_status")}
    out["age_advisory_flagged"] = conn.execute(
        "SELECT COUNT(*) n FROM player_registry WHERE age_advisory=1").fetchone()["n"]
    out["styles_coverage"] = styles.coverage(conn)
    out["players_with_cricinfo"] = conn.execute(
        "SELECT COUNT(*) n FROM players WHERE key_cricinfo IS NOT NULL "
        "AND key_cricinfo != ''").fetchone()["n"]
    out["players_need_review"] = conn.execute(
        "SELECT COUNT(*) n FROM players WHERE needs_review=1").fetchone()["n"]
    out["freshness"] = refresh.freshness(conn)
    out["last_refresh"] = get_meta(conn, "last_successful_refresh")
    _pp(out); conn.close()


def cmd_card(args):
    conn = connect(); init_schema(conn)
    matches = _find_player(conn, args.name)
    if not matches:
        print(f"no player matching '{args.name}'"); conn.close(); return
    if len(matches) > 1 and not args.first:
        print("multiple matches — narrow the name or pass --first:")
        _pp(matches); conn.close(); return
    pid = matches[0]["player_id"]
    card = player_card.get_card(conn, pid, args.format)
    _pp(card or {"error": "no card for that player/format",
                 "player": matches[0]})
    conn.close()


def cmd_h2h(args):
    conn = connect(); init_schema(conn)
    bat = _find_player(conn, args.batter)
    bowl = _find_player(conn, args.bowler)
    if not bat or not bowl:
        print("player not found"); conn.close(); return
    bat_names, bat_gender = names_for_player(conn, bat[0]["player_id"])
    bowl_names, bowl_gender = names_for_player(conn, bowl[0]["player_id"])
    _pp({"batter": bat[0]["canonical_name"], "bowler": bowl[0]["canonical_name"],
         "format": args.format,
         "h2h": batter_vs_bowler(conn, args.format, bat_names, bowl_names,
                                  bat_gender, bowl_gender)})
    conn.close()


def cmd_vs_team(args):
    """a player's full matchup breakdown against one specific opponent team:
    every bowler she's faced if she bats, every batter she's bowled to if
    she bowls. an all-rounder gets both.
    """
    conn = connect(); init_schema(conn)
    found = _find_player(conn, args.name)
    if not found:
        print("player not found"); conn.close(); return
    player_id = found[0]["player_id"]
    out = {"player": found[0]["canonical_name"], "opponent": args.team, "format": args.format}

    batting = matchups.batter_vs_team_bowlers(conn, player_id, args.format, args.team)
    if batting["bowlers"]:
        out["batting"] = batting
    bowling = matchups.bowler_vs_team_batters(conn, player_id, args.format, args.team, args.gender)
    if bowling["batters"]:
        out["bowling"] = bowling
    if "batting" not in out and "bowling" not in out:
        out["note"] = "no recorded matchup data vs this opponent"

    _pp(out)
    conn.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="criiq-data", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)

    d = sub.add_parser("download"); d.add_argument("--force", action="store_true")
    d.set_defaults(func=cmd_download)

    sub.add_parser("ingest").set_defaults(func=cmd_ingest)
    sub.add_parser("identity").set_defaults(func=cmd_identity)
    sub.add_parser("registry").set_defaults(func=cmd_registry)
    sub.add_parser("cards").set_defaults(func=cmd_cards)

    e = sub.add_parser("enrich")
    e.add_argument("--limit", type=int, default=None)
    e.add_argument("--refetch", action="store_true")
    e.set_defaults(func=cmd_enrich)

    sub.add_parser("rss").set_defaults(func=cmd_rss)

    a = sub.add_parser("alerts")
    a.add_argument("--confirm", type=int); a.add_argument("--dismiss", type=int)
    a.set_defaults(func=cmd_alerts)

    sub.add_parser("career").set_defaults(func=cmd_career)
    sub.add_parser("advanced").set_defaults(func=cmd_advanced)
    sub.add_parser("opponents").set_defaults(func=cmd_opponents)
    sub.add_parser("impact").set_defaults(func=cmd_impact)
    sub.add_parser("venues").set_defaults(func=cmd_venues)
    sub.add_parser("matchups").set_defaults(func=cmd_matchups)
    sub.add_parser("phases").set_defaults(func=cmd_phases)
    sub.add_parser("ml").set_defaults(func=cmd_ml)
    sub.add_parser("wpa", help="win-probability-added per player/match/phase").set_defaults(func=cmd_wpa)

    rf = sub.add_parser("role-finalize", help="finalized batter/bowler/all-rounder/keeper role")
    rf.add_argument("--format", default="T20")
    rf.add_argument("--load-external", metavar="CSV",
                     help="merge an externally-researched roles CSV (key_cricinfo, is_keeper, ...) "
                          "instead of running the local batting-position pass")
    rf.set_defaults(func=cmd_role_finalize)

    wp = sub.add_parser("winprob", help="build/query ball-by-ball win probability")
    wp.add_argument("--format", default="T20")
    wp.add_argument("--gender", default="female", help="which gender's fitted model to query (--state only; "
                                                         "build/--match are gender-agnostic, both are built/read together)")
    wp.add_argument("--match", help="print the per-over WP timeline for a match id")
    wp.add_argument("--state", help='ad-hoc WP, e.g. "innings=2,balls_remaining=30,wickets=4,runs_required=40"')
    wp.set_defaults(func=cmd_winprob)

    rk = sub.add_parser("rankings")
    rk.add_argument("--scaffold", action="store_true", help="write data/rankings/icc_rankings.csv template")
    rk.add_argument("--fetch", action="store_true", help="pull public ICC rankings into data/rankings/icc_rankings.csv")
    rk.set_defaults(func=cmd_rankings)

    so = sub.add_parser("status-override")
    so.add_argument("--scaffold", action="store_true", help="write data/overrides/player_status.csv template")
    so.set_defaults(func=cmd_status_override)

    sh = sub.add_parser("sheet", help="curated individual performance sheet")
    sh.add_argument("--name", required=True); sh.add_argument("--format", default="T20")
    sh.add_argument("--opponents", type=int, default=8)
    sh.set_defaults(func=cmd_sheet)

    s = sub.add_parser("styles")
    s.add_argument("--scaffold", action="store_true", help="write template CSV to fill")
    s.add_argument("--all", action="store_true", help="scaffold includes already-filled rows")
    s.add_argument("--seed", action="store_true", help="seed role/nationality from Wikidata")
    s.add_argument("--wiki", action="store_true", help="fill batting hand + bowling style from Wikipedia infoboxes")
    s.add_argument("--load", action="store_true", help="merge data/styles/player_styles.csv")
    s.add_argument("--limit", type=int, default=None)
    s.set_defaults(func=cmd_styles)

    pr = sub.add_parser("profile")
    pr.add_argument("--name", required=True); pr.add_argument("--format", default="T20")
    pr.add_argument("--first", action="store_true"); pr.set_defaults(func=cmd_profile)

    r = sub.add_parser("refresh")
    r.add_argument("--force", action="store_true", help="force re-download")
    r.add_argument("--enrich", action="store_true", help="best-effort cricinfo enrichment")
    r.add_argument("--seed-styles", action="store_true", help="seed styles from Wikidata")
    r.add_argument("--no-rss", action="store_true")
    r.set_defaults(func=cmd_refresh)

    sub.add_parser("status").set_defaults(func=cmd_status)

    c = sub.add_parser("card")
    c.add_argument("--name", required=True); c.add_argument("--format", default="T20")
    c.add_argument("--first", action="store_true")
    c.set_defaults(func=cmd_card)

    h = sub.add_parser("h2h")
    h.add_argument("--batter", required=True); h.add_argument("--bowler", required=True)
    h.add_argument("--format", default="T20"); h.set_defaults(func=cmd_h2h)

    vt = sub.add_parser("vs-team", help="a player's per-bowler/per-batter matchup breakdown vs one opponent team")
    vt.add_argument("--name", required=True)
    vt.add_argument("--team", required=True, help="opponent team name")
    vt.add_argument("--format", default="T20")
    vt.add_argument("--gender", default="female")
    vt.set_defaults(func=cmd_vs_team)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

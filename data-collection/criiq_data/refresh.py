from __future__ import annotations

import datetime as dt

from . import advanced, career, download_cricsheet, download_register, identity, impact
from . import ingest, matchups, ml_features, opponents, overrides, phases, player_card
from . import rankings, registry, rss_monitor, scrape_cricinfo, styles, venue_stats
from .config import SETTINGS
from .db import connect, get_meta, init_schema, set_meta, table_count
from .logging_utils import get_logger

log = get_logger("refresh")


def run(*, force_download: bool = False, enrich: bool = False,
        scan_rss: bool = True, seed_styles: bool = False, db_path=None) -> dict:
    started = dt.datetime.now()
    conn = connect(db_path)
    init_schema(conn)
    summary: dict = {"started_at": started.isoformat(timespec="seconds")}

    log.info("== 1/8 register ==")
    summary["register"] = download_register.download_register(conn)

    log.info("== 2/8 download cricsheet ==")
    summary["download"] = download_cricsheet.download_all(conn, force=force_download)

    log.info("== 3/8 ingest ==")
    summary["ingest"] = ingest.ingest_all(conn)

    log.info("== 4/8 identity ==")
    summary["identity"] = identity.run(conn)

    if enrich:
        log.info("== 5/9 cricinfo enrichment (best-effort) ==")
        summary["enrich"] = scrape_cricinfo.enrich_players(conn)
    else:
        log.info("== 5/9 cricinfo enrichment skipped (use --enrich) ==")

    log.info("== 6/9 styles (manual csv always; wikidata seed if requested) ==")
    summary["styles_csv"] = styles.load_manual_csv(conn)
    if seed_styles:
        try:
            summary["styles_wikidata"] = styles.seed_from_wikidata(conn)
        except Exception as exc:
            log.warning("wikidata seed failed: %s", exc)
            summary["styles_wikidata"] = {"error": str(exc)}
    summary["styles_coverage"] = styles.coverage(conn)

    if scan_rss:
        log.info("== 7/9 rss retirement scan ==")
        try:
            summary["rss"] = rss_monitor.scan_feeds(conn)
        except Exception as exc:
            log.warning("rss scan failed: %s", exc)
            summary["rss"] = {"error": str(exc)}

    log.info("== 8/9 registry + career + player cards ==")
    summary["icc_rankings"] = rankings.load_csv(conn)
    summary["status_overrides"] = overrides.load_csv(conn)
    summary["registry"] = registry.build_registry(conn)
    summary["career"] = career.build_career(conn)
    summary["cards"] = player_card.build_cards(conn)

    log.info("== 9/10 advanced profiles ==")
    summary["advanced"] = advanced.build_advanced(conn)

    log.info("== 10/10 per-opponent, impact, venue, matchups, phases ==")
    summary["vs_opponent"] = opponents.build_vs_opponent(conn)
    summary["impact"] = impact.build_impact(conn)
    summary["venue"] = venue_stats.build_venue_stats(conn)
    summary["matchups"] = matchups.build_matchups(conn)
    summary["phases"] = phases.build_phases(conn)

    log.info("== ML feature/label datasets (win-loss, ball-state, per-match impact) ==")
    summary["ml_features"] = ml_features.build_all(conn)

    set_meta(conn, "last_successful_refresh", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()

    summary["totals"] = {
        "matches": table_count(conn, "matches"),
        "deliveries": table_count(conn, "deliveries"),
        "players": table_count(conn, "players"),
        "registry_rows": table_count(conn, "player_registry"),
        "career_rows": table_count(conn, "player_career"),
        "cards": table_count(conn, "player_cards"),
        "advanced": table_count(conn, "player_advanced"),
        "vs_opponent_rows": table_count(conn, "player_vs_opponent"),
        "impact_rows": table_count(conn, "player_impact"),
        "venue_rows": table_count(conn, "player_by_venue"),
        "matchup_rows": table_count(conn, "dismissal_matchup"),
        "phase_rows": table_count(conn, "player_phase"),
        "match_features": table_count(conn, "match_features"),
        "player_match_impact": table_count(conn, "player_match_impact"),
    }
    summary["elapsed_s"] = round((dt.datetime.now() - started).total_seconds(), 1)
    conn.close()
    log.info("refresh complete in %.1fs | %s", summary["elapsed_s"], summary["totals"])
    return summary


def freshness(conn) -> dict:
    last = get_meta(conn, "last_successful_refresh")
    if not last:
        return {"status": "never", "stale": True, "days": None}
    days = (dt.datetime.now() - dt.datetime.fromisoformat(last)).days
    return {
        "status": "ok" if days <= SETTINGS.registry_refresh_days else
                  ("warn" if days <= SETTINGS.staleness_warn_days else "stale"),
        "stale": days > SETTINGS.staleness_warn_days,
        "days": days, "last_successful_refresh": last,
    }

from __future__ import annotations

import datetime as dt

import feedparser

from .config import RETIREMENT_KEYWORDS, RSS_FEEDS
from .logging_utils import get_logger

log = get_logger("rss")


def _matches_keyword(text: str) -> str | None:
    low = (text or "").lower()
    for kw in RETIREMENT_KEYWORDS:
        if kw in low:
            return kw
    return None


def scan_feeds(conn, feeds: list[str] | None = None) -> dict:
    feeds = feeds or RSS_FEEDS
    now = dt.datetime.now().isoformat(timespec="seconds")
    new_alerts = scanned = 0
    for url in feeds:
        try:
            parsed = feedparser.parse(url)
        except Exception as exc:
            log.warning("RSS parse failed %s: %s", url, exc)
            continue
        for entry in parsed.entries:
            scanned += 1
            text = f"{entry.get('title','')} {entry.get('summary','')}"
            kw = _matches_keyword(text)
            if not kw:
                continue
            link = entry.get("link") or entry.get("id")
            cur = conn.execute(
                "INSERT OR IGNORE INTO retirement_alerts"
                "(source, title, link, published, matched_keyword, status, detected_at) "
                "VALUES(?,?,?,?,?, 'PENDING', ?)",
                (url, entry.get("title"), link, entry.get("published"), kw, now))
            if cur.rowcount:
                new_alerts += 1
    conn.commit()
    log.info("RSS: scanned %d entries, %d new retirement alerts", scanned, new_alerts)
    return {"scanned": scanned, "new_alerts": new_alerts}


def list_alerts(conn, status: str = "PENDING") -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, source, title, link, published, matched_keyword, status "
        "FROM retirement_alerts WHERE status=? ORDER BY id DESC", (status,))]


def set_alert_status(conn, alert_id: int, status: str) -> bool:
    cur = conn.execute("UPDATE retirement_alerts SET status=? WHERE id=?",
                       (status, alert_id))
    conn.commit()
    return bool(cur.rowcount)

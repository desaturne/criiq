from __future__ import annotations

import csv
import datetime as dt
import json
import urllib.parse

from . import http
from .config import MANUAL_STYLES_CSV, STYLES_DIR, WIKIDATA_SPARQL
from .logging_utils import get_logger

log = get_logger("styles")


_PACE = ("fast", "medium", "seam", "pace", "swing")
_SPIN = ("off break", "offbreak", "leg break", "legbreak", "orthodox",
         "spin", "googly", "chinaman", "slow", "wrist", "finger")


def classify_bowling(style: str | None) -> str | None:
    if not style:
        return None
    s = style.lower()
    if any(k in s for k in _SPIN):
        return "spin"
    if any(k in s for k in _PACE):
        return "pace"
    return None


def classify_hand(hand: str | None) -> str | None:
    if not hand:
        return None
    h = hand.lower()
    if "left" in h:
        return "LHB"
    if "right" in h:
        return "RHB"
    return None


def _sparql(query: str) -> dict:
    url = f"{WIKIDATA_SPARQL}?" + urllib.parse.urlencode(
        {"query": query, "format": "json"})
    resp = http.get(url, delay_s=1.5, timeout=60,
                    headers={"Accept": "application/sparql-results+json"})
    return resp.json()


def seed_from_wikidata(conn, chunk: int = 150, limit: int | None = None) -> dict:
    q = ("SELECT key_cricinfo FROM players WHERE key_cricinfo IS NOT NULL "
         "AND key_cricinfo != '' AND (date_of_birth IS NULL OR role IS NULL "
         "OR nationality IS NULL)")
    if limit:
        q += f" LIMIT {int(limit)}"
    ids = [r["key_cricinfo"] for r in conn.execute(q)]
    if not ids:
        log.info("wikidata seed: nothing to do")
        return {"targets": 0, "seeded": 0, "with_dob": 0}

    now = dt.datetime.now().isoformat(timespec="seconds")
    seeded = with_dob = 0
    for i in range(0, len(ids), chunk):
        batch = ids[i:i + chunk]
        values = " ".join(f'"{x}"' for x in batch)
        query = f"""
        SELECT ?cricinfo ?dob ?roleLabel ?countryLabel WHERE {{
          ?p wdt:P2697 ?cricinfo .
          VALUES ?cricinfo {{ {values} }}
          OPTIONAL {{ ?p wdt:P569 ?dob. }}
          OPTIONAL {{ ?p wdt:P413 ?role. }}
          OPTIONAL {{ ?p wdt:P27 ?country. }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }}"""
        try:
            res = _sparql(query)
        except Exception as exc:
            log.warning("wikidata batch %d failed: %s", i // chunk, exc)
            continue
        for b in res["results"]["bindings"]:
            cid = b["cricinfo"]["value"]
            dob = b.get("dob", {}).get("value")
            dob = dob[:10] if dob else None
            role = b.get("roleLabel", {}).get("value")
            country = b.get("countryLabel", {}).get("value")
            if not (dob or role or country):
                continue
            if dob:
                with_dob += 1
            conn.execute(
                "UPDATE players SET date_of_birth=COALESCE(date_of_birth, ?), "
                "role=COALESCE(role, ?), nationality=COALESCE(nationality, ?) "
                "WHERE key_cricinfo=?", (dob, role, country, cid))
            conn.execute(
                "INSERT INTO player_styles(player_id, playing_role, source, updated_at) "
                "SELECT player_id, ?, 'wikidata', ? FROM players WHERE key_cricinfo=? "
                "ON CONFLICT(player_id) DO UPDATE SET "
                "playing_role=COALESCE(player_styles.playing_role, excluded.playing_role), "
                "source=excluded.source, updated_at=excluded.updated_at",
                (role, now, cid))
            seeded += 1
        conn.commit()
        log.info("wikidata seed: %d/%d processed", min(i + chunk, len(ids)), len(ids))
    log.info("wikidata seed: %d players seeded (%d with DOB)", seeded, with_dob)
    return {"targets": len(ids), "seeded": seeded, "with_dob": with_dob}


_CSV_HEADER = ["key_cricinfo", "name", "bowling_style", "batting_hand", "playing_role"]


def scaffold_csv(conn, path=None, only_missing: bool = True) -> str:
    path = path or MANUAL_STYLES_CSV
    STYLES_DIR.mkdir(parents=True, exist_ok=True)
    where = "WHERE key_cricinfo IS NOT NULL AND key_cricinfo != ''"
    if only_missing:
        where += " AND (bowling_style IS NULL OR batting_hand IS NULL)"
    rows = conn.execute(
        f"SELECT key_cricinfo, canonical_name, bowling_style, batting_hand, role "
        f"FROM players {where} ORDER BY canonical_name").fetchall()
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(_CSV_HEADER)
        for r in rows:
            w.writerow([r["key_cricinfo"], r["canonical_name"],
                        r["bowling_style"] or "", r["batting_hand"] or "", r["role"] or ""])
    log.info("scaffolded styles CSV (%d rows) -> %s", len(rows), path)
    return str(path)


def load_manual_csv(conn, path=None) -> dict:
    path = path or MANUAL_STYLES_CSV
    try:
        fh = open(path, newline="", encoding="utf-8")
    except FileNotFoundError:
        log.info("no manual styles CSV at %s (skip)", path)
        return {"loaded": 0}
    now = dt.datetime.now().isoformat(timespec="seconds")
    loaded = 0
    with fh:
        for row in csv.DictReader(fh):
            cid = (row.get("key_cricinfo") or "").strip()
            bowl = (row.get("bowling_style") or "").strip() or None
            hand = (row.get("batting_hand") or "").strip() or None
            role = (row.get("playing_role") or "").strip() or None
            if not cid or not (bowl or hand or role):
                continue
            conn.execute(
                "UPDATE players SET bowling_style=COALESCE(?, bowling_style), "
                "batting_hand=COALESCE(?, batting_hand), role=COALESCE(?, role) "
                "WHERE key_cricinfo=?", (bowl, hand, role, cid))
            conn.execute(
                "INSERT INTO player_styles(player_id, bowling_style, batting_hand, "
                "playing_role, source, updated_at) "
                "SELECT player_id, ?, ?, ?, 'manual_csv', ? FROM players WHERE key_cricinfo=? "
                "ON CONFLICT(player_id) DO UPDATE SET "
                "bowling_style=COALESCE(excluded.bowling_style, player_styles.bowling_style), "
                "batting_hand=COALESCE(excluded.batting_hand, player_styles.batting_hand), "
                "playing_role=COALESCE(excluded.playing_role, player_styles.playing_role), "
                "source='manual_csv', updated_at=excluded.updated_at",
                (bowl, hand, role, now, cid))
            loaded += 1
    conn.commit()
    log.info("manual styles CSV: %d rows merged", loaded)
    return {"loaded": loaded}


def bowler_buckets(conn) -> dict[str, str]:
    out = {}
    for r in conn.execute(
            "SELECT im.player_name, p.bowling_style FROM players p "
            "JOIN identifier_map im ON im.identifier = p.cricsheet_identifier "
            "WHERE p.bowling_style IS NOT NULL"):
        bucket = classify_bowling(r["bowling_style"])
        if bucket:
            out[r["player_name"]] = bucket
    return out


def batter_hands(conn) -> dict[str, str]:
    out = {}
    for r in conn.execute(
            "SELECT im.player_name, p.batting_hand FROM players p "
            "JOIN identifier_map im ON im.identifier = p.cricsheet_identifier "
            "WHERE p.batting_hand IS NOT NULL"):
        hand = classify_hand(r["batting_hand"])
        if hand:
            out[r["player_name"]] = hand
    return out


def coverage(conn) -> dict:
    total = conn.execute("SELECT COUNT(*) n FROM players").fetchone()["n"]
    bowl = conn.execute("SELECT COUNT(*) n FROM players WHERE bowling_style IS NOT NULL").fetchone()["n"]
    hand = conn.execute("SELECT COUNT(*) n FROM players WHERE batting_hand IS NOT NULL").fetchone()["n"]
    role = conn.execute("SELECT COUNT(*) n FROM players WHERE role IS NOT NULL").fetchone()["n"]
    return {"players": total, "with_bowling_style": bowl,
            "with_batting_hand": hand, "with_role": role}

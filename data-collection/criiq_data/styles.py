from __future__ import annotations

import csv
import datetime as dt
import json
import re
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


def classify_bowling_detail(style: str | None) -> str | None:
    """finer bowling bucket for batter matchups (off-spin turns into a RHB, leg-spin away).
    falls back to pace/spin when the style is only generically described."""
    if not style:
        return None
    s = style.lower()
    left = ("left-arm" in s) or ("left arm" in s) or ("slow left" in s)
    if "off" in s and ("break" in s or "spin" in s):
        return "off-spin"
    if ("leg" in s and ("break" in s or "spin" in s)) or "googly" in s or "wrist" in s or "chinaman" in s:
        return "leg-spin"
    if left and ("orthodox" in s or "slow" in s or "spin" in s):
        return "slow-left-arm"
    if any(k in s for k in _PACE):
        return "pace"
    if any(k in s for k in _SPIN):
        return "spin"
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


_CRICKET_ROLE_KEYWORDS = (
    "batsman", "batswoman", "batter", "batting",
    "bowler", "bowling",
    "all-rounder", "all rounder", "allrounder",
    "wicket-keeper", "wicketkeeper", "wicket keeper",
)


def is_cricket_role(role_text: str | None) -> bool:
    """True if `role_text` names an actual cricket role, not another sport's position (Wikidata's P413 is cross-sport)."""
    if not role_text:
        return False
    r = role_text.lower()
    return any(k in r for k in _CRICKET_ROLE_KEYWORDS)


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
            if role and not is_cricket_role(role):
                log.info("wikidata seed: dropping non-cricket role %r for cricinfo=%s "
                         "(P413 is a cross-sport property, not cricket-specific)", role, cid)
                role = None
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


_WIKI_API = "https://en.wikipedia.org/w/api.php"


def _clean_wiki(v: str) -> str:
    v = v.split("<br")[0].split("<ref")[0]                     # first style only
    v = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", v)    # [[a|b]] -> b, [[a]] -> a (removes internal |)
    v = re.sub(r"\{\{[^{}]*\}\}", "", v)                        # drop templates
    v = v.split("|")[0]                                        # stop at the next infobox parameter
    v = re.sub(r"<[^>]+>", "", v)                              # drop tags
    return v.replace("'''", "").replace("''", "").strip(" .")


def _infobox_field(text: str, field: str) -> str | None:
    m = re.search(r"\n\s*\|\s*" + re.escape(field) + r"\s*=\s*([^\n]*)", text, re.I)
    val = _clean_wiki(m.group(1)) if m else ""
    return val or None


def _wiki_titles(cricinfo_ids: list[str]) -> dict[str, str]:
    """map ESPNcricinfo id -> English Wikipedia article title via Wikidata."""
    values = " ".join(f'"{x}"' for x in cricinfo_ids)
    query = f"""
    SELECT ?cricinfo ?title WHERE {{
      ?p wdt:P2697 ?cricinfo .
      VALUES ?cricinfo {{ {values} }}
      ?article schema:about ?p ;
               schema:isPartOf <https://en.wikipedia.org/> ;
               schema:name ?title .
    }}"""
    out = {}
    for b in _sparql(query)["results"]["bindings"]:
        out[b["cricinfo"]["value"]] = b["title"]["value"]
    return out


def _wiki_pages(titles: list[str]) -> tuple[dict[str, str], list, list]:
    params = {"action": "query", "prop": "revisions", "rvprop": "content",
              "rvslots": "main", "format": "json", "formatversion": "2",
              "redirects": "1", "titles": "|".join(titles)}
    data = http.get(_WIKI_API, params=params, delay_s=1.0, timeout=60,
                    headers={"Accept": "application/json"}).json()
    q = data.get("query", {})
    pages = {}
    for pg in q.get("pages", []):
        revs = pg.get("revisions")
        if revs:
            content = revs[0].get("slots", {}).get("main", {}).get("content")
            if content:
                pages[pg["title"]] = content
    return pages, q.get("normalized", []), q.get("redirects", [])


def _resolve_title(title: str, normalized: list, redirects: list) -> str:
    nmap = {n["from"]: n["to"] for n in normalized}
    rmap = {r["from"]: r["to"] for r in redirects}
    return rmap.get(nmap.get(title, title), nmap.get(title, title))


def enrich_from_wikipedia(conn, limit: int | None = None, chunk: int = 40) -> dict:
    """fills batting hand + bowling style from Wikipedia cricketer infoboxes via Wikidata sitelinks.
    never overwrites existing values, so manual_csv entries act as overrides."""
    ids = [r["key_cricinfo"] for r in conn.execute(
        "SELECT key_cricinfo FROM players WHERE key_cricinfo IS NOT NULL "
        "AND key_cricinfo != '' AND (bowling_style IS NULL OR batting_hand IS NULL)")]
    if limit:
        ids = ids[:limit]
    if not ids:
        log.info("wikipedia styles: nothing to do")
        return {"targets": 0, "with_hand": 0, "with_style": 0}

    title_to_cid: dict[str, str] = {}
    for i in range(0, len(ids), 150):
        try:
            for cid, title in _wiki_titles(ids[i:i + 150]).items():
                title_to_cid[title] = cid
        except Exception as exc:
            log.warning("wikidata sitelink batch %d failed: %s", i // 150, exc)

    now = dt.datetime.now().isoformat(timespec="seconds")
    all_titles = list(title_to_cid)
    with_hand = with_style = 0
    for i in range(0, len(all_titles), chunk):
        batch = all_titles[i:i + chunk]
        try:
            pages, norm, redir = _wiki_pages(batch)
        except Exception as exc:
            log.warning("wikipedia batch %d failed: %s", i // chunk, exc)
            continue
        for req_title in batch:
            cid = title_to_cid.get(req_title)
            text = pages.get(_resolve_title(req_title, norm, redir)) or pages.get(req_title)
            if not (cid and text):
                continue
            bat = _infobox_field(text, "batting")
            bowl = _infobox_field(text, "bowling")
            hand = bat if classify_hand(bat) else None       # keep only real hands
            if not (hand or bowl):
                continue
            conn.execute(
                "UPDATE players SET bowling_style=COALESCE(bowling_style, ?), "
                "batting_hand=COALESCE(batting_hand, ?) WHERE key_cricinfo=?",
                (bowl, hand, cid))
            conn.execute(
                "INSERT INTO player_styles(player_id, bowling_style, batting_hand, "
                "source, updated_at) SELECT player_id, ?, ?, 'wikipedia_infobox', ? "
                "FROM players WHERE key_cricinfo=? "
                "ON CONFLICT(player_id) DO UPDATE SET "
                "bowling_style=COALESCE(player_styles.bowling_style, excluded.bowling_style), "
                "batting_hand=COALESCE(player_styles.batting_hand, excluded.batting_hand), "
                "updated_at=excluded.updated_at",
                (bowl, hand, now, cid))
            with_hand += 1 if hand else 0
            with_style += 1 if bowl else 0
        conn.commit()
        log.info("wikipedia styles: %d/%d titles processed", min(i + chunk, len(all_titles)), len(all_titles))
    log.info("wikipedia styles: %d hands, %d bowling styles filled (of %d targets)",
             with_hand, with_style, len(ids))
    return {"targets": len(ids), "matched_titles": len(all_titles),
            "with_hand": with_hand, "with_style": with_style}


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


def bowler_buckets(conn, *, detail: bool = False) -> dict[tuple[str, str | None], str]:
    """(player_name, gender) -> bucket, not just player_name.

    a few Cricsheet identifiers are shared across two different people (see identity.py), so gender must be part of the key.
    """
    fn = classify_bowling_detail if detail else classify_bowling
    out = {}
    for r in conn.execute(
            "SELECT im.player_name, p.gender, p.bowling_style FROM players p "
            "JOIN identifier_map im ON im.identifier = p.cricsheet_identifier "
            "WHERE p.bowling_style IS NOT NULL"):
        bucket = fn(r["bowling_style"])
        if bucket:
            out[(r["player_name"], r["gender"])] = bucket
    return out


def batter_hands(conn) -> dict[tuple[str, str | None], str]:
    """(player_name, gender) -> hand. see bowler_buckets for why gender must be part of the key."""
    out = {}
    for r in conn.execute(
            "SELECT im.player_name, p.gender, p.batting_hand FROM players p "
            "JOIN identifier_map im ON im.identifier = p.cricsheet_identifier "
            "WHERE p.batting_hand IS NOT NULL"):
        hand = classify_hand(r["batting_hand"])
        if hand:
            out[(r["player_name"], r["gender"])] = hand
    return out


def coverage(conn) -> dict:
    total = conn.execute("SELECT COUNT(*) n FROM players").fetchone()["n"]
    bowl = conn.execute("SELECT COUNT(*) n FROM players WHERE bowling_style IS NOT NULL").fetchone()["n"]
    hand = conn.execute("SELECT COUNT(*) n FROM players WHERE batting_hand IS NOT NULL").fetchone()["n"]
    role = conn.execute("SELECT COUNT(*) n FROM players WHERE role IS NOT NULL").fetchone()["n"]
    return {"players": total, "with_bowling_style": bowl,
            "with_batting_hand": hand, "with_role": role}

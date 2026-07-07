from __future__ import annotations

import csv
import datetime as dt
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

from .config import (
    ICC_RANKINGS_CLIENT_ID,
    ICC_RANKINGS_CSV,
    ICC_RANKINGS_SOURCE_URL,
    RANKINGS_DIR,
    SETTINGS,
)
from .logging_utils import get_logger

log = get_logger("rankings")

_CSV_HEADER = [
    "format", "gender", "discipline", "rank", "rating", "player_name",
    "key_cricinfo", "source", "source_url", "rank_date", "extracted_at",
]
_DISCIPLINES = {"batting": "bat", "bowling": "bowl", "allrounder": "allrounder"}
_FORMATS = {"Test": "test", "ODI": "odi", "T20": "t20"}
_GENDERS = {"male": "", "female": "w"}


class RankingsFetchError(RuntimeError):
    pass


def _unmatched_id(fmt: str, discipline: str, gender: str | None, rank: int | None, name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "unknown"
    return f"UNMATCHED::{fmt}::{discipline}::{gender or "unknown"}::{rank or "na"}::{key}"


def normalise_format(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().upper()
    if v in ("T20", "T20I", "IT20"):
        return "T20"
    if v == "ODI":
        return "ODI"
    if v in ("TEST", "TESTS"):
        return "Test"
    return value.strip()


def _resolve(conn):
    by_cricinfo = {}
    names = []
    for r in conn.execute("SELECT player_id, canonical_name, key_cricinfo FROM players"):
        if r["key_cricinfo"]:
            by_cricinfo[str(r["key_cricinfo"])] = r["player_id"]
        if r["canonical_name"]:
            names.append((r["player_id"], r["canonical_name"]))
    return by_cricinfo, names


def _load_rows(conn, rows, *, source: str = "manual_csv", source_url: str | None = None) -> dict:
    from rapidfuzz import fuzz, process

    by_cricinfo, names = _resolve(conn)
    name_keys = [n for _, n in names]
    now = dt.datetime.now().isoformat(timespec="seconds")
    loaded = matched = unmatched = 0
    for row in rows:
        fmt = normalise_format(row.get("format"))
        disc = (row.get("discipline") or "").strip().lower()
        if not fmt or not disc:
            continue
        cid = (row.get("key_cricinfo") or "").strip()
        pid = by_cricinfo.get(cid) if cid else None
        if not pid:
            nm = (row.get("player_name") or "").strip()
            if nm and name_keys:
                best = process.extractOne(nm, name_keys, scorer=fuzz.WRatio)
                if best and best[1] >= 90:
                    pid = names[best[2]][0]
        rank = int(row["rank"]) if (row.get("rank") or "").strip().isdigit() else None
        row_gender = (row.get("gender") or "").strip().lower() or None
        row_name = (row.get("player_name") or "").strip()
        is_matched = 1
        if not pid:
            unmatched += 1
            is_matched = 0
            pid = _unmatched_id(fmt, disc, row_gender, rank, row_name)
        rating = int(row["rating"]) if (row.get("rating") or "").strip().isdigit() else None
        row_source = (row.get("source") or source or "manual_csv").strip()
        row_source_url = (row.get("source_url") or source_url or "").strip() or None
        rank_date = (row.get("rank_date") or "").strip() or None
        extracted_at = (row.get("extracted_at") or now).strip()
        conn.execute(
            "INSERT INTO icc_rankings(player_id, format, discipline, gender, rank, "
            "rating, player_name, matched, source, source_url, rank_date, extracted_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(player_id, format, discipline) DO UPDATE SET "
            "rank=excluded.rank, rating=excluded.rating, gender=excluded.gender, "
            "player_name=excluded.player_name, matched=excluded.matched, source=excluded.source, "
            "source_url=excluded.source_url, rank_date=excluded.rank_date, "
            "extracted_at=excluded.extracted_at, updated_at=excluded.updated_at",
            (pid, fmt, disc, row_gender, rank, rating, row_name, is_matched,
             row_source, row_source_url, rank_date, extracted_at, now))
        loaded += 1
        matched += is_matched
    conn.commit()
    log.info("ICC rankings: %d loaded, %d unmatched names", loaded, unmatched)
    return {"loaded": loaded, "matched": matched, "unmatched": unmatched}


def load_csv(conn, path=None) -> dict:
    path = path or ICC_RANKINGS_CSV
    try:
        fh = open(path, newline="", encoding="utf-8")
    except FileNotFoundError:
        log.info("no ICC rankings CSV at %s (skip)", path)
        return {"loaded": 0, "matched": 0, "unmatched": 0, "path": str(path)}

    with fh:
        res = _load_rows(conn, csv.DictReader(fh), source="manual_csv", source_url=str(path))
    res["path"] = str(path)
    return res


def _response_rows(payload: dict, *, fmt: str, gender: str, discipline: str,
                   source_url: str | None = None, extracted_at: str | None = None) -> list[dict]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    ranking_block = None
    for key, value in data.items():
        if key.endswith("-rank") and isinstance(value, dict):
            ranking_block = value
            break
    if not ranking_block:
        return []

    rank_date = str(ranking_block.get("rank_date") or "").strip()
    out = []
    for item in ranking_block.get("rank") or []:
        rank = str(item.get("no") or "").strip()
        if rank == "=":
            rank = str(item.get("rank") or "").strip()
        player_name = str(item.get("Player-name") or item.get("player_name") or "").strip()
        rating = str(item.get("Points") or item.get("Rating") or "").strip()
        if not rank or not player_name:
            continue
        out.append({
            "format": fmt,
            "gender": gender,
            "discipline": discipline,
            "rank": rank,
            "rating": rating,
            "player_name": player_name,
            "key_cricinfo": "",
            "source": "icc_public_endpoint",
            "source_url": source_url or "",
            "rank_date": rank_date,
            "extracted_at": extracted_at or "",
        })
    return out


def _ranking_url_is_public(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.netloc)


def fetch_live_rows(*, client_id: str | None = None, source_url: str | None = None,
                    session=None) -> list[dict]:
    client_id = client_id or ICC_RANKINGS_CLIENT_ID
    source_url = source_url or ICC_RANKINGS_SOURCE_URL
    if not client_id:
        raise RankingsFetchError(
            "CRIIQ_ICC_RANKINGS_CLIENT_ID is not set; refusing to guess or bypass ICC access"
        )
    if not _ranking_url_is_public(source_url):
        raise RankingsFetchError(f"ICC rankings source must be an https URL: {source_url}")

    http = session or requests.Session()
    headers = {"User-Agent": SETTINGS.user_agent, "Accept": "application/json"}
    rows: list[dict] = []
    extracted_at = dt.datetime.now().isoformat(timespec="seconds")
    for fmt, comp_base in _FORMATS.items():
        for gender, gender_suffix in _GENDERS.items():
            if fmt == "Test" and gender == "female":
                continue
            for discipline, data_type in _DISCIPLINES.items():
                params = {
                    "client_id": client_id,
                    "comp_type": f"{comp_base}{gender_suffix}",
                    "lang": "en",
                    "feed_format": "json",
                    "type": data_type,
                }
                resp = http.get(source_url, params=params, headers=headers,
                                timeout=SETTINGS.http_timeout_s)
                if resp.status_code in (401, 403):
                    raise RankingsFetchError(
                        "ICC rankings endpoint denied access; check CRIIQ_ICC_RANKINGS_CLIENT_ID"
                    )
                resp.raise_for_status()
                rows.extend(_response_rows(
                    resp.json(), fmt=fmt, gender=gender, discipline=discipline,
                    source_url=source_url, extracted_at=extracted_at,
                ))
    return rows


def write_csv(rows: list[dict], path=None) -> str:
    path = Path(path or ICC_RANKINGS_CSV)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)
    log.info("wrote %d ICC ranking rows -> %s", len(rows), path)
    return str(path)


def load_live(conn, *, client_id: str | None = None, source_url: str | None = None,
              persist_csv: bool = True, session=None) -> dict:
    source_url = source_url or ICC_RANKINGS_SOURCE_URL
    rows = fetch_live_rows(client_id=client_id, source_url=source_url, session=session)
    csv_path = write_csv(rows) if persist_csv else None
    res = _load_rows(conn, rows, source="icc_public_endpoint", source_url=source_url)
    res["fetched"] = len(rows)
    res["source"] = source_url
    res["path"] = csv_path
    return res


def load(conn, *, prefer_live: bool = True) -> dict:
    if prefer_live and ICC_RANKINGS_CLIENT_ID:
        try:
            return load_live(conn)
        except Exception as exc:
            log.warning("live ICC rankings fetch failed; falling back to CSV: %s", exc)
    return load_csv(conn)


def scaffold_csv(path=None) -> str:
    path = path or ICC_RANKINGS_CSV
    RANKINGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(_CSV_HEADER)
        w.writerow(["T20", "female", "batting", "1", "760", "Smriti Mandhana", "",
                    "manual_csv", str(path), "", ""])
        w.writerow(["T20", "male", "bowling", "1", "745", "", "8917",
                    "manual_csv", str(path), "", ""])
    log.info("wrote ICC rankings template -> %s", path)
    return str(path)


def ranked_ids(conn, fmt: str) -> set[str]:
    return {r["player_id"] for r in conn.execute(
        "SELECT DISTINCT player_id FROM icc_rankings WHERE format=? AND matched=1", (fmt,))}


def current_rank(conn, player_id: str, fmt: str):
    row = conn.execute(
        "SELECT rank, rating, discipline, source, source_url, rank_date, extracted_at "
        "FROM icc_rankings WHERE player_id=? AND format=? AND matched=1 "
        "ORDER BY rank ASC LIMIT 1", (player_id, fmt)).fetchone()
    return dict(row) if row else None


def player_rankings(conn, player_id: str, fmt: str) -> list[dict]:
    rows = conn.execute(
        "SELECT discipline, rank, rating, gender, player_name, source, source_url, "
        "rank_date, extracted_at, updated_at FROM icc_rankings "
        "WHERE player_id=? AND format=? AND matched=1 ORDER BY rank ASC, discipline ASC",
        (player_id, fmt),
    ).fetchall()
    return [dict(r) for r in rows]
from __future__ import annotations

import csv
import datetime as dt

from .config import ICC_RANKINGS_CSV, RANKINGS_DIR
from .logging_utils import get_logger

log = get_logger("rankings")

_CSV_HEADER = ["format", "gender", "discipline", "rank", "rating", "player_name", "key_cricinfo"]


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


def load_csv(conn, path=None) -> dict:
    path = path or ICC_RANKINGS_CSV
    try:
        fh = open(path, newline="", encoding="utf-8")
    except FileNotFoundError:
        log.info("no ICC rankings CSV at %s (skip)", path)
        return {"loaded": 0, "matched": 0, "unmatched": 0}

    from rapidfuzz import process, fuzz
    by_cricinfo, names = _resolve(conn)
    name_keys = [n for _, n in names]
    now = dt.datetime.now().isoformat(timespec="seconds")
    loaded = matched = unmatched = 0
    with fh:
        for row in csv.DictReader(fh):
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
            if not pid:
                unmatched += 1
                continue
            rank = int(row["rank"]) if (row.get("rank") or "").strip().isdigit() else None
            rating = int(row["rating"]) if (row.get("rating") or "").strip().isdigit() else None
            conn.execute(
                "INSERT INTO icc_rankings(player_id, format, discipline, gender, rank, "
                "rating, player_name, updated_at) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(player_id, format, discipline) DO UPDATE SET "
                "rank=excluded.rank, rating=excluded.rating, gender=excluded.gender, "
                "player_name=excluded.player_name, updated_at=excluded.updated_at",
                (pid, fmt, disc, (row.get("gender") or "").strip().lower() or None,
                 rank, rating, row.get("player_name"), now))
            loaded += 1
            matched += 1
    conn.commit()
    log.info("ICC rankings: %d loaded, %d unmatched names", loaded, unmatched)
    return {"loaded": loaded, "matched": matched, "unmatched": unmatched}


def scaffold_csv(path=None) -> str:
    path = path or ICC_RANKINGS_CSV
    RANKINGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(_CSV_HEADER)
        w.writerow(["T20", "female", "batting", "1", "760", "Smriti Mandhana", ""])
        w.writerow(["T20", "male", "bowling", "1", "745", "", "8917"])
    log.info("wrote ICC rankings template -> %s", path)
    return str(path)


def ranked_ids(conn, fmt: str) -> set[str]:
    return {r["player_id"] for r in conn.execute(
        "SELECT DISTINCT player_id FROM icc_rankings WHERE format=?", (fmt,))}


def current_rank(conn, player_id: str, fmt: str):
    row = conn.execute(
        "SELECT rank, rating, discipline FROM icc_rankings WHERE player_id=? AND format=? "
        "ORDER BY rank ASC LIMIT 1", (player_id, fmt)).fetchone()
    return dict(row) if row else None

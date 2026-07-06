from __future__ import annotations

import csv
import datetime as dt

from .config import OVERRIDES_DIR, PLAYER_STATUS_CSV
from .logging_utils import get_logger
from .rankings import normalise_format

log = get_logger("overrides")

_CSV_HEADER = ["player_name", "key_cricinfo", "format", "retirement_status",
               "retirement_date", "note"]
_VALID = {"ACTIVE", "RETIRED_ALL", "RETIRED_FORMAT", "UNAVAILABLE", "UNKNOWN"}


def _resolve(conn):
    by_cricinfo, names = {}, []
    for r in conn.execute("SELECT player_id, canonical_name, key_cricinfo FROM players"):
        if r["key_cricinfo"]:
            by_cricinfo[str(r["key_cricinfo"])] = r["player_id"]
        if r["canonical_name"]:
            names.append((r["player_id"], r["canonical_name"]))
    return by_cricinfo, names


def load_csv(conn, path=None) -> dict:
    path = path or PLAYER_STATUS_CSV
    try:
        fh = open(path, newline="", encoding="utf-8")
    except FileNotFoundError:
        log.info("no status overrides CSV at %s (skip)", path)
        return {"loaded": 0, "unmatched": 0}

    from rapidfuzz import process, fuzz
    by_cricinfo, names = _resolve(conn)
    name_keys = [n for _, n in names]
    now = dt.datetime.now().isoformat(timespec="seconds")
    loaded = unmatched = 0
    with fh:
        for row in csv.DictReader(fh):
            status = (row.get("retirement_status") or "").strip().upper()
            if status not in _VALID:
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
            fmt = normalise_format(row.get("format")) or "ALL"
            if status == "RETIRED_ALL":
                fmt = "ALL"
            conn.execute(
                "INSERT INTO status_overrides(player_id, format, retirement_status, "
                "retirement_date, note, source, updated_at) VALUES(?,?,?,?,?, 'manual', ?) "
                "ON CONFLICT(player_id, format) DO UPDATE SET "
                "retirement_status=excluded.retirement_status, "
                "retirement_date=excluded.retirement_date, note=excluded.note, "
                "updated_at=excluded.updated_at",
                (pid, fmt, status, (row.get("retirement_date") or "").strip() or None,
                 (row.get("note") or "").strip() or None, now))
            loaded += 1
    conn.commit()
    log.info("status overrides: %d loaded, %d unmatched", loaded, unmatched)
    return {"loaded": loaded, "unmatched": unmatched}


def scaffold_csv(path=None) -> str:
    path = path or PLAYER_STATUS_CSV
    OVERRIDES_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(_CSV_HEADER)
        w.writerow(["V Kohli", "253802", "T20", "RETIRED_FORMAT", "2024-06-29",
                    "Retired from T20Is after 2024 T20 World Cup"])
        w.writerow(["MM Lanning", "329336", "ALL", "RETIRED_ALL", "2023-11-30",
                    "Retired from international cricket"])
    log.info("wrote status overrides template -> %s", path)
    return str(path)


def overrides_map(conn, fmt: str) -> dict:
    out = {}
    for r in conn.execute(
            "SELECT player_id, format, retirement_status, retirement_date "
            "FROM status_overrides WHERE format IN ('ALL', ?)", (fmt,)):
        prev = out.get(r["player_id"])
        if prev is None or r["format"] != "ALL":
            out[r["player_id"]] = {"status": r["retirement_status"],
                                   "date": r["retirement_date"], "scope": r["format"]}
    return out

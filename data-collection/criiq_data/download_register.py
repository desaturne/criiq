from __future__ import annotations

import csv
import datetime as dt
import io

from . import http
from .config import REGISTER_DIR, REGISTER_URL, SETTINGS, ensure_dirs
from .db import set_meta
from .logging_utils import get_logger

log = get_logger("register")

_KEEP = ["identifier", "name", "unique_name", "key_cricinfo", "key_cricinfo_2"]


def download_register(conn) -> int:
    ensure_dirs()
    log.info("downloading people register …")
    resp = http.get(REGISTER_URL, delay_s=SETTINGS.cricsheet_delay_s)
    text = resp.content.decode("utf-8", errors="replace")

    out_path = REGISTER_DIR / "people.csv"
    out_path.write_text(text, encoding="utf-8")

    reader = csv.DictReader(io.StringIO(text))
    rows = []
    with_cricinfo = 0
    for r in reader:
        rec = {k: (r.get(k) or "").strip() or None for k in _KEEP}
        if not rec["identifier"]:
            continue
        if rec["key_cricinfo"]:
            with_cricinfo += 1
        rows.append((rec["identifier"], rec["name"], rec["unique_name"],
                     rec["key_cricinfo"], rec["key_cricinfo_2"]))

    conn.executemany(
        "INSERT INTO people(identifier, name, unique_name, key_cricinfo, key_cricinfo_2) "
        "VALUES(?,?,?,?,?) "
        "ON CONFLICT(identifier) DO UPDATE SET "
        "name=excluded.name, unique_name=excluded.unique_name, "
        "key_cricinfo=excluded.key_cricinfo, key_cricinfo_2=excluded.key_cricinfo_2",
        rows,
    )
    set_meta(conn, "register_downloaded_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    log.info("register loaded: %d people (%d with key_cricinfo)", len(rows), with_cricinfo)
    return len(rows)

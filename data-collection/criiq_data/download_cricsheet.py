from __future__ import annotations

import datetime as dt

from . import http
from .config import RAW_DIR, SETTINGS, CricsheetSource, enabled_sources, ensure_dirs
from .db import get_meta, set_meta
from .logging_utils import get_logger

log = get_logger("cricsheet")


def _fingerprint(resp_headers) -> str:
    return f"{resp_headers.get('Last-Modified','')}|{resp_headers.get('Content-Length','')}"


def download_source(conn, src: CricsheetSource, *, force: bool = False) -> dict:
    ensure_dirs()
    dest = RAW_DIR / src.filename
    meta_key = f"cricsheet_fp::{src.filename}"
    prev_fp = get_meta(conn, meta_key)

    if dest.exists() and not force:
        h = http.head(src.url, delay_s=SETTINGS.cricsheet_delay_s)
        if h is not None and h.ok:
            new_fp = _fingerprint(h.headers)
            if new_fp and new_fp == prev_fp:
                log.info("%s unchanged (skip)", src.filename)
                return {"source": src.label, "status": "unchanged", "path": str(dest)}

    log.info("downloading %s …", src.filename)
    resp = http.get(src.url, delay_s=SETTINGS.cricsheet_delay_s, stream=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    total = 0
    with open(tmp, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            if chunk:
                fh.write(chunk)
                total += len(chunk)
    tmp.replace(dest)

    set_meta(conn, meta_key, _fingerprint(resp.headers))
    set_meta(conn, f"cricsheet_downloaded_at::{src.filename}",
             dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    log.info("downloaded %s (%.1f MB)", src.filename, total / 1e6)
    return {"source": src.label, "status": "downloaded", "bytes": total, "path": str(dest)}


def download_all(conn, *, force: bool = False) -> list[dict]:
    results = []
    for src in enabled_sources():
        try:
            results.append(download_source(conn, src, force=force))
        except Exception as exc:
            log.error("failed to download %s: %s", src.filename, exc)
            results.append({"source": src.label, "status": "error", "error": str(exc)})
    return results

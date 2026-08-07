from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from . import http
from .config import CACHE_DIR, SETTINGS
from .logging_utils import get_logger
from .styles import is_cricket_role

log = get_logger("cricinfo")

_ATHLETE_API = "https://core.espnuk.org/v2/sports/cricket/athletes/{id}"
_CACHE = CACHE_DIR / "cricinfo" / "athletes.parquet"


def _load_cache() -> dict[str, dict]:
    if _CACHE.exists():
        try:
            df = pd.read_parquet(_CACHE)
            return {str(r["key_cricinfo"]): json.loads(r["payload"])
                    for _, r in df.iterrows()}
        except Exception as exc:
            log.warning("could not read cricinfo cache: %s", exc)
    return {}


def _save_cache(cache: dict[str, dict]) -> None:
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        [{"key_cricinfo": k, "payload": json.dumps(v)} for k, v in cache.items()])
    df.to_parquet(_CACHE, index=False)


def fetch_athlete(key_cricinfo: str) -> dict | None:
    try:
        resp = http.get(_ATHLETE_API.format(id=key_cricinfo),
                        delay_s=SETTINGS.cricinfo_delay_s, timeout=30)
        data = resp.json()
    except Exception as exc:
        log.debug("cricinfo fetch failed for %s: %s", key_cricinfo, exc)
        return None

    dob = data.get("dateOfBirth")
    if dob:
        dob = str(dob)[:10]
    role = data.get("position", {}).get("name") if isinstance(data.get("position"), dict) else None
    if role and not is_cricket_role(role):
        # Defensive check -- Wikidata's P413 (styles.seed_from_wikidata) is the confirmed source, not this API.
        role = None
    return {
        "date_of_birth": dob,
        "nationality": (data.get("citizenship") or data.get("nationality")),
        "role": role,
        "batting_hand": data.get("style", [{}])[0].get("description")
            if isinstance(data.get("style"), list) and data.get("style") else None,
    }


def enrich_players(conn, limit: int | None = None, refetch: bool = False) -> dict:
    where = "key_cricinfo IS NOT NULL AND key_cricinfo != ''"
    if not refetch:
        where += " AND (date_of_birth IS NULL OR role IS NULL)"
    q = f"SELECT player_id, key_cricinfo FROM players WHERE {where}"
    if limit:
        q += f" LIMIT {int(limit)}"
    targets = conn.execute(q).fetchall()
    if not targets:
        log.info("cricinfo enrichment: nothing to do")
        return {"attempted": 0, "enriched": 0}

    cache = _load_cache()
    enriched = attempted = 0
    for row in targets:
        key = str(row["key_cricinfo"])
        attempted += 1
        meta = cache.get(key) if not refetch else None
        if meta is None:
            meta = fetch_athlete(key)
            if meta is None:
                continue
            cache[key] = meta
        if any(meta.values()):
            conn.execute(
                "UPDATE players SET date_of_birth=COALESCE(?, date_of_birth), "
                "nationality=COALESCE(?, nationality), role=COALESCE(?, role), "
                "batting_hand=COALESCE(?, batting_hand) WHERE player_id=?",
                (meta.get("date_of_birth"), meta.get("nationality"),
                 meta.get("role"), meta.get("batting_hand"), row["player_id"]))
            enriched += 1
    conn.commit()
    _save_cache(cache)
    log.info("cricinfo enrichment: %d attempted, %d enriched (cache=%d)",
             attempted, enriched, len(cache))
    return {"attempted": attempted, "enriched": enriched, "as_of":
            dt.datetime.now().isoformat(timespec="seconds")}

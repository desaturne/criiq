from __future__ import annotations

import datetime as dt

import pandas as pd

from .config import SETTINGS, enabled_sources
from .db import set_meta
from .logging_utils import get_logger
from .overrides import overrides_map
from .rankings import current_rank, ranked_ids
from .styles import classify_bowling

log = get_logger("registry")

PHASE_BANDS = {
    "batter": (23, 33, 37),
    "pace": (22, 30, 34),
    "spin": (23, 35, 39),
    "keeper": (23, 34, 37),
    "allrounder": (23, 32, 36),
}


def _category(role, bowling_style) -> str:
    r = (role or "").lower()
    if "keeper" in r or r == "wk":
        return "keeper"
    if "all" in r:
        return "allrounder"
    bucket = classify_bowling(bowling_style)
    if bucket:
        return bucket
    if "bowl" in r:
        return "spin"
    return "batter"


def _career_phase(age, cat):
    if age is None:
        return None
    e, p, x = PHASE_BANDS.get(cat, PHASE_BANDS["batter"])
    if age < e:
        return "EMERGING"
    if age < p:
        return "PEAK"
    if age < x:
        return "EXPERIENCED"
    return "DECLINING"


def _age_advisory(age, cat) -> int:
    if age is None:
        return 0
    thr = SETTINGS.age_advisory_pace if cat == "pace" else SETTINGS.age_advisory_default
    return 1 if age >= thr else 0


def _status(is_ranked, days_since) -> str:
    if is_ranked:
        return "ACTIVE"
    if days_since <= SETTINGS.active_window_days:
        return "ACTIVE"
    if days_since > SETTINGS.inactive_window_days:
        return "INACTIVE"
    return "UNKNOWN"


def _players_meta(conn) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT player_id, cricsheet_identifier, canonical_name, key_cricinfo, "
        "nationality, role, derived_role, date_of_birth, bowling_style, batting_hand "
        "FROM players").fetchall()
    return {r["cricsheet_identifier"]: dict(r) for r in rows if r["cricsheet_identifier"]}


def build_registry_for_format(conn, fmt: str) -> int:
    apps = pd.read_sql_query(
        "SELECT mp.match_id, mp.player_name, mp.team, m.date, m.team1, m.team2 "
        "FROM match_players mp JOIN matches m ON mp.match_id = m.match_id "
        "WHERE m.format = ?", conn, params=(fmt,))
    if apps.empty:
        log.info("registry %s: no appearances", fmt)
        return 0

    idmap = pd.read_sql_query("SELECT player_name, identifier FROM identifier_map", conn)
    apps = apps.merge(idmap, on="player_name", how="left").dropna(subset=["identifier"])
    apps["date"] = pd.to_datetime(apps["date"], errors="coerce")
    apps = apps.dropna(subset=["date"])
    if apps.empty:
        return 0
    apps["opponent"] = apps.apply(
        lambda r: r["team2"] if r["team"] == r["team1"] else r["team1"], axis=1)

    meta = _players_meta(conn)
    ranked = ranked_ids(conn, fmt)
    overrides = overrides_map(conn, fmt)
    as_of = apps["date"].max()
    now = dt.datetime.now().isoformat(timespec="seconds")

    last_idx = apps.sort_values("date").groupby("identifier").tail(1).set_index("identifier")

    rows = []
    active = inactive = retired = advisories = 0
    for ident, last in last_idx.iterrows():
        pm = meta.get(ident)
        if not pm:
            continue
        pid = pm["player_id"]
        last_date = last["date"].date()
        days_since = (as_of.date() - last_date).days
        recall = 1 if days_since > SETTINGS.recall_flag_days else 0

        dob = pm.get("date_of_birth")
        age = None
        if dob:
            try:
                age = round((last_date - dt.date.fromisoformat(dob)).days / 365.25, 1)
            except ValueError:
                age = None

        cat = _category(pm.get("role") or pm.get("derived_role"), pm.get("bowling_style"))
        phase = _career_phase(age, cat)
        advisory = _age_advisory(age, cat)
        is_ranked = pid in ranked
        status = _status(is_ranked, days_since)
        rk = current_rank(conn, pid, fmt) if is_ranked else None

        retired_formats = None
        retirement_date = None
        ov = overrides.get(pid)
        if ov:
            status = ov["status"]
            retirement_date = ov["date"]
            if status == "RETIRED_FORMAT":
                retired_formats = fmt

        active += status == "ACTIVE"
        inactive += status == "INACTIVE"
        retired += status in ("RETIRED_ALL", "RETIRED_FORMAT")
        advisories += advisory

        rows.append((
            pid, fmt, status, retired_formats, retirement_date,
            last_date.isoformat(), last["opponent"], days_since,
            dob, age, phase,
            pm.get("role") or pm.get("derived_role"),
            pm.get("bowling_style"), pm.get("batting_hand"), pm.get("nationality"),
            recall, advisory, rk["rank"] if rk else None, rk["rating"] if rk else None, now,
        ))

    conn.executemany(
        "INSERT INTO player_registry(player_id, format, retirement_status, "
        "retired_formats, retirement_date, last_appearance_date, "
        "last_appearance_opponent, days_since_last_appearance, date_of_birth, "
        "age_at_last_match, career_phase, role, bowling_style, batting_hand, "
        "nationality, recall_flag, age_advisory, icc_rank, icc_rating, "
        "registry_last_updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id, format) DO UPDATE SET "
        "retirement_status=excluded.retirement_status, "
        "retired_formats=excluded.retired_formats, "
        "retirement_date=excluded.retirement_date, "
        "last_appearance_date=excluded.last_appearance_date, "
        "last_appearance_opponent=excluded.last_appearance_opponent, "
        "days_since_last_appearance=excluded.days_since_last_appearance, "
        "age_at_last_match=excluded.age_at_last_match, career_phase=excluded.career_phase, "
        "role=excluded.role, recall_flag=excluded.recall_flag, "
        "age_advisory=excluded.age_advisory, icc_rank=excluded.icc_rank, "
        "icc_rating=excluded.icc_rating, registry_last_updated=excluded.registry_last_updated",
        rows,
    )
    conn.commit()
    log.info("registry %s: %d players (as-of %s) | active=%d inactive=%d retired=%d recall=%d age-advisory=%d ranked=%d",
             fmt, len(rows), as_of.date(), active, inactive, retired,
             sum(r[15] for r in rows), advisories, len(ranked))
    return len(rows)


def build_registry(conn) -> dict:
    formats = sorted({s.fmt for s in enabled_sources()})
    out = {}
    for fmt in formats:
        out[fmt] = build_registry_for_format(conn, fmt)
    set_meta(conn, "registry_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out

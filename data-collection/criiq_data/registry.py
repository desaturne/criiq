from __future__ import annotations

import datetime as dt

import pandas as pd

from .config import SETTINGS, enabled_sources
from .db import set_meta
from .logging_utils import get_logger

log = get_logger("registry")


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
    as_of = apps["date"].max()
    now = dt.datetime.now().isoformat(timespec="seconds")

    last_idx = apps.sort_values("date").groupby("identifier").tail(1).set_index("identifier")

    rows = []
    for ident, last in last_idx.iterrows():
        pm = meta.get(ident)
        if not pm:
            continue
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

        rows.append((
            pm["player_id"], fmt, "UNKNOWN", None, None,
            last_date.isoformat(), last["opponent"], days_since,
            dob, age, None,
            pm.get("role") or pm.get("derived_role"),
            pm.get("bowling_style"), pm.get("batting_hand"), pm.get("nationality"),
            recall, 0, now,
        ))

    conn.executemany(
        "INSERT INTO player_registry(player_id, format, retirement_status, "
        "retired_formats, retirement_date, last_appearance_date, "
        "last_appearance_opponent, days_since_last_appearance, date_of_birth, "
        "age_at_last_match, career_phase, role, bowling_style, batting_hand, "
        "nationality, recall_flag, age_advisory, registry_last_updated) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id, format) DO UPDATE SET "
        "last_appearance_date=excluded.last_appearance_date, "
        "last_appearance_opponent=excluded.last_appearance_opponent, "
        "days_since_last_appearance=excluded.days_since_last_appearance, "
        "age_at_last_match=excluded.age_at_last_match, role=excluded.role, "
        "recall_flag=excluded.recall_flag, registry_last_updated=excluded.registry_last_updated",
        rows,
    )
    conn.commit()
    log.info("registry %s: %d players (as-of %s, %d recall-flagged)",
             fmt, len(rows), as_of.date(), sum(r[15] for r in rows))
    return len(rows)


def build_registry(conn) -> dict:
    formats = sorted({s.fmt for s in enabled_sources()})
    out = {}
    for fmt in formats:
        out[fmt] = build_registry_for_format(conn, fmt)
    set_meta(conn, "registry_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out

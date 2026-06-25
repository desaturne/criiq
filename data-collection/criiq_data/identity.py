from __future__ import annotations

import re
import uuid

import pandas as pd

from .config import SETTINGS
from .logging_utils import get_logger

log = get_logger("identity")

_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")

_VENUE_ALIASES = {
    "brabourne stadium, mumbai": "Brabourne Stadium",
    "wankhede stadium, mumbai": "Wankhede Stadium",
    "m chinnaswamy stadium": "M Chinnaswamy Stadium",
    "m.chinnaswamy stadium": "M Chinnaswamy Stadium",
    "punjab cricket association stadium, mohali": "PCA Stadium, Mohali",
    "punjab cricket association is bindra stadium, mohali": "PCA Stadium, Mohali",
}


def player_id_for(identifier: str) -> str:
    return str(uuid.uuid5(_NS, f"cricsheet:{identifier}"))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _derived_roles(conn) -> dict[str, str]:
    idmap = pd.read_sql_query("SELECT player_name, identifier FROM identifier_map", conn)
    if idmap.empty:
        return {}

    bat = pd.read_sql_query(
        "SELECT striker AS player_name, COUNT(*) AS balls_faced "
        "FROM deliveries WHERE wides=0 GROUP BY striker", conn)
    bowl = pd.read_sql_query(
        "SELECT bowler AS player_name, COUNT(*) AS balls_bowled "
        "FROM deliveries WHERE wides=0 AND noballs=0 GROUP BY bowler", conn)

    m = idmap.merge(bat, on="player_name", how="left").merge(bowl, on="player_name", how="left")
    m["balls_faced"] = m["balls_faced"].fillna(0)
    m["balls_bowled"] = m["balls_bowled"].fillna(0)
    agg = m.groupby("identifier")[["balls_faced", "balls_bowled"]].sum()

    roles = {}
    for ident, row in agg.iterrows():
        bf, bb = row["balls_faced"], row["balls_bowled"]
        if bb >= 60 and bf >= 60:
            roles[ident] = "all-rounder"
        elif bb >= 60:
            roles[ident] = "bowler"
        elif bf >= 1:
            roles[ident] = "batter"
        else:
            roles[ident] = "unknown"
    return roles


def resolve_players(conn) -> dict:
    identifiers = [r["identifier"] for r in conn.execute(
        "SELECT DISTINCT im.identifier FROM identifier_map im "
        "JOIN match_players mp ON mp.player_name = im.player_name")]
    if not identifiers:
        log.warning("no player identifiers found — run ingest first")
        return {"players": 0}

    people = {r["identifier"]: r for r in conn.execute(
        "SELECT identifier, name, unique_name, key_cricinfo FROM people")}
    roles = _derived_roles(conn)

    name_variants: dict[str, str] = {}
    for r in conn.execute(
            "SELECT identifier, player_name FROM identifier_map ORDER BY player_name"):
        name_variants.setdefault(r["identifier"], r["player_name"])

    matched = with_cricinfo = 0
    rows = []
    for ident in identifiers:
        p = people.get(ident)
        key_cricinfo = (p["key_cricinfo"] if p else None) or None
        canonical = (p["unique_name"] or p["name"]) if p else name_variants.get(ident)
        unique = (p["unique_name"] if p else None) or canonical
        if p:
            matched += 1
        if key_cricinfo:
            with_cricinfo += 1
            method = "register"
        elif p:
            method = "register_no_cricinfo"
        else:
            method = "cricsheet_only"
        rows.append((
            player_id_for(ident), ident, canonical, unique, key_cricinfo,
            roles.get(ident, "unknown"), method, 0 if key_cricinfo else 1,
        ))

    conn.executemany(
        "INSERT INTO players(player_id, cricsheet_identifier, canonical_name, "
        "unique_name, key_cricinfo, derived_role, resolution_method, needs_review) "
        "VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id) DO UPDATE SET "
        "canonical_name=excluded.canonical_name, unique_name=excluded.unique_name, "
        "key_cricinfo=excluded.key_cricinfo, derived_role=excluded.derived_role, "
        "resolution_method=excluded.resolution_method, needs_review=excluded.needs_review",
        rows,
    )
    conn.execute(
        "DELETE FROM players WHERE cricsheet_identifier NOT IN ("
        "SELECT DISTINCT im.identifier FROM identifier_map im "
        "JOIN match_players mp ON mp.player_name = im.player_name)")
    conn.commit()
    log.info("players resolved: %d total, %d in register, %d with key_cricinfo, "
             "%d need review", len(rows), matched, with_cricinfo, len(rows) - with_cricinfo)
    return {"players": len(rows), "in_register": matched, "with_cricinfo": with_cricinfo,
            "needs_review": len(rows) - with_cricinfo}


def fuzzy_match_name(name: str, candidates: list[str]) -> tuple[str | None, int]:
    from rapidfuzz import process, fuzz
    if not candidates:
        return None, 0
    match = process.extractOne(name, candidates, scorer=fuzz.WRatio)
    if match and match[1] >= SETTINGS.fuzzy_threshold:
        return match[0], int(match[1])
    return None, int(match[1]) if match else 0


def normalise_venues(conn) -> dict:
    raws = [r["venue_raw"] for r in
            conn.execute("SELECT DISTINCT venue_raw FROM matches WHERE venue_raw IS NOT NULL")]
    rows = []
    for raw in raws:
        key = raw.strip().lower()
        if key in _VENUE_ALIASES:
            canonical = _VENUE_ALIASES[key]
        else:
            canonical = raw.split(",")[0].strip()
        rows.append((raw, _slug(canonical), canonical))

    conn.executemany(
        "INSERT INTO venues(venue_raw, venue_id, canonical_name) VALUES(?,?,?) "
        "ON CONFLICT(venue_raw) DO UPDATE SET "
        "venue_id=excluded.venue_id, canonical_name=excluded.canonical_name",
        rows,
    )
    conn.execute(
        "UPDATE matches SET venue_id = (SELECT venue_id FROM venues "
        "WHERE venues.venue_raw = matches.venue_raw) WHERE venue_raw IS NOT NULL")
    conn.commit()
    log.info("venues normalised: %d raw -> %d canonical",
             len(rows), len({c for _, _, c in rows}))
    return {"venues_raw": len(rows), "venues_canonical": len({c for _, _, c in rows})}


def run(conn) -> dict:
    out = resolve_players(conn)
    out.update(normalise_venues(conn))
    return out

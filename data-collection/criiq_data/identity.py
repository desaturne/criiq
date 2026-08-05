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
    # the fallback below canonicalizes on raw.split(",")[0], which merges
    # different grounds that share a bare "County Ground"/"National Stadium"
    # prefix, so each is listed here with its own distinct canonical name.
    "county ground, bristol": "County Ground, Bristol",
    "county ground, chelmsford": "County Ground, Chelmsford",
    "county ground, derby": "County Ground, Derby",
    "county ground, hove": "County Ground, Hove",
    "county ground, new road, worcester": "County Ground, New Road, Worcester",
    "county ground, northampton": "County Ground, Northampton",
    # same ground as "The Cooper Associates County Ground" (Somerset's
    # sponsored name), pointed at that canonical name explicitly.
    "county ground, taunton": "The Cooper Associates County Ground",
    # raw string doesn't say which English county ground, so it's labelled
    # unresolved rather than guessed.
    "county ground": "County Ground (ground unspecified)",
    "national stadium, hamilton": "National Stadium, Hamilton",
    "national stadium, karachi": "National Stadium, Karachi",
    "national stadium": "National Stadium (ground unspecified)",
}


def player_id_for(identifier: str, gender: str | None = None) -> str:
    """deterministic id from a Cricsheet registry identifier. pass `gender`
    only when `identifier` is confirmed to span more than one gender's
    matches (see `_colliding_identifiers`); leave `None` for the rest so
    their id stays unchanged.
    """
    suffix = f":{gender}" if gender else ""
    return str(uuid.uuid5(_NS, f"cricsheet:{identifier}{suffix}"))


def player_id_map(conn) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """two lookup structures for resolving cricsheet identifiers to
    player_ids, instead of a plain `{identifier: player_id}` dict (which
    would pick an arbitrary one of two people for colliding identifiers):

      * `unambiguous`: identifier -> player_id, for identifiers that only
        ever appear under one gender.
      * `split`: (identifier, gender) -> player_id, for the rare identifiers
        that span more than one gender.
    """
    unambiguous: dict[str, str] = {}
    split: dict[tuple[str, str], str] = {}
    for r in conn.execute("SELECT cricsheet_identifier, gender, player_id FROM players"):
        if r["gender"] is None:
            unambiguous[r["cricsheet_identifier"]] = r["player_id"]
        else:
            split[(r["cricsheet_identifier"], r["gender"])] = r["player_id"]
    return unambiguous, split


def resolve_player_ids(conn, identifiers: pd.Series, genders: pd.Series | None = None) -> pd.Series:
    """vectorized counterpart to `player_id_map`: resolves `identifiers` to
    player_id, falling back to `(identifier, gender)` for the rare
    identifiers that collide across genders.

    unmatched entries are `None`, never NaN: `pd.Series.map` misses produce
    `nan`, which is truthy in Python, so a caller's `if not pid: continue`
    guard would otherwise silently let unmatched rows through.
    """
    unambiguous, split = player_id_map(conn)
    result = identifiers.map(unambiguous)
    if genders is not None and split:
        missing = result.isna() & identifiers.notna()
        if missing.any():
            paired = pd.Series(
                list(zip(identifiers[missing], genders[missing])), index=identifiers[missing].index)
            result.loc[missing] = paired.map(split)
    return result.astype(object).where(result.notna(), None)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _derived_roles(conn) -> dict[tuple[str, str | None], str]:
    """(identifier, gender) -> role, from ball counts in each player's most recent `impact_recent_matches`, not career totals.
    gender-scoped so the rare identifier reused across two different people doesn't blend their roles together.
    """
    idmap = pd.read_sql_query(
        "SELECT im.player_name, im.identifier, m.gender FROM identifier_map im "
        "JOIN match_players mp ON mp.player_name = im.player_name "
        "JOIN matches m ON m.match_id = mp.match_id", conn).drop_duplicates()
    if idmap.empty:
        return {}

    # per-match, not lifetime, so recency can be scoped per player below.
    bat = pd.read_sql_query(
        "SELECT d.match_id, d.striker AS player_name, m.gender, m.date, COUNT(*) AS balls_faced "
        "FROM deliveries d JOIN matches m ON m.match_id = d.match_id "
        "WHERE d.wides=0 GROUP BY d.match_id, d.striker, m.gender, m.date", conn)
    bowl = pd.read_sql_query(
        "SELECT d.match_id, d.bowler AS player_name, m.gender, m.date, COUNT(*) AS balls_bowled "
        "FROM deliveries d JOIN matches m ON m.match_id = d.match_id "
        "WHERE d.wides=0 AND d.noballs=0 GROUP BY d.match_id, d.bowler, m.gender, m.date", conn)

    # recent N matches PLAYED (match_players), not N matches with a recorded ball -- a DNB still counts as recent.
    appearances = pd.read_sql_query(
        "SELECT mp.player_name, m.gender, mp.match_id, m.date "
        "FROM match_players mp JOIN matches m ON m.match_id = mp.match_id", conn).drop_duplicates()
    idapp = idmap.merge(appearances, on=["player_name", "gender"], how="inner")
    recent_keys = (idapp.sort_values("date", ascending=False)
                   .groupby(["identifier", "gender"]).head(SETTINGS.impact_recent_matches)
                   [["identifier", "gender", "match_id"]].drop_duplicates())

    bat_id = idmap.merge(bat, on=["player_name", "gender"], how="inner") \
                  .merge(recent_keys, on=["identifier", "gender", "match_id"], how="inner")
    bowl_id = idmap.merge(bowl, on=["player_name", "gender"], how="inner") \
                   .merge(recent_keys, on=["identifier", "gender", "match_id"], how="inner")

    agg_bat = bat_id.groupby(["identifier", "gender"])["balls_faced"].sum()
    agg_bowl = bowl_id.groupby(["identifier", "gender"])["balls_bowled"].sum()
    agg = pd.concat([agg_bat, agg_bowl], axis=1).fillna(0)

    roles = {}
    for (ident, gender), row in agg.iterrows():
        bf, bb = row["balls_faced"], row["balls_bowled"]
        if bb >= 60 and bf >= 60:
            role = "all-rounder"
        elif bb >= 60:
            role = "bowler"
        elif bf >= 1:
            role = "batter"
        else:
            role = "unknown"
        roles[(ident, gender)] = role
    return roles


def _colliding_identifiers(conn) -> dict[str, list[str]]:
    """identifier -> sorted list of the >1 distinct genders it appears under
    in Cricsheet's own registry data. rare: most identifiers aren't in this
    dict at all, since they only ever appear under one gender.
    """
    rows = conn.execute(
        "SELECT DISTINCT im.identifier, m.gender FROM identifier_map im "
        "JOIN match_players mp ON mp.player_name = im.player_name "
        "JOIN matches m ON m.match_id = mp.match_id").fetchall()
    by_ident: dict[str, set[str]] = {}
    for r in rows:
        by_ident.setdefault(r["identifier"], set()).add(r["gender"])
    return {ident: sorted(genders) for ident, genders in by_ident.items() if len(genders) > 1}


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
    colliding = _colliding_identifiers(conn)

    name_variants: dict[str, str] = {}
    for r in conn.execute(
            "SELECT identifier, player_name FROM identifier_map ORDER BY player_name"):
        name_variants.setdefault(r["identifier"], r["player_name"])

    matched = with_cricinfo = split_identifiers = 0
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

        # a colliding identifier mints one row per gender; everyone else
        # keeps a single gender=NULL row.
        genders_for_ident = colliding.get(ident)
        if genders_for_ident:
            split_identifiers += 1
        else:
            genders_for_ident = [None]
        for gender in genders_for_ident:
            role_key = (ident, gender) if gender else next(
                (k for k in roles if k[0] == ident), (ident, None))
            rows.append((
                player_id_for(ident, gender), ident, gender, canonical, unique, key_cricinfo,
                roles.get(role_key, "unknown"), method, 0 if key_cricinfo else 1,
            ))

    conn.executemany(
        "INSERT INTO players(player_id, cricsheet_identifier, gender, canonical_name, "
        "unique_name, key_cricinfo, derived_role, resolution_method, needs_review) "
        "VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id) DO UPDATE SET "
        "canonical_name=excluded.canonical_name, unique_name=excluded.unique_name, "
        "key_cricinfo=excluded.key_cricinfo, derived_role=excluded.derived_role, "
        "resolution_method=excluded.resolution_method, needs_review=excluded.needs_review",
        rows,
    )
    # removes players no longer present, and the old gender-agnostic id of
    # any identifier just split into per-gender ids above.
    valid_ids = tuple(row[0] for row in rows)
    placeholders = ",".join("?" * len(valid_ids)) if valid_ids else "NULL"
    conn.execute(f"DELETE FROM players WHERE player_id NOT IN ({placeholders})", valid_ids)
    conn.commit()
    log.info("players resolved: %d total, %d in register, %d with key_cricinfo, "
             "%d need review, %d identifiers split by gender",
             len(rows), matched, with_cricinfo, len(rows) - with_cricinfo, split_identifiers)
    return {"players": len(rows), "in_register": matched, "with_cricinfo": with_cricinfo,
            "needs_review": len(rows) - with_cricinfo, "split_identifiers": split_identifiers}


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

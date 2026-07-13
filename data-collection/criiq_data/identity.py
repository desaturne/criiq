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


def player_id_for(identifier: str, gender: str | None = None) -> str:
    """Deterministic id from a Cricsheet registry identifier. `gender` must
    be passed when (and only when) `identifier` is confirmed to span more
    than one gender's matches (see `_colliding_identifiers`) -- a real,
    if rare, quirk in Cricsheet's own upstream registry, not a bug in this
    codebase's matching, where the same identifier gets reused across two
    genuinely different people. Left `None` for the overwhelming majority of
    identifiers, which only ever appear under one gender, so their id is
    identical to before this parameter existed -- no downstream rebuild
    needed for them.
    """
    suffix = f":{gender}" if gender else ""
    return str(uuid.uuid5(_NS, f"cricsheet:{identifier}{suffix}"))


def player_id_map(conn) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """Two lookup structures every builder that resolves cricsheet identifiers
    to player_ids should use instead of a plain `{identifier: player_id}`
    dict (which silently picks an arbitrary one of two real people for the
    handful of identifiers Cricsheet's own registry reuses across genders):

      * `unambiguous`: identifier -> player_id, for the ~99.5% of
        identifiers that only ever appear under one gender -- check this
        first, no gender needed.
      * `split`: (identifier, gender) -> player_id, for the rare identifiers
        that do span more than one gender -- only reachable when the
        caller's row actually carries a gender to disambiguate with.
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
    """Vectorized counterpart to `player_id_map` for pandas-merge-style
    builders: `identifiers` resolved to player_id, falling back to
    `(identifier, gender)` (using the aligned `genders` series) only for the
    rare identifiers that need it. Omit `genders` only when the caller
    already knows none of its identifiers can possibly collide.

    Unmatched entries are `None`, never NaN -- `pd.Series.map` on an object
    dtype produces `float('nan')` for misses, and `nan` is truthy in Python
    (`bool(nan) is True`), so a caller's usual `if not pid: continue` guard
    (the same idiom a plain dict's `.get()` has always supported) would
    silently let unmatched rows through instead of skipping them.
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
    """(identifier, gender) -> role. Gender-scoped (not just identifier) so
    the rare identifier Cricsheet's own registry reuses across two genuinely
    different people doesn't blend one person's batting with the other's
    bowling into a single, meaningless combined role.
    """
    idmap = pd.read_sql_query(
        "SELECT im.player_name, im.identifier, m.gender FROM identifier_map im "
        "JOIN match_players mp ON mp.player_name = im.player_name "
        "JOIN matches m ON m.match_id = mp.match_id", conn).drop_duplicates()
    if idmap.empty:
        return {}

    bat = pd.read_sql_query(
        "SELECT d.striker AS player_name, m.gender, COUNT(*) AS balls_faced "
        "FROM deliveries d JOIN matches m ON m.match_id = d.match_id "
        "WHERE d.wides=0 GROUP BY d.striker, m.gender", conn)
    bowl = pd.read_sql_query(
        "SELECT d.bowler AS player_name, m.gender, COUNT(*) AS balls_bowled "
        "FROM deliveries d JOIN matches m ON m.match_id = d.match_id "
        "WHERE d.wides=0 AND d.noballs=0 GROUP BY d.bowler, m.gender", conn)

    m = idmap.merge(bat, on=["player_name", "gender"], how="left") \
             .merge(bowl, on=["player_name", "gender"], how="left")
    m["balls_faced"] = m["balls_faced"].fillna(0)
    m["balls_bowled"] = m["balls_bowled"].fillna(0)
    agg = m.groupby(["identifier", "gender"])[["balls_faced", "balls_bowled"]].sum()

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
    in Cricsheet's own per-match registry data. Confirmed real (not a
    matching bug in this codebase -- see `ingest._parse_info`, which reads
    these identifiers verbatim from each match file's own `registry,people`
    rows) but rare: identifiers not in this dict (the overwhelming majority)
    only ever appear under one gender.
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

        # A colliding identifier mints one row PER gender (each a distinct,
        # stable id via player_id_for(ident, gender)); everyone else keeps a
        # single gender=NULL row with exactly the id they've always had.
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
    # Removes players for identifiers no longer present at all, AND the OLD
    # gender-agnostic id of any identifier that has just been split into
    # per-gender ids above (that id is deliberately not in `rows` anymore).
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

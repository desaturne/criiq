"""finalized playing role (batter/bowler/all-rounder) + wicket-keeper flag.

`players.derived_role` (identity.py) classifies from ball counts alone,
which conflates batting all-rounders with tail-batting specialist bowlers;
batting position disambiguates the two. wicket-keeper status has no signal
in the ball-by-ball data, so it comes from Wikipedia squad-page lookups
merged in via `merge_external_roles`, matched strictly by `key_cricinfo`.
"""
from __future__ import annotations

import csv
import datetime as dt

import pandas as pd

from .config import enabled_sources
from .db import set_meta
from .logging_utils import get_logger

log = get_logger("role_finalize")

# a derived all-rounder batting this deep in the order is really a tail-end
# bowler, not a genuine batting all-rounder.
TAIL_POSITION_THRESHOLD = 8


def compute_batting_positions(conn, fmt: str) -> pd.DataFrame:
    """median batting position + innings-batted count, per (cricsheet
    identifier, gender). gender-scoped since a handful of Cricsheet
    identifiers are reused across two different people (see identity.py).
    """
    deliv = pd.read_sql_query(
        "SELECT d.match_id, d.innings, d.over, d.ball_in_over, d.striker, d.non_striker, "
        "m.gender FROM deliveries d JOIN matches m ON d.match_id = m.match_id "
        "WHERE m.format = ? AND m.team_type = 'international'",
        conn, params=(fmt,))
    if deliv.empty:
        return pd.DataFrame(columns=["identifier", "gender", "batting_position_median", "innings_batted"])

    deliv = deliv.sort_values(["match_id", "innings", "over", "ball_in_over"]).reset_index(drop=True)
    order = deliv.index.to_series()
    long = pd.concat([
        pd.DataFrame({"match_id": deliv["match_id"], "innings": deliv["innings"],
                      "player_name": deliv["striker"], "gender": deliv["gender"], "o": order}),
        pd.DataFrame({"match_id": deliv["match_id"], "innings": deliv["innings"],
                      "player_name": deliv["non_striker"], "gender": deliv["gender"], "o": order}),
    ])
    first = long.groupby(["match_id", "innings", "player_name"], as_index=False).agg(
        o=("o", "min"), gender=("gender", "first"))
    first["position"] = first.groupby(["match_id", "innings"])["o"].rank("first").astype(int)

    name2ident = {r["player_name"]: r["identifier"]
                  for r in conn.execute("SELECT player_name, identifier FROM identifier_map")}
    first["identifier"] = first["player_name"].map(name2ident)
    first = first.dropna(subset=["identifier"])

    return (first.groupby(["identifier", "gender"])["position"]
            .agg(batting_position_median="median", innings_batted="count")
            .reset_index())


def _classify(derived_role: str | None, position_median: float | None) -> str:
    role = derived_role or "unknown"
    if role == "all-rounder" and pd.notna(position_median) and position_median >= TAIL_POSITION_THRESHOLD:
        return "bowler"
    return role


def _role_field_keepers(conn) -> set:
    """player_ids whose existing role data (players.role or
    player_styles.playing_role) already says wicket-keeper. excludes
    "goalkeeper", a Wikidata mis-tag seen on a few players.
    """
    keepers = set()
    for q in ("SELECT player_id, role AS r FROM players WHERE role IS NOT NULL",
              "SELECT player_id, playing_role AS r FROM player_styles WHERE playing_role IS NOT NULL"):
        for row in conn.execute(q):
            r = (row["r"] or "").lower()
            if "wicket-keeper" in r or "wicketkeeper" in r or "wk-batsman" in r:
                keepers.add(row["player_id"])
    return keepers


def finalize_local_roles(conn, fmt: str) -> int:
    """local-only pass: refines `derived_role` with batting position, and
    sets `is_keeper` from any existing wicket-keeper role field. the keeper
    flag is merged with MAX so it's never overwritten back down to 0.
    """
    keeper_ids = _role_field_keepers(conn)
    positions = compute_batting_positions(conn, fmt)
    players_df = pd.read_sql_query(
        "SELECT player_id, cricsheet_identifier, gender, derived_role FROM players", conn)
    # merge on (identifier, gender); rows with gender=NULL (never split)
    # fall back to a gender-agnostic merge.
    split_players = players_df[players_df["gender"].notna()]
    unsplit_players = players_df[players_df["gender"].isna()]
    merged_split = split_players.merge(
        positions, left_on=["cricsheet_identifier", "gender"],
        right_on=["identifier", "gender"], how="left")
    merged_unsplit = unsplit_players.drop(columns=["gender"]).merge(
        positions.drop(columns=["gender"]).groupby("identifier", as_index=False).first(),
        left_on="cricsheet_identifier", right_on="identifier", how="left")
    merged = pd.concat([merged_split, merged_unsplit], ignore_index=True)

    now = dt.datetime.now().isoformat(timespec="seconds")
    rows = [
        (r.player_id, fmt, _classify(r.derived_role, r.batting_position_median),
         r.batting_position_median if pd.notna(r.batting_position_median) else None,
         int(r.innings_batted) if pd.notna(r.innings_batted) else 0,
         1 if r.player_id in keeper_ids else 0,
         "local_role_field" if r.player_id in keeper_ids else None,
         "local_derived", now)
        for r in merged.itertuples()
    ]
    conn.executemany(
        "INSERT INTO player_role_final(player_id, format, primary_role, "
        "batting_position_median, innings_batted, is_keeper, keeper_source, role_source, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id, format) DO UPDATE SET "
        "primary_role=excluded.primary_role, "
        "batting_position_median=excluded.batting_position_median, "
        "innings_batted=excluded.innings_batted, "
        # never demote a keeper flag: MAX only ever promotes 0/NULL -> 1.
        "is_keeper=MAX(COALESCE(player_role_final.is_keeper, 0), excluded.is_keeper), "
        "keeper_source=COALESCE(player_role_final.keeper_source, excluded.keeper_source), "
        "role_source=excluded.role_source, updated_at=excluded.updated_at",
        rows)
    conn.commit()
    n_keepers = sum(1 for r in rows if r[5])
    log.info("role_finalize %s: %d players (local pass), %d keepers from role fields", fmt, len(rows), n_keepers)
    return len(rows)


def finalize_all_local(conn) -> dict:
    out = {}
    for fmt in sorted({s.fmt for s in enabled_sources()}):
        out[fmt] = finalize_local_roles(conn, fmt)
    set_meta(conn, "role_finalize_local_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out


def merge_external_roles(conn, records: list[dict], fmt: str) -> dict:
    """merge externally-sourced role records into `player_role_final`.

    matches strictly by `key_cricinfo`; a record with no match is reported
    unmatched rather than dropped or inserted as a new identity (matching by
    raw name could create a duplicate like "S Mandhana" vs "Smriti Mandhana").

    each record: {key_cricinfo, name, is_keeper, primary_role_override,
    bowling_style, confidence, source_url}. `bowling_style` is also merged
    into `player_styles`, without overwriting an existing value there.
    """
    by_cricinfo = {r["key_cricinfo"]: r["player_id"] for r in conn.execute(
        "SELECT key_cricinfo, player_id FROM players WHERE key_cricinfo IS NOT NULL")}

    now = dt.datetime.now().isoformat(timespec="seconds")
    matched_rows = []
    style_rows = []
    unmatched = []
    for rec in records:
        player_id = by_cricinfo.get(rec.get("key_cricinfo"))
        if not player_id:
            unmatched.append(rec)
            continue
        matched_rows.append((
            player_id, fmt, rec.get("primary_role_override"), 1 if rec.get("is_keeper") else 0,
            rec.get("confidence"), rec.get("source_url"), now,
        ))
        if rec.get("bowling_style"):
            style_rows.append((player_id, rec["bowling_style"], "wikipedia_squad", now))

    for player_id, f, role_override, is_keeper, confidence, source_url, ts in matched_rows:
        conn.execute(
            "INSERT INTO player_role_final(player_id, format, primary_role, is_keeper, "
            "keeper_confidence, keeper_source, updated_at) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(player_id, format) DO UPDATE SET "
            "primary_role = COALESCE(excluded.primary_role, player_role_final.primary_role), "
            "is_keeper=excluded.is_keeper, keeper_confidence=excluded.keeper_confidence, "
            "keeper_source=excluded.keeper_source, updated_at=excluded.updated_at",
            (player_id, f, role_override, is_keeper, confidence, source_url, ts))

    for player_id, bowling_style, source, ts in style_rows:
        conn.execute(
            "INSERT INTO player_styles(player_id, bowling_style, source, updated_at) "
            "VALUES(?,?,?,?) ON CONFLICT(player_id) DO UPDATE SET "
            "bowling_style = COALESCE(player_styles.bowling_style, excluded.bowling_style), "
            "updated_at=excluded.updated_at",
            (player_id, bowling_style, source, ts))
        # advanced.py's vs-pace/vs-spin computation reads players.bowling_style,
        # a separate column from player_styles.bowling_style, so both need the backfill
        conn.execute(
            "UPDATE players SET bowling_style = COALESCE(bowling_style, ?) WHERE player_id=?",
            (bowling_style, player_id))

    conn.commit()
    log.info("role_finalize external merge: %d matched, %d unmatched, %d bowling styles",
             len(matched_rows), len(unmatched), len(style_rows))
    return {"matched": len(matched_rows), "unmatched": unmatched, "bowling_styles": len(style_rows)}


def team_candidates(conn, team: str, gender: str = "female") -> pd.DataFrame:
    """players who've appeared for `team`, scoping a squad-page name match
    to a small candidate set instead of matching against all players.
    gender-qualified join since a handful of Cricsheet identifiers are
    reused across two different people (see identity.py).
    """
    return pd.read_sql_query(
        "SELECT DISTINCT p.player_id, p.canonical_name, p.key_cricinfo "
        "FROM match_players mp "
        "JOIN matches m ON mp.match_id = m.match_id "
        "JOIN identifier_map im ON im.player_name = mp.player_name "
        "JOIN players p ON p.cricsheet_identifier = im.identifier "
        "AND (p.gender IS NULL OR p.gender = m.gender) "
        "WHERE mp.team = ? AND m.gender = ? AND m.team_type = 'international'",
        conn, params=(team, gender))


def _surname(name: str) -> str:
    parts = name.strip().split()
    return parts[-1] if parts else ""


def _initials(name: str) -> str:
    parts = name.strip().split()
    return "".join(p[0] for p in parts[:-1]).lower() if len(parts) > 1 else ""


def match_full_name_to_cricsheet(full_name: str, candidates: pd.DataFrame) -> tuple[dict | None, str]:
    """match a "First Last" name (e.g. from a Wikipedia squad table) against
    Cricsheet's "XY Surname" display names for one team's roster.

    plain fuzzy string similarity scores this too low to trust (e.g.
    "Smriti Mandhana" vs "S Mandhana" ~85, below fuzzy_threshold), so this
    matches on surname and disambiguates by leading initial instead.
    """
    surname = _surname(full_name).lower()
    initials = _initials(full_name)
    if not surname or candidates.empty:
        return None, "no_surname"

    candidates = candidates.assign(_surname=candidates["canonical_name"].map(lambda n: _surname(n).lower()))
    same_surname = candidates[candidates["_surname"] == surname]
    if same_surname.empty:
        return None, "no_surname_match_in_team"

    if len(same_surname) == 1:
        cand = same_surname.iloc[0]
        cand_initials = _initials(cand["canonical_name"])
        if initials and cand_initials and cand_initials[0] == initials[0]:
            return cand.to_dict(), "surname+initial"
        return cand.to_dict(), "surname_only"

    for _, cand in same_surname.iterrows():
        cand_initials = _initials(cand["canonical_name"])
        if initials and cand_initials and cand_initials[0] == initials[0]:
            return cand.to_dict(), "surname+initial_disambiguated"
    return None, "ambiguous_surname"


_ROLE_KEYWORDS = (
    ("all-rounder", "all-rounder"), ("all rounder", "all-rounder"),
    ("keeper", "batter"),  # a keeper's batting/bowling capability is "batter"; is_keeper is tracked separately
    ("bowler", "bowler"), ("batter", "batter"), ("batsman", "batter"),
)


def _map_primary_role(role_text: str) -> str | None:
    r = role_text.lower()
    for keyword, mapped in _ROLE_KEYWORDS:
        if keyword in r:
            return mapped
    return None


def _map_bowling_style(role_text: str) -> str | None:
    """coarse pace/spin from the same squad-page role text already fetched
    for role-finalization. returns None (not guessed) when the role text
    doesn't specify a bowling discipline.
    """
    r = role_text.lower()
    if "spin" in r:
        return "spin"
    if "pace" in r or "seam" in r:
        return "pace"
    return None


_CONFIDENCE_BY_METHOD = {
    "surname+initial": 95.0, "surname+initial_disambiguated": 90.0, "surname_only": 75.0,
}


def match_squad_to_roster(conn, team: str, entries: list[dict], source_url: str,
                           gender: str = "female") -> dict:
    """`entries`: [{"name": "Smriti Mandhana", "role": "Batter"}, ...] as read
    off a squad page. returns {"records": [...ready for merge_external_roles...],
    "unmatched": [...names that didn't confidently resolve to this team's roster...]}.
    """
    candidates = team_candidates(conn, team, gender)
    records, unmatched = [], []
    for e in entries:
        match, method = match_full_name_to_cricsheet(e["name"], candidates)
        if not match:
            unmatched.append({**e, "team": team, "reason": method})
            continue
        records.append({
            "key_cricinfo": match["key_cricinfo"], "name": e["name"], "team": team,
            "is_keeper": "keeper" in e["role"].lower(),
            "primary_role_override": _map_primary_role(e["role"]),
            "bowling_style": _map_bowling_style(e["role"]),
            "confidence": _CONFIDENCE_BY_METHOD.get(method, 50.0),
            "source_url": source_url,
        })
    return {"records": records, "unmatched": unmatched}


def load_external_roles_csv(path) -> list[dict]:
    """read `key_cricinfo, name, team, is_keeper, primary_role_override,
    bowling_style, confidence, source_url` rows, the shape
    `merge_external_roles` expects.
    """
    records = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key_cricinfo = (row.get("key_cricinfo") or "").strip() or None
            records.append({
                "key_cricinfo": key_cricinfo,
                "name": row.get("name"),
                "team": row.get("team"),
                "is_keeper": (row.get("is_keeper") or "").strip().lower() in ("1", "true", "yes"),
                "primary_role_override": (row.get("primary_role_override") or "").strip() or None,
                "bowling_style": (row.get("bowling_style") or "").strip() or None,
                "confidence": float(row["confidence"]) if row.get("confidence") else None,
                "source_url": row.get("source_url") or None,
            })
    return records

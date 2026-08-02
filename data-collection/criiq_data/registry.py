from __future__ import annotations

import bisect
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


def _classify(is_ranked: bool, days_since: int,
              selection_rate: float | None) -> tuple[str, str, str]:
    """classify a player's activity status from appearance signals.

    precedence: a current ICC ranking means ACTIVE; a long absence means
    INACTIVE. otherwise selection rate over the recent window separates
    ACTIVE from in-and-out INCONSISTENT players.
    """
    if is_ranked:
        return "ACTIVE", "icc_ranked", "present in current ICC rankings"
    if days_since > SETTINGS.inactive_window_days:
        return "INACTIVE", "stale_no_rank", "no recent appearance and absent from ICC rankings"
    if days_since <= SETTINGS.active_window_days:
        if selection_rate is not None:
            pct = round(100 * selection_rate)
            if selection_rate >= SETTINGS.regular_selection_rate:
                return "ACTIVE", "regular_selection", f"recent and regularly selected ({pct}% of team matches)"
            return "INCONSISTENT", "in_and_out", f"recent but selected in only {pct}% of team matches"
        return "ACTIVE", "recent_appearance", "appeared inside active window"
    return "UNKNOWN", "aging_no_rank", "outside active window but not stale enough for inactive"


def _status(is_ranked, days_since) -> str:
    return _classify(is_ranked, days_since, None)[0]


def _players_meta(conn) -> dict[tuple[str, str | None], dict]:
    """(cricsheet_identifier, gender) -> player row. gender-scoped since a
    handful of Cricsheet identifiers are reused across two different
    people (see identity.py).
    """
    rows = conn.execute(
        "SELECT player_id, cricsheet_identifier, gender, canonical_name, key_cricinfo, "
        "nationality, role, derived_role, date_of_birth, bowling_style, batting_hand "
        "FROM players").fetchall()
    return {(r["cricsheet_identifier"], r["gender"]): dict(r) for r in rows if r["cricsheet_identifier"]}


def build_registry_for_format(conn, fmt: str) -> int:
    apps = pd.read_sql_query(
        "SELECT mp.match_id, mp.player_name, mp.team, m.date, m.team1, m.team2, "
        "m.gender, m.team_type "
        "FROM match_players mp JOIN matches m ON mp.match_id = m.match_id "
        "WHERE m.format = ?", conn, params=(fmt,)
    )
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
    # recency is relative to the most recent match in the data, not wall-clock
    # time, so re-running the same snapshot stays reproducible.
    as_of_date = as_of.date()
    now = dt.datetime.now().isoformat(timespec="seconds")

    # two different questions share this table: "is she still playing" (any
    # competition, `last_idx` below) is broad, but "which country, how
    # regularly" needs international-only rows, since team1/team2 in a
    # domestic fixture is a franchise, not a country.
    apps_intl = apps[apps["team_type"] == "international"]

    # selection-consistency window: compares matches a player was picked for
    # against their team's matches since her first appearance in the window,
    # so a mid-window debutant isn't misread as in-and-out.
    window_start = as_of - pd.Timedelta(days=SETTINGS.selection_window_days)
    win = apps_intl[apps_intl["date"] >= window_start]
    # gender kept alongside identifier in every group key below, see
    # _players_meta's docstring.
    grp = win.groupby(["identifier", "gender"])
    player_win = grp["match_id"].nunique().to_dict()
    first_win = grp["date"].min().to_dict()
    recent_team = (grp["team"].agg(lambda s: s.value_counts().idxmax()).to_dict()
                   if not win.empty else {})
    match_meta = apps_intl.drop_duplicates("match_id")
    match_meta = match_meta[match_meta["date"] >= window_start]
    # team_dates is keyed by (team, gender), not team name alone, since most
    # nations field both a men's and women's side under the same team string
    # and pooling them would corrupt the selection-rate denominator.
    _td = pd.concat([
        match_meta[["team1", "gender", "date"]].rename(columns={"team1": "team"}),
        match_meta[["team2", "gender", "date"]].rename(columns={"team2": "team"}),
    ])
    team_dates = {tg: sorted(g["date"].tolist()) for tg, g in _td.groupby(["team", "gender"])}
    # fallback for "which country" when there's no recent international
    # appearance: her most recent international appearance ever, however
    # long ago.
    last_intl_team = apps_intl.sort_values("date").groupby(
        ["identifier", "gender"])["team"].last().to_dict()

    # a third thing this table must not conflate: the ACTIVE/INCONSISTENT/
    # INACTIVE status label must stay international-only, or a player with
    # only recent domestic form would misleadingly read as ACTIVE
    # internationally. `last_idx` (any competition) still feeds the
    # informational last_appearance_date/days_since_last_appearance columns.
    last_idx_intl = apps_intl.sort_values("date").groupby(["identifier", "gender"]).tail(1).set_index(
        ["identifier", "gender"])
    last_idx_domestic = apps[apps["team_type"] == "club"].sort_values("date").groupby(
        ["identifier", "gender"]).tail(1).set_index(["identifier", "gender"])

    last_idx = apps.sort_values("date").groupby(["identifier", "gender"]).tail(1).set_index(
        ["identifier", "gender"])

    rows = []
    active = inactive = inconsistent = retired = advisories = 0
    for (ident, gender), last in last_idx.iterrows():
        # unsplit players are stored with gender=NULL, so try the
        # split-specific key first, then fall back to the unsplit one.
        pm = meta.get((ident, gender)) or meta.get((ident, None))
        if not pm:
            continue
        pid = pm["player_id"]
        last_date = last["date"].date()
        days_since = max(0, (as_of_date - last_date).days)

        key = (ident, gender)
        # international-only recency drives the status label; `days_since`
        # above stays purely informational. a domestic-only player with no
        # international appearance sentinels past inactive_window_days so
        # she reads as INACTIVE, not a false ACTIVE.
        if key in last_idx_intl.index:
            days_since_intl = max(0, (as_of_date - last_idx_intl.loc[key, "date"].date()).days)
        else:
            days_since_intl = SETTINGS.inactive_window_days + 1
        # eligibility carve-out: a player INACTIVE internationally but
        # recently active domestically shouldn't be silently excluded from
        # selection, tracked separately from days_since_intl above.
        recent_domestic_activity = 0
        if key in last_idx_domestic.index:
            days_since_domestic = max(0, (as_of_date - last_idx_domestic.loc[key, "date"].date()).days)
            recent_domestic_activity = int(days_since_domestic <= SETTINGS.active_window_days)
        team = recent_team.get(key) or last_intl_team.get(key)
        window_player_matches = int(player_win.get(key, 0))
        fw = first_win.get(key)
        # (team, gender): a men's player is measured against his men's
        # side's matches, not the combined total.
        dates = team_dates.get((team, gender), [])
        window_team_matches = (len(dates) - bisect.bisect_left(dates, fw)) if (fw is not None and dates) else 0
        selection_rate = None
        if window_team_matches >= SETTINGS.min_window_team_matches:
            selection_rate = round(min(window_player_matches / window_team_matches, 1.0), 3)

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
        status, activity_signal, status_reason = _classify(is_ranked, days_since_intl, selection_rate)
        # recall_flag flags a borderline-stale player worth a second look,
        # not a genuinely long-absent INACTIVE one back into eligibility.
        # without this guard every unranked INACTIVE player would get
        # recall_flag=1, defeating roster.team_pool's INACTIVE exclusion.
        # uses days_since_intl for the same reason status/activity_signal do.
        recall = 0 if is_ranked or days_since_intl > SETTINGS.inactive_window_days else (
            1 if days_since_intl > SETTINGS.recall_flag_days else 0)
        rk = current_rank(conn, pid, fmt) if is_ranked else None
        discipline = rk["discipline"] if rk else None

        retired_formats = None
        retirement_date = None
        ov = overrides.get(pid)
        if ov:
            status = ov["status"]
            retirement_date = ov["date"]
            activity_signal = "manual_override"
            status_reason = "manual retirement/status override"
            if status == "RETIRED_FORMAT":
                retired_formats = fmt

        active += status == "ACTIVE"
        inactive += status == "INACTIVE"
        inconsistent += status == "INCONSISTENT"
        retired += status in ("RETIRED_ALL", "RETIRED_FORMAT")
        advisories += advisory

        rows.append((
            pid, fmt, status, retired_formats, retirement_date,
            last_date.isoformat(), last["opponent"], days_since,
            dob, age, phase,
            pm.get("role") or pm.get("derived_role"),
            pm.get("bowling_style"), pm.get("batting_hand"), pm.get("nationality"),
            recall, advisory, rk["rank"] if rk else None, rk["rating"] if rk else None,
            activity_signal, status_reason, discipline,
            selection_rate, window_player_matches, window_team_matches,
            recent_domestic_activity, now,
        ))

    conn.executemany(
        "INSERT INTO player_registry(player_id, format, retirement_status, "
        "retired_formats, retirement_date, last_appearance_date, "
        "last_appearance_opponent, days_since_last_appearance, date_of_birth, "
        "age_at_last_match, career_phase, role, bowling_style, batting_hand, "
        "nationality, recall_flag, age_advisory, icc_rank, icc_rating, "
        "activity_signal, status_reason, icc_discipline, "
        "selection_rate, window_player_matches, window_team_matches, "
        "recent_domestic_activity, registry_last_updated) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
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
        "icc_rating=excluded.icc_rating, activity_signal=excluded.activity_signal, "
        "status_reason=excluded.status_reason, icc_discipline=excluded.icc_discipline, "
        "selection_rate=excluded.selection_rate, "
        "window_player_matches=excluded.window_player_matches, "
        "window_team_matches=excluded.window_team_matches, "
        "recent_domestic_activity=excluded.recent_domestic_activity, "
        "registry_last_updated=excluded.registry_last_updated",
        rows,
    )
    conn.commit()
    ranked_count = sum(1 for r in rows if r[19] == "icc_ranked")
    log.info("registry %s: %d players (as-of %s) | active=%d inconsistent=%d inactive=%d "
             "retired=%d recall=%d age-advisory=%d ranked=%d",
             fmt, len(rows), as_of.date(), active, inconsistent, inactive, retired,
             sum(r[15] for r in rows), advisories, ranked_count)
    return len(rows)


def build_registry(conn) -> dict:
    formats = sorted({s.fmt for s in enabled_sources()})
    out = {}
    for fmt in formats:
        out[fmt] = build_registry_for_format(conn, fmt)
    set_meta(conn, "registry_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out
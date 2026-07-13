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
    """Classify a player's activity status from appearance signals.

    Precedence: a current ICC (top-10) ranking confirms ACTIVE; a long absence
    marks INACTIVE (likely retired/out). For players who *did* appear recently,
    the selection rate (share of their team's matches they were picked for over
    the recent window) separates regularly-selected ACTIVE players from in-and-out
    INCONSISTENT ones. selection_rate is None when the team's sample is too small
    to judge, in which case a recent appearance alone keeps the player ACTIVE.
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
    """(cricsheet_identifier, gender) -> player row. Gender-scoped because a
    handful of Cricsheet registry identifiers are reused across two
    genuinely different people of different genders (see identity.py) --
    a plain identifier-keyed dict would silently keep only one of them.
    """
    rows = conn.execute(
        "SELECT player_id, cricsheet_identifier, gender, canonical_name, key_cricinfo, "
        "nationality, role, derived_role, date_of_birth, bowling_style, batting_hand "
        "FROM players").fetchall()
    return {(r["cricsheet_identifier"], r["gender"]): dict(r) for r in rows if r["cricsheet_identifier"]}


def build_registry_for_format(conn, fmt: str) -> int:
    apps = pd.read_sql_query(
        "SELECT mp.match_id, mp.player_name, mp.team, m.date, m.team1, m.team2, m.gender "
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
    # Recency is measured relative to the most recent match in the data, not
    # wall-clock time, so re-running the same snapshot is reproducible and a
    # player who featured in the latest fixtures is never drifted into "stale".
    as_of_date = as_of.date()
    now = dt.datetime.now().isoformat(timespec="seconds")

    # Selection-consistency window. For each player we compare how many matches
    # they were picked for against how many their team played *since the player's
    # first appearance in the window* — so a mid-window debutant who then played
    # every game reads as a regular, not as in-and-out. Only appearances within
    # selection_window_days before as_of are considered.
    window_start = as_of - pd.Timedelta(days=SETTINGS.selection_window_days)
    win = apps[apps["date"] >= window_start]
    # gender kept alongside identifier in every group key below -- see
    # _players_meta's docstring on why a plain identifier isn't always
    # enough to identify one real person.
    grp = win.groupby(["identifier", "gender"])
    player_win = grp["match_id"].nunique().to_dict()
    first_win = grp["date"].min().to_dict()
    recent_team = (grp["team"].agg(lambda s: s.value_counts().idxmax()).to_dict()
                   if not win.empty else {})
    match_meta = apps.drop_duplicates("match_id")
    match_meta = match_meta[match_meta["date"] >= window_start]
    _td = pd.concat([
        match_meta[["team1", "date"]].rename(columns={"team1": "team"}),
        match_meta[["team2", "date"]].rename(columns={"team2": "team"}),
    ])
    team_dates = {t: sorted(g["date"].tolist()) for t, g in _td.groupby("team")}

    last_idx = apps.sort_values("date").groupby(["identifier", "gender"]).tail(1).set_index(
        ["identifier", "gender"])

    rows = []
    active = inactive = inconsistent = retired = advisories = 0
    for (ident, gender), last in last_idx.iterrows():
        # unsplit (non-colliding) players are stored with gender=NULL --
        # `gender` here is the real value from actual match data, so try the
        # split-specific key first, then fall back to the unsplit one.
        pm = meta.get((ident, gender)) or meta.get((ident, None))
        if not pm:
            continue
        pid = pm["player_id"]
        last_date = last["date"].date()
        days_since = max(0, (as_of_date - last_date).days)

        key = (ident, gender)
        team = recent_team.get(key) or last["team"]
        window_player_matches = int(player_win.get(key, 0))
        fw = first_win.get(key)
        dates = team_dates.get(team, [])
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
        status, activity_signal, status_reason = _classify(is_ranked, days_since, selection_rate)
        # `recall_flag` is meant to flag a borderline-stale player worth a
        # selector's second look, NOT to override a genuinely long-absent
        # (INACTIVE, >inactive_window_days) player back into eligibility --
        # `recall_flag_days` (180) is far smaller than `inactive_window_days`
        # (1095), so without this guard *every* unranked INACTIVE player
        # automatically got recall_flag=1, silently defeating
        # `roster.team_pool`'s INACTIVE exclusion for anyone not ICC-ranked
        # (a real bug found this way: "RK Parwin", last appearance 2012, was
        # still surfacing in India's current squad recommendations in 2026).
        # A genuine recall-from-retirement needs a real signal this
        # single-most-recent-appearance loop can't see (a fresh appearance
        # after a long-past gap) -- that belongs in `overrides.py`'s manual
        # status override, not an automatic days-since-last-appearance guess.
        recall = 0 if is_ranked or days_since > SETTINGS.inactive_window_days else (
            1 if days_since > SETTINGS.recall_flag_days else 0)
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
            selection_rate, window_player_matches, window_team_matches, now,
        ))

    conn.executemany(
        "INSERT INTO player_registry(player_id, format, retirement_status, "
        "retired_formats, retirement_date, last_appearance_date, "
        "last_appearance_opponent, days_since_last_appearance, date_of_birth, "
        "age_at_last_match, career_phase, role, bowling_style, batting_hand, "
        "nationality, recall_flag, age_advisory, icc_rank, icc_rating, "
        "activity_signal, status_reason, icc_discipline, "
        "selection_rate, window_player_matches, window_team_matches, "
        "registry_last_updated) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
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
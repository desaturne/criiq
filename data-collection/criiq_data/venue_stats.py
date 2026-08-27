from __future__ import annotations

import datetime as dt

import pandas as pd

from .config import enabled_sources
from .db import set_meta
from .identity import player_id_map
from .logging_utils import get_logger
from .stats import build_innings

log = get_logger("venue")


def _situational_by_venue(conn, fmt: str) -> pd.DataFrame:
    """batting-first (innings 1) vs chasing (innings 2) splits, per (player, venue).
    same computation as impact.py's _sit helper, with venue_id added to the group key.
    """
    deliv = pd.read_sql_query(
        "SELECT d.striker, d.runs_off_bat, d.wides, d.innings, d.player_dismissed, "
        "m.gender, m.venue_id "
        "FROM deliveries d JOIN matches m ON d.match_id=m.match_id "
        "WHERE m.format=? AND m.team_type='international' AND m.venue_id IS NOT NULL "
        "AND d.innings IN (1, 2)", conn, params=(fmt,))
    if deliv.empty:
        return pd.DataFrame()
    name2id = {r["player_name"]: r["identifier"]
               for r in conn.execute("SELECT player_name, identifier FROM identifier_map")}
    deliv["legal"] = (deliv["wides"].fillna(0) == 0).astype(int)
    deliv["striker_id"] = deliv["striker"].map(name2id)
    sit = deliv.dropna(subset=["striker_id"])
    sit_runs = sit.groupby(["striker_id", "gender", "venue_id", "innings"]).agg(
        runs=("runs_off_bat", "sum"), balls=("legal", "sum")).reset_index()
    outs = (deliv[deliv["player_dismissed"].notna()].assign(
        did=lambda x: x["player_dismissed"].map(name2id))
        .dropna(subset=["did"])
        .groupby(["did", "gender", "venue_id", "innings"]).size()
        .rename("outs").reset_index()
        .rename(columns={"did": "striker_id"}))
    return sit_runs.merge(outs, on=["striker_id", "gender", "venue_id", "innings"], how="left")


def build_for_format(conn, fmt: str) -> int:
    inn = build_innings(conn, fmt)
    if inn.empty:
        return 0
    inn = inn.dropna(subset=["venue_id"])
    venues = {r["venue_id"]: r["canonical_name"]
              for r in conn.execute("SELECT venue_id, canonical_name FROM venues")}
    unambiguous, split = player_id_map(conn)

    # gender kept in every group key: see identity.py on why a plain
    # identifier isn't always enough to identify one real person.
    keys = ["identifier", "gender", "venue_id"]
    res = inn.groupby(keys).agg(matches=("match_id", "nunique"), won=("won", "sum")).reset_index()
    batted = inn[inn["balls_faced"] > 0]
    bat = batted.groupby(keys).agg(
        bat_innings=("runs", "size"), runs=("runs", "sum"), balls=("balls_faced", "sum"),
        outs=("out", "sum"), hs=("runs", "max")).reset_index()
    bowled = inn[inn["balls_bowled"] > 0]
    bowl = bowled.groupby(keys).agg(
        bowl_innings=("wickets", "size"), bb=("balls_bowled", "sum"),
        wkts=("wickets", "sum"), rc=("runs_conceded", "sum")).reset_index()
    best = (bowled.sort_values(["wickets", "runs_conceded"], ascending=[False, True])
            .groupby(keys).first().reset_index()[keys + ["wickets", "runs_conceded"]]
            .rename(columns={"wickets": "best_w", "runs_conceded": "best_r"}))

    df = res.merge(bat, on=keys, how="left").merge(bowl, on=keys, how="left").merge(best, on=keys, how="left")

    sit = _situational_by_venue(conn, fmt)
    sit_by_key: dict[tuple, dict] = {}
    if not sit.empty:
        for r in sit.itertuples(index=False):
            key = (r.striker_id, r.gender, r.venue_id)
            sit_by_key.setdefault(key, {})[int(r.innings)] = {
                "runs": int(r.runs), "balls": int(r.balls),
                "outs": int(r.outs) if pd.notna(r.outs) else 0,
            }

    now = dt.datetime.now().isoformat(timespec="seconds")
    rows = []
    for r in df.itertuples(index=False):
        pid = unambiguous.get(r.identifier) or split.get((r.identifier, r.gender))
        if not pid:
            continue
        runs = int(r.runs) if pd.notna(r.runs) else 0
        balls = int(r.balls) if pd.notna(r.balls) else 0
        outs = int(r.outs) if pd.notna(r.outs) else 0
        bb = int(r.bb) if pd.notna(r.bb) else 0
        rc = int(r.rc) if pd.notna(r.rc) else 0
        wk = int(r.wkts) if pd.notna(r.wkts) else 0
        best_bowl = f"{int(r.best_w)}/{int(r.best_r)}" if pd.notna(getattr(r, "best_w", None)) else None

        sit_key = (r.identifier, r.gender, r.venue_id)
        set_d = sit_by_key.get(sit_key, {}).get(1, {})
        chase_d = sit_by_key.get(sit_key, {}).get(2, {})
        set_balls, set_runs, set_outs = set_d.get("balls", 0), set_d.get("runs", 0), set_d.get("outs", 0)
        chase_balls, chase_runs, chase_outs = chase_d.get("balls", 0), chase_d.get("runs", 0), chase_d.get("outs", 0)

        rows.append((
            pid, fmt, r.venue_id, venues.get(r.venue_id, r.venue_id),
            int(r.matches), int(r.won),
            int(r.bat_innings) if pd.notna(r.bat_innings) else 0, runs, balls,
            round(runs / outs, 1) if outs else None,
            round(100 * runs / balls, 1) if balls else None,
            int(r.hs) if pd.notna(r.hs) else None,
            int(r.bowl_innings) if pd.notna(r.bowl_innings) else 0, bb, wk, rc,
            round(6 * rc / bb, 2) if bb else None, best_bowl,
            set_balls or None, set_runs or None,
            round(set_runs / set_outs, 1) if set_outs else None,
            round(100 * set_runs / set_balls, 1) if set_balls else None,
            chase_balls or None, chase_runs or None,
            round(chase_runs / chase_outs, 1) if chase_outs else None,
            round(100 * chase_runs / chase_balls, 1) if chase_balls else None,
            now,
        ))
    conn.executemany(
        "INSERT INTO player_by_venue(player_id, format, venue_id, venue_name, matches, "
        "won, bat_innings, runs, balls_faced, bat_average, bat_strike_rate, high_score, "
        "bowl_innings, balls_bowled, wickets, runs_conceded, economy, best_bowling, "
        "setting_balls, setting_runs, setting_average, setting_strike_rate, "
        "chasing_balls, chasing_runs, chasing_average, chasing_strike_rate, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id, format, venue_id) DO UPDATE SET "
        "venue_name=excluded.venue_name, matches=excluded.matches, won=excluded.won, "
        "bat_innings=excluded.bat_innings, runs=excluded.runs, balls_faced=excluded.balls_faced, "
        "bat_average=excluded.bat_average, bat_strike_rate=excluded.bat_strike_rate, "
        "high_score=excluded.high_score, bowl_innings=excluded.bowl_innings, "
        "balls_bowled=excluded.balls_bowled, wickets=excluded.wickets, "
        "runs_conceded=excluded.runs_conceded, economy=excluded.economy, "
        "best_bowling=excluded.best_bowling, "
        "setting_balls=excluded.setting_balls, setting_runs=excluded.setting_runs, "
        "setting_average=excluded.setting_average, setting_strike_rate=excluded.setting_strike_rate, "
        "chasing_balls=excluded.chasing_balls, chasing_runs=excluded.chasing_runs, "
        "chasing_average=excluded.chasing_average, chasing_strike_rate=excluded.chasing_strike_rate, "
        "updated_at=excluded.updated_at", rows)
    conn.commit()
    log.info("venue %s: %d player-venue rows", fmt, len(rows))
    return len(rows)


def build_venue_stats(conn) -> dict:
    out = {}
    for fmt in sorted({s.fmt for s in enabled_sources()}):
        out[fmt] = build_for_format(conn, fmt)
    set_meta(conn, "venue_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out


def get_by_venue(conn, player_id: str, fmt: str, limit: int = 12) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM player_by_venue WHERE player_id=? AND format=? "
        "ORDER BY matches DESC, runs DESC LIMIT ?", (player_id, fmt, limit))]

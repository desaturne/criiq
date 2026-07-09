from __future__ import annotations

import datetime as dt

import pandas as pd

from .config import enabled_sources
from .db import set_meta
from .logging_utils import get_logger
from .stats import build_innings

log = get_logger("venue")


def build_for_format(conn, fmt: str) -> int:
    inn = build_innings(conn, fmt)
    if inn.empty:
        return 0
    inn = inn.dropna(subset=["venue_id"])
    venues = {r["venue_id"]: r["canonical_name"]
              for r in conn.execute("SELECT venue_id, canonical_name FROM venues")}
    players = {r["cricsheet_identifier"]: dict(r) for r in conn.execute(
        "SELECT cricsheet_identifier, player_id FROM players")}

    keys = ["identifier", "venue_id"]
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
    now = dt.datetime.now().isoformat(timespec="seconds")
    rows = []
    for r in df.itertuples(index=False):
        pm = players.get(r.identifier)
        if not pm:
            continue
        runs = int(r.runs) if pd.notna(r.runs) else 0
        balls = int(r.balls) if pd.notna(r.balls) else 0
        outs = int(r.outs) if pd.notna(r.outs) else 0
        bb = int(r.bb) if pd.notna(r.bb) else 0
        rc = int(r.rc) if pd.notna(r.rc) else 0
        wk = int(r.wkts) if pd.notna(r.wkts) else 0
        best_bowl = f"{int(r.best_w)}/{int(r.best_r)}" if pd.notna(getattr(r, "best_w", None)) else None
        rows.append((
            pm["player_id"], fmt, r.venue_id, venues.get(r.venue_id, r.venue_id),
            int(r.matches), int(r.won),
            int(r.bat_innings) if pd.notna(r.bat_innings) else 0, runs, balls,
            round(runs / outs, 1) if outs else None,
            round(100 * runs / balls, 1) if balls else None,
            int(r.hs) if pd.notna(r.hs) else None,
            int(r.bowl_innings) if pd.notna(r.bowl_innings) else 0, bb, wk, rc,
            round(6 * rc / bb, 2) if bb else None, best_bowl, now,
        ))
    conn.executemany(
        "INSERT INTO player_by_venue(player_id, format, venue_id, venue_name, matches, "
        "won, bat_innings, runs, balls_faced, bat_average, bat_strike_rate, high_score, "
        "bowl_innings, balls_bowled, wickets, runs_conceded, economy, best_bowling, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id, format, venue_id) DO UPDATE SET "
        "venue_name=excluded.venue_name, matches=excluded.matches, won=excluded.won, "
        "bat_innings=excluded.bat_innings, runs=excluded.runs, balls_faced=excluded.balls_faced, "
        "bat_average=excluded.bat_average, bat_strike_rate=excluded.bat_strike_rate, "
        "high_score=excluded.high_score, bowl_innings=excluded.bowl_innings, "
        "balls_bowled=excluded.balls_bowled, wickets=excluded.wickets, "
        "runs_conceded=excluded.runs_conceded, economy=excluded.economy, "
        "best_bowling=excluded.best_bowling, updated_at=excluded.updated_at", rows)
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

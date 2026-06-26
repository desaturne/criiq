from __future__ import annotations

import datetime as dt

import pandas as pd

from .config import enabled_sources
from .db import set_meta
from .logging_utils import get_logger
from .stats import build_innings

log = get_logger("opponents")


def potm_match_to_ident(conn, fmt: str) -> dict[str, str]:
    name2id = {r["player_name"]: r["identifier"]
               for r in conn.execute("SELECT player_name, identifier FROM identifier_map")}
    out = {}
    for r in conn.execute(
            "SELECT match_id, player_of_match FROM matches "
            "WHERE format=? AND player_of_match IS NOT NULL", (fmt,)):
        ident = name2id.get(r["player_of_match"])
        if ident:
            out[r["match_id"]] = ident
    return out


def build_vs_opponent_for_format(conn, fmt: str) -> int:
    inn = build_innings(conn, fmt)
    if inn.empty:
        log.info("vs_opponent %s: no innings", fmt)
        return 0
    inn = inn.dropna(subset=["opponent"])
    potm = potm_match_to_ident(conn, fmt)
    inn["potm"] = [potm.get(m) == i for m, i in zip(inn["match_id"], inn["identifier"])]

    players = {r["cricsheet_identifier"]: dict(r) for r in conn.execute(
        "SELECT cricsheet_identifier, player_id, canonical_name FROM players")}

    keys = ["identifier", "opponent"]
    results = inn.groupby(keys).agg(
        matches=("match_id", "nunique"), won=("won", "sum"),
        potm=("potm", "sum")).reset_index()

    batted = inn[inn["balls_faced"] > 0]
    bat = batted.groupby(keys).agg(
        bat_innings=("runs", "size"), runs=("runs", "sum"),
        balls_faced=("balls_faced", "sum"), dismissals=("out", "sum"),
        high_score=("runs", "max")).reset_index()
    fifties = (batted[(batted["runs"] >= 50) & (batted["runs"] < 100)]
               .groupby(keys).size().rename("fifties").reset_index())
    hundreds = (batted[batted["runs"] >= 100]
                .groupby(keys).size().rename("hundreds").reset_index())

    bowled = inn[inn["balls_bowled"] > 0]
    bowl = bowled.groupby(keys).agg(
        bowl_innings=("wickets", "size"), balls_bowled=("balls_bowled", "sum"),
        wickets=("wickets", "sum"), runs_conceded=("runs_conceded", "sum")).reset_index()
    best = (bowled.sort_values(["wickets", "runs_conceded"], ascending=[False, True])
            .groupby(keys).first().reset_index()[keys + ["wickets", "runs_conceded"]]
            .rename(columns={"wickets": "best_w", "runs_conceded": "best_r"}))

    df = results
    for part in (bat, fifties, hundreds, bowl, best):
        df = df.merge(part, on=keys, how="left")

    now = dt.datetime.now().isoformat(timespec="seconds")
    rows = []
    for r in df.itertuples(index=False):
        pm = players.get(r.identifier)
        if not pm:
            continue
        runs = int(r.runs) if pd.notna(r.runs) else 0
        balls = int(r.balls_faced) if pd.notna(r.balls_faced) else 0
        outs = int(r.dismissals) if pd.notna(r.dismissals) else 0
        bb = int(r.balls_bowled) if pd.notna(r.balls_bowled) else 0
        rc = int(r.runs_conceded) if pd.notna(r.runs_conceded) else 0
        wk = int(r.wickets) if pd.notna(r.wickets) else 0
        best_bowl = (f"{int(r.best_w)}/{int(r.best_r)}"
                     if pd.notna(getattr(r, "best_w", None)) else None)
        rows.append((
            pm["player_id"], fmt, r.opponent,
            int(r.matches), int(r.won), round(100 * r.won / r.matches, 1) if r.matches else None,
            int(r.bat_innings) if pd.notna(r.bat_innings) else 0, runs, balls,
            round(runs / outs, 1) if outs else None,
            round(100 * runs / balls, 1) if balls else None,
            int(r.high_score) if pd.notna(r.high_score) else None,
            int(r.fifties) if pd.notna(r.fifties) else 0,
            int(r.hundreds) if pd.notna(r.hundreds) else 0, outs,
            int(r.bowl_innings) if pd.notna(r.bowl_innings) else 0, bb, wk, rc,
            round(6 * rc / bb, 2) if bb else None,
            round(rc / wk, 1) if wk else None,
            round(bb / wk, 1) if wk else None, best_bowl,
            int(r.potm) if pd.notna(r.potm) else 0, now,
        ))

    conn.executemany(
        "INSERT INTO player_vs_opponent(player_id, format, opponent, matches, won, "
        "win_pct, bat_innings, runs, balls_faced, bat_average, bat_strike_rate, "
        "high_score, fifties, hundreds, dismissals, bowl_innings, balls_bowled, "
        "wickets, runs_conceded, economy, bowl_average, bowl_strike_rate, "
        "best_bowling, player_of_match, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id, format, opponent) DO UPDATE SET "
        "matches=excluded.matches, won=excluded.won, win_pct=excluded.win_pct, "
        "bat_innings=excluded.bat_innings, runs=excluded.runs, "
        "balls_faced=excluded.balls_faced, bat_average=excluded.bat_average, "
        "bat_strike_rate=excluded.bat_strike_rate, high_score=excluded.high_score, "
        "fifties=excluded.fifties, hundreds=excluded.hundreds, dismissals=excluded.dismissals, "
        "bowl_innings=excluded.bowl_innings, balls_bowled=excluded.balls_bowled, "
        "wickets=excluded.wickets, runs_conceded=excluded.runs_conceded, "
        "economy=excluded.economy, bowl_average=excluded.bowl_average, "
        "bowl_strike_rate=excluded.bowl_strike_rate, best_bowling=excluded.best_bowling, "
        "player_of_match=excluded.player_of_match, updated_at=excluded.updated_at", rows)
    conn.commit()
    log.info("vs_opponent %s: %d player-opponent rows", fmt, len(rows))
    return len(rows)


def build_vs_opponent(conn) -> dict:
    out = {}
    for fmt in sorted({s.fmt for s in enabled_sources()}):
        out[fmt] = build_vs_opponent_for_format(conn, fmt)
    set_meta(conn, "vs_opponent_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out


def get_vs_opponent(conn, player_id: str, fmt: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM player_vs_opponent WHERE player_id=? AND format=? "
        "ORDER BY matches DESC, runs DESC", (player_id, fmt))]

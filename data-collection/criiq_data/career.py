from __future__ import annotations

import datetime as dt

import pandas as pd

from .config import enabled_sources
from .db import set_meta
from .identity import player_id_map
from .logging_utils import get_logger
from .stats import build_innings

log = get_logger("career")


def _overs(balls: int) -> str:
    return f"{int(balls) // 6}.{int(balls) % 6}"


def career_from_group(g: pd.DataFrame) -> dict:
    batted = g[g["balls_faced"] > 0]
    runs = int(g["runs"].sum())
    balls = int(g["balls_faced"].sum())
    outs = int(batted["out"].sum())
    out: dict = {"batting": {
        "innings": int(len(batted)),
        "runs": runs,
        "balls": balls,
        "average": round(runs / outs, 1) if outs else None,
        "strike_rate": round(100 * runs / balls, 1) if balls else None,
        "high_score": int(batted["runs"].max()) if len(batted) else 0,
        "fifties": int(((batted["runs"] >= 50) & (batted["runs"] < 100)).sum()),
        "hundreds": int((batted["runs"] >= 100).sum()),
    }}

    bowl_balls = int(g["balls_bowled"].sum())
    if bowl_balls > 0:
        bowled = g[g["balls_bowled"] > 0]
        rc = int(g["runs_conceded"].sum())
        wk = int(g["wickets"].sum())
        best = bowled.sort_values(["wickets", "runs_conceded"],
                                  ascending=[False, True]).iloc[0]
        out["bowling"] = {
            "innings": int(len(bowled)),
            "balls": bowl_balls,
            "overs": _overs(bowl_balls),
            "runs_conceded": rc,
            "wickets": wk,
            "economy": round(6 * rc / bowl_balls, 2),
            "average": round(rc / wk, 1) if wk else None,
            "strike_rate": round(bowl_balls / wk, 1) if wk else None,
            "best_bowling": f"{int(best['wickets'])}/{int(best['runs_conceded'])}",
        }
    return out


def build_career_for_format(conn, fmt: str) -> int:
    innings = build_innings(conn, fmt)
    if innings.empty:
        log.info("career %s: no innings", fmt)
        return 0
    # gender-scoped group, not just identifier: the handful of Cricsheet
    # registry identifiers reused across two genuinely different people of
    # different genders (see identity.py) would otherwise have their innings
    # blended into one meaningless combined "career" before player_id is
    # even resolved.
    meta = {}
    for r in conn.execute(
            "SELECT cricsheet_identifier, gender, canonical_name, role, derived_role FROM players"):
        meta[(r["cricsheet_identifier"], r["gender"])] = dict(r)
    unambiguous, split = player_id_map(conn)
    now = dt.datetime.now().isoformat(timespec="seconds")

    rows = []
    for (ident, gender), g in innings.groupby(["identifier", "gender"]):
        pid = unambiguous.get(ident) or split.get((ident, gender))
        # unsplit (non-colliding) players are stored with gender=NULL.
        pm = meta.get((ident, gender)) or meta.get((ident, None))
        if not pid or not pm:
            continue
        c = career_from_group(g)
        b = c["batting"]
        bw = c.get("bowling", {})
        rows.append((
            pid, fmt, pm["canonical_name"],
            pm.get("role") or pm.get("derived_role"),
            b["innings"], b["runs"], b["balls"], b["average"], b["strike_rate"],
            b["high_score"], b["fifties"], b["hundreds"],
            bw.get("innings"), bw.get("balls"), bw.get("overs"),
            bw.get("runs_conceded"), bw.get("wickets"), bw.get("economy"),
            bw.get("average"), bw.get("strike_rate"), bw.get("best_bowling"),
            now,
        ))

    conn.executemany(
        "INSERT INTO player_career(player_id, format, name, role, bat_innings, runs, "
        "balls_faced, bat_average, bat_strike_rate, high_score, fifties, hundreds, "
        "bowl_innings, balls_bowled, overs, runs_conceded, wickets, economy, "
        "bowl_average, bowl_strike_rate, best_bowling, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id, format) DO UPDATE SET "
        "name=excluded.name, role=excluded.role, bat_innings=excluded.bat_innings, "
        "runs=excluded.runs, balls_faced=excluded.balls_faced, "
        "bat_average=excluded.bat_average, bat_strike_rate=excluded.bat_strike_rate, "
        "high_score=excluded.high_score, fifties=excluded.fifties, hundreds=excluded.hundreds, "
        "bowl_innings=excluded.bowl_innings, balls_bowled=excluded.balls_bowled, "
        "overs=excluded.overs, runs_conceded=excluded.runs_conceded, wickets=excluded.wickets, "
        "economy=excluded.economy, bowl_average=excluded.bowl_average, "
        "bowl_strike_rate=excluded.bowl_strike_rate, best_bowling=excluded.best_bowling, "
        "updated_at=excluded.updated_at", rows)
    conn.commit()
    log.info("career %s: %d player career records built", fmt, len(rows))
    return len(rows)


def build_career(conn) -> dict:
    out = {}
    for fmt in sorted({s.fmt for s in enabled_sources()}):
        out[fmt] = build_career_for_format(conn, fmt)
    set_meta(conn, "career_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out

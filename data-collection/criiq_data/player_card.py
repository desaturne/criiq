from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from .career import career_from_group
from .config import SETTINGS, enabled_sources
from .db import set_meta
from .h2h import player_vs_team
from .logging_utils import get_logger
from .rankings import player_rankings
from .stats import build_innings
from .styles import classify_bowling_detail, classify_hand

log = get_logger("player_card")


def _overs(balls: int) -> str:
    return f"{balls // 6}.{balls % 6}"


def _rfi(runs_series: list[float]) -> float | None:
    if not runs_series:
        return None
    window = runs_series[-SETTINGS.form_window_innings:]
    lam = SETTINGS.rfi_lambda
    num = den = 0.0
    for i, r in enumerate(reversed(window)):
        w = lam ** i
        num += w * r
        den += w
    return round(num / den, 1) if den else None


def _trend(bat_runs: list[float]) -> str:
    if len(bat_runs) < 4:
        return "flat"
    half = len(bat_runs) // 2
    recent = sum(bat_runs[half:]) / max(1, len(bat_runs) - half)
    earlier = sum(bat_runs[:half]) / max(1, half)
    if recent > earlier * 1.15:
        return "up"
    if recent < earlier * 0.85:
        return "down"
    return "flat"


def _support_tables(conn, fmt: str):
    team_runs = pd.read_sql_query(
        "SELECT d.match_id, d.batting_team AS team, SUM(d.runs_total) AS runs "
        "FROM deliveries d JOIN matches m ON d.match_id=m.match_id "
        "WHERE m.format=? AND m.team_type='international' "
        "GROUP BY d.match_id, d.batting_team", conn, params=(fmt,))
    tr = {(r.match_id, r.team): r.runs for r in team_runs.itertuples()}

    team_wkts = pd.read_sql_query(
        "SELECT d.match_id, d.bowling_team AS team, "
        "SUM(CASE WHEN d.player_dismissed IS NOT NULL THEN 1 ELSE 0 END) AS wkts "
        "FROM deliveries d JOIN matches m ON d.match_id=m.match_id "
        "WHERE m.format=? AND m.team_type='international' "
        "GROUP BY d.match_id, d.bowling_team", conn, params=(fmt,))
    tw = {(r.match_id, r.team): r.wkts for r in team_wkts.itertuples()}

    death = pd.read_sql_query(
        "SELECT d.striker AS player_name, SUM(d.runs_off_bat) AS death_runs "
        "FROM deliveries d JOIN matches m ON d.match_id=m.match_id "
        "WHERE m.format=? AND m.team_type='international' AND d.over>=15 "
        "GROUP BY d.striker", conn, params=(fmt,))
    idmap = pd.read_sql_query("SELECT player_name, identifier FROM identifier_map", conn)
    death = death.merge(idmap, on="player_name", how="left").dropna(subset=["identifier"])
    dr = death.groupby("identifier")["death_runs"].sum().to_dict()
    return tr, tw, dr


def _ident_to_player(conn) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT player_id, cricsheet_identifier, canonical_name, nationality, "
        "role, derived_role, date_of_birth, batting_hand, bowling_style FROM players").fetchall()
    return {r["cricsheet_identifier"]: dict(r) for r in rows if r["cricsheet_identifier"]}


def _registry_status(conn, fmt: str) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT player_id, retirement_status, retired_formats, retirement_date, "
        "recall_flag, age_advisory, career_phase, icc_rank, icc_rating, "
        "activity_signal, status_reason, icc_discipline, "
        "last_appearance_date, days_since_last_appearance, "
        "selection_rate, window_player_matches, window_team_matches "
        "FROM player_registry WHERE format=?", (fmt,)).fetchall()
    return {r["player_id"]: dict(r) for r in rows}


def build_cards_for_format(conn, fmt: str) -> int:
    innings = build_innings(conn, fmt)
    if innings.empty:
        log.info("cards %s: no innings", fmt)
        return 0

    players = _ident_to_player(conn)
    status = _registry_status(conn, fmt)
    team_runs, team_wkts, death_runs = _support_tables(conn, fmt)
    matches_meta = {r["match_id"]: dict(r) for r in conn.execute(
        "SELECT match_id, date, event, venue_raw, team1, team2, winner, win_margin "
        "FROM matches WHERE format=? AND team_type='international'", (fmt,))}
    now = dt.datetime.now().isoformat(timespec="seconds")
    n_recent = SETTINGS.impact_recent_matches

    innings = innings.sort_values("date")
    rows = []
    for ident, g in innings.groupby("identifier"):
        pm = players.get(ident)
        if pm is None:
            continue
        g = g.sort_values("date")
        latest = g.iloc[-1]

        bat_balls = int(latest["balls_faced"])
        bowl_balls = int(latest["balls_bowled"])
        latest_block = {
            "date": latest["date"].date().isoformat() if pd.notna(latest["date"]) else None,
            "opponent": latest["opponent"], "venue_id": latest["venue_id"],
            "result": "won" if latest["won"] else "lost/other",
        }
        if bat_balls > 0:
            latest_block["batting"] = {
                "runs": int(latest["runs"]), "balls": bat_balls,
                "not_out": bool(latest["out"] == 0),
                "strike_rate": round(100 * latest["runs"] / bat_balls, 1),
            }
        if bowl_balls > 0:
            latest_block["bowling"] = {
                "overs": _overs(bowl_balls), "runs": int(latest["runs_conceded"]),
                "wickets": int(latest["wickets"]),
                "economy": round(6 * latest["runs_conceded"] / bowl_balls, 2),
            }
        mm = matches_meta.get(latest["match_id"])
        if mm:
            t1, t2 = mm.get("team1"), mm.get("team2")
            latest_block["match_summary"] = {
                "event": mm.get("event"), "venue": mm.get("venue_raw"),
                "teams": [t1, t2],
                "totals": {t1: team_runs.get((latest["match_id"], t1)),
                           t2: team_runs.get((latest["match_id"], t2))},
                "winner": mm.get("winner"), "margin": mm.get("win_margin"),
            }

        batted = g[g["balls_faced"] > 0]
        bat_runs = [int(x) for x in batted["runs"].tolist()]
        form_block = {
            "last_innings": bat_runs[-SETTINGS.form_sparkline_len:],
            "rfi": _rfi(bat_runs),
            "trend": _trend(bat_runs),
            "innings_count": len(bat_runs),
        }

        recent = g.tail(n_recent)
        team = latest["team"]
        pr = recent["runs"].sum()
        tr = sum(team_runs.get((mid, t), 0)
                 for mid, t in zip(recent["match_id"], recent["team"]))
        pw = recent["wickets"].sum()
        tw = sum(team_wkts.get((mid, t), 0)
                 for mid, t in zip(recent["match_id"], recent["team"]))
        bowled_matches = int((g["balls_bowled"] > 0).sum())
        total_runs = g["runs"].sum()
        impact_block = {
            "runs_share": round(pr / tr, 3) if tr else None,
            "wickets_share": round(pw / tw, 3) if tw else None,
            "wicket_contribution_rate": round(g["wickets"].sum() / bowled_matches, 2)
                if bowled_matches else None,
            "pressure_index": round(death_runs.get(ident, 0) / total_runs, 3)
                if total_runs else None,
            "win_contribution": round(g["won"].mean(), 3),
            "window_matches": int(len(recent)),
        }

        st = status.get(pm["player_id"], {})
        ranking_rows = player_rankings(conn, pm["player_id"], fmt)
        best_ranking = ranking_rows[0] if ranking_rows else None
        age = None
        dob = pm.get("date_of_birth")
        if dob and pd.notna(latest["date"]):
            try:
                age = round((latest["date"].date() - dt.date.fromisoformat(dob)).days / 365.25, 1)
            except ValueError:
                age = None

        h2h = player_vs_team(conn, fmt, pm["player_id"], latest["opponent"]) \
            if latest["opponent"] else {}

        card = {
            "identity": {
                "player_id": pm["player_id"], "name": pm["canonical_name"],
                "role": pm.get("role") or pm.get("derived_role"),
                "nationality": pm.get("nationality") or team, "age": age,
                "batting_hand": classify_hand(pm.get("batting_hand")),
                "bowling_style": pm.get("bowling_style"),
                "bowling_type": classify_bowling_detail(pm.get("bowling_style")),
            },
            "career": career_from_group(g),
            "latest_match": latest_block,
            "form": form_block,
            "impact": impact_block,
            "status": {
                "retirement_status": st.get("retirement_status", "UNKNOWN"),
                "retired_formats": st.get("retired_formats"),
                "retirement_date": st.get("retirement_date"),
                "recall_flag": bool(st.get("recall_flag", 0)),
                "age_advisory": bool(st.get("age_advisory", 0)),
                "career_phase": st.get("career_phase"),
                "activity_signal": st.get("activity_signal"),
                "status_reason": st.get("status_reason"),
                "icc_rank": st.get("icc_rank"),
                "icc_rating": st.get("icc_rating"),
                "icc_discipline": st.get("icc_discipline"),
                "last_appearance_date": st.get("last_appearance_date"),
                "days_since_last_appearance": st.get("days_since_last_appearance"),
                "selection_rate": st.get("selection_rate"),
                "window_player_matches": st.get("window_player_matches"),
                "window_team_matches": st.get("window_team_matches"),
            },
            "icc_ranking": {
                "ranked": bool(ranking_rows),
                "best": best_ranking,
                "all": ranking_rows,
                "source": best_ranking.get("source") if best_ranking else None,
                "source_url": best_ranking.get("source_url") if best_ranking else None,
                "rank_date": best_ranking.get("rank_date") if best_ranking else None,
                "extracted_at": best_ranking.get("extracted_at") if best_ranking else None,
            },
            "h2h_vs_latest_opponent": h2h,
            "matches_played": int(g["match_id"].nunique()),
            "meta": {"format": fmt, "card_last_updated": now},
        }

        rows.append((
            pm["player_id"], fmt, pm["canonical_name"],
            card["identity"]["role"], card["identity"]["nationality"],
            form_block["rfi"], form_block["trend"], latest_block["date"],
            card["matches_played"], json.dumps(card), now,
        ))

    conn.executemany(
        "INSERT INTO player_cards(player_id, format, name, role, nationality, "
        "rfi, form_trend, latest_match_date, matches_played, card_json, card_last_updated) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id, format) DO UPDATE SET "
        "name=excluded.name, role=excluded.role, nationality=excluded.nationality, "
        "rfi=excluded.rfi, form_trend=excluded.form_trend, "
        "latest_match_date=excluded.latest_match_date, "
        "matches_played=excluded.matches_played, card_json=excluded.card_json, "
        "card_last_updated=excluded.card_last_updated",
        rows,
    )
    conn.commit()
    log.info("cards %s: %d player cards built", fmt, len(rows))
    return len(rows)


def build_cards(conn) -> dict:
    formats = sorted({s.fmt for s in enabled_sources()})
    out = {}
    for fmt in formats:
        out[fmt] = build_cards_for_format(conn, fmt)
    set_meta(conn, "cards_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out


def get_card(conn, player_id: str, fmt: str) -> dict | None:
    row = conn.execute(
        "SELECT card_json FROM player_cards WHERE player_id=? AND format=?",
        (player_id, fmt)).fetchone()
    return json.loads(row["card_json"]) if row else None

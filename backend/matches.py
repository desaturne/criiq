"""
matches.py — fixtures list, match details, dashboard numbers, ticker (Phase 3).

Completed matches come from criiq.db (the pipeline's `matches` table).
Upcoming fixtures live in OUR app.db `fixtures` table (ids look like "f1").
"""

import json

from fastapi import APIRouter, Depends, HTTPException

import ai_model  # the real AI (falls back to ai_stub if a subprocess fails)
from auth import require_user
from database import app_db, criiq_db

router = APIRouter(tags=["matches"], dependencies=[Depends(require_user)])


def team_last5(team: str, gender: str) -> str:
    """Last 5 results for a team as a string like 'WLWWL' (most recent first).
    gender matters: the men's and women's sides share the name 'India'."""
    rows = criiq_db.execute(
        """SELECT winner FROM matches
           WHERE (team1 = ? OR team2 = ?) AND winner IS NOT NULL AND gender = ?
           ORDER BY date DESC LIMIT 5""",
        (team, team, gender),
    ).fetchall()
    return "".join("W" if r["winner"] == team else "L" for r in rows)


def fixture_to_json(f) -> dict:
    return {
        "id": f"f{f['id']}", "status": "upcoming",
        "team1": f["team1"], "team2": f["team2"],
        "venue": f["venue"], "date": f["date"], "format": f["format"],
        "result": None,
        "team1_last5": team_last5(f["team1"], f["gender"]),
        "team2_last5": team_last5(f["team2"], f["gender"]),
    }


# --------------------------------------------------------------------------
# 10. GET /matches — upcoming fixtures + recent completed matches
# --------------------------------------------------------------------------
@router.get("/matches")
def list_matches(completed_limit: int = 10):
    upcoming = [fixture_to_json(f) for f in app_db.execute(
        "SELECT * FROM fixtures ORDER BY date"
    ).fetchall()]

    completed = []
    for m in criiq_db.execute(
        """SELECT match_id, date, team1, team2, venue_raw, city, winner,
                  win_margin, format, gender, player_of_match
           FROM matches ORDER BY date DESC LIMIT ?""",
        (min(completed_limit, 50),),
    ).fetchall():
        completed.append({
            "id": m["match_id"], "status": "completed",
            "team1": m["team1"], "team2": m["team2"],
            "venue": m["venue_raw"], "city": m["city"], "date": m["date"],
            "format": m["format"], "gender": m["gender"],
            "result": (f"{m['winner']} won by {m['win_margin']}"
                       if m["winner"] else "No result"),
            "player_of_match": m["player_of_match"],
            "team1_last5": team_last5(m["team1"], m["gender"]),
            "team2_last5": team_last5(m["team2"], m["gender"]),
        })

    return {"data": {"upcoming": upcoming, "completed": completed}, "error": None}


# --------------------------------------------------------------------------
# 11. GET /matches/{id} — one match (fixture "f1" or completed match id)
# --------------------------------------------------------------------------
@router.get("/matches/{match_id}")
def match_detail(match_id: str):
    if match_id.startswith("f") and match_id[1:].isdigit():
        f = app_db.execute(
            "SELECT * FROM fixtures WHERE id = ?", (match_id[1:],)
        ).fetchone()
        if not f:
            raise HTTPException(404, "Unknown fixture id")
        return {"data": fixture_to_json(f), "error": None}

    m = criiq_db.execute(
        "SELECT * FROM matches WHERE match_id = ?", (match_id,)
    ).fetchone()
    if not m:
        raise HTTPException(404, "Unknown match id")

    # innings totals computed from the ball-by-ball table
    innings = [dict(r) for r in criiq_db.execute(
        """SELECT innings, batting_team,
                  SUM(runs_total)                          AS runs,
                  SUM(player_dismissed IS NOT NULL)        AS wickets,
                  COUNT(*)                                 AS balls
           FROM deliveries WHERE match_id = ?
           GROUP BY innings, batting_team ORDER BY innings""",
        (match_id,),
    ).fetchall()]

    return {"data": {**dict(m), "innings": innings}, "error": None}


# --------------------------------------------------------------------------
# 12. GET /dashboard/summary — the big numbers on the Dashboard screen
# --------------------------------------------------------------------------
@router.get("/dashboard/summary")
def dashboard_summary():
    next_fixture = app_db.execute(
        "SELECT * FROM fixtures ORDER BY date LIMIT 1"
    ).fetchone()

    # squad counts come from the saved selection for the next fixture (if any)
    xi_count = extras_count = 0
    if next_fixture:
        sel = app_db.execute(
            "SELECT squad_json FROM selections WHERE match_id = ?",
            (f"f{next_fixture['id']}",),
        ).fetchone()
        if sel:
            squad = json.loads(sel["squad_json"])
            xi_count = len(squad.get("xi", []))
            extras_count = len(squad.get("extra", []))

    win_prob = ai_model.get_win_probability(
        {"innings": 1, "balls_remaining": 120, "wickets": 0}
    )

    return {"data": {
        "squad_size": xi_count + extras_count,
        "xi_selected": xi_count,
        "reserves": extras_count,
        "next_match": fixture_to_json(next_fixture) if next_fixture else None,
        "win_probability": win_prob,
    }, "error": None}


# --------------------------------------------------------------------------
# 13. GET /dashboard/alerts — simple, rule-based "Form Alerts"
# --------------------------------------------------------------------------
@router.get("/dashboard/alerts")
def dashboard_alerts(limit: int = 10):
    """Two deliberately simple rules over each ACTIVE player's last scores:
       - last 3 innings all 50+          -> positive alert (in form)
       - last 3 innings all 10 or fewer  -> warning (out of form)"""
    alerts = []
    rows = criiq_db.execute(
        """SELECT c.name, c.player_id, c.card_json
           FROM player_cards c
           JOIN player_registry r ON r.player_id = c.player_id
           WHERE r.retirement_status = 'ACTIVE'
           ORDER BY c.matches_played DESC LIMIT 400"""
    ).fetchall()

    for row in rows:
        card = json.loads(row["card_json"])
        last3 = (card.get("form", {}).get("last_innings") or [])[-3:]
        if len(last3) < 3:
            continue
        if all(s >= 50 for s in last3):
            alerts.append({"type": "positive", "player_id": row["player_id"],
                           "player": row["name"], "scores": last3,
                           "message": f"{row['name']}: three consecutive 50+ scores"})
        elif all(s <= 10 for s in last3):
            alerts.append({"type": "warning", "player_id": row["player_id"],
                           "player": row["name"], "scores": last3,
                           "message": f"{row['name']}: three single-digit scores in a row"})
        if len(alerts) >= limit:
            break

    return {"data": alerts, "error": None}


# --------------------------------------------------------------------------
# 14. GET /ticker — standout performances from the latest matches
# --------------------------------------------------------------------------
@router.get("/ticker")
def ticker(matches: int = 8):
    items = []
    recent = criiq_db.execute(
        "SELECT match_id, date, team1, team2 FROM matches "
        "WHERE winner IS NOT NULL ORDER BY date DESC LIMIT ?",
        (min(matches, 20),),
    ).fetchall()

    for m in recent:
        # top run scorer of the match (only if they made 30+)
        bat = criiq_db.execute(
            """SELECT striker, batting_team, SUM(runs_off_bat) AS runs
               FROM deliveries WHERE match_id = ?
               GROUP BY striker ORDER BY runs DESC LIMIT 1""",
            (m["match_id"],),
        ).fetchone()
        if bat and bat["runs"] >= 30:
            opponent = m["team2"] if bat["batting_team"] == m["team1"] else m["team1"]
            items.append({"date": m["date"], "player": bat["striker"],
                          "figure": f"{bat['runs']} runs", "opponent": opponent})

        # best bowler of the match (only if they took 3+)
        bowl = criiq_db.execute(
            """SELECT bowler, bowling_team, COUNT(*) AS wkts
               FROM deliveries
               WHERE match_id = ? AND player_dismissed IS NOT NULL
                 AND wicket_type NOT IN ('run out', 'retired hurt', 'retired out')
               GROUP BY bowler ORDER BY wkts DESC LIMIT 1""",
            (m["match_id"],),
        ).fetchone()
        if bowl and bowl["wkts"] >= 3:
            opponent = m["team2"] if bowl["bowling_team"] == m["team1"] else m["team1"]
            items.append({"date": m["date"], "player": bowl["bowler"],
                          "figure": f"{bowl['wkts']} wickets", "opponent": opponent})

    return {"data": items, "error": None}

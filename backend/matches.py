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

BOWLER_WICKETS = {"bowled", "caught", "lbw", "stumped", "caught and bowled", "hit wicket"}


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
#
# Filters (all optional, all combinable):
#   gender          -- 'male' | 'female'
#   country         -- only matches this team played in, either side
#   team1 + team2   -- head-to-head history between exactly these two teams
#                      (order doesn't matter -- A-vs-B and B-vs-A both match)
# `country` and `team1`/`team2` are deliberately separate params rather than
# overloading one -- a "past matches for my country" filter and a "team A vs
# team B" selector are two different real questions a coach asks, and mixing
# them into one param would make one of the two impossible to express.
# --------------------------------------------------------------------------
@router.get("/matches")
def list_matches(
    completed_limit: int = 10,
    gender: str | None = None,
    country: str | None = None,
    team1: str | None = None,
    team2: str | None = None,
):
    # Filter the raw fixture rows (which carry gender) before mapping to
    # JSON -- fixture_to_json's output has no gender field of its own.
    fixture_rows = app_db.execute("SELECT * FROM fixtures ORDER BY date").fetchall()
    if gender:
        fixture_rows = [f for f in fixture_rows if f["gender"] == gender]
    if country:
        fixture_rows = [f for f in fixture_rows if country in (f["team1"], f["team2"])]
    if team1 and team2:
        fixture_rows = [f for f in fixture_rows if {f["team1"], f["team2"]} == {team1, team2}]
    upcoming = [fixture_to_json(f) for f in fixture_rows]

    where = ["1=1"]
    params: list = []
    if gender:
        where.append("gender = ?")
        params.append(gender)
    if team1 and team2:
        where.append("((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))")
        params.extend([team1, team2, team2, team1])
    elif country:
        where.append("(team1 = ? OR team2 = ?)")
        params.extend([country, country])

    completed = []
    for m in criiq_db.execute(
        f"""SELECT match_id, date, team1, team2, venue_raw, city, winner,
                   win_margin, format, gender, player_of_match
            FROM matches WHERE {' AND '.join(where)}
            ORDER BY date DESC LIMIT ?""",
        (*params, min(completed_limit, 50)),
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
# 10b. GET /teams — distinct real team names, for filter/selector dropdowns
# --------------------------------------------------------------------------
@router.get("/teams")
def list_teams(gender: str | None = None):
    where = "WHERE gender = ?" if gender else ""
    params = (gender,) if gender else ()
    rows = criiq_db.execute(
        f"""SELECT DISTINCT team FROM (
                SELECT team1 AS team, gender FROM matches
                UNION ALL
                SELECT team2 AS team, gender FROM matches
            ) {where}
            ORDER BY team""",
        params,
    ).fetchall()
    return {"data": [r["team"] for r in rows], "error": None}


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

    # Same status/result synthesis as list_matches -- the `matches` table has
    # no `status`/`result` columns of its own, and without these the frontend
    # (mapApiMatch) falls back to classifying every completed match as
    # "Upcoming", hiding the scorecard/win-prob it's otherwise entitled to.
    return {"data": {
        **dict(m), "status": "completed",
        "result": (f"{m['winner']} won by {m['win_margin']}" if m["winner"] else "No result"),
        "innings": innings,
    }, "error": None}


# --------------------------------------------------------------------------
# 11b. GET /matches/{id}/scorecard — real per-player batting/bowling figures,
# built ball-by-ball from `deliveries` (a fixture "f<n>" has none yet).
#
# Mirrors the same shape the simulator's Scorecard/BattingTable/BowlingTable
# components already render for a SIMULATED match's `first_innings_scorecard`/
# `second_innings_scorecard` (see model-training/criiq_models/simulate/
# scorecard.py), so the frontend can reuse one component for both real and
# simulated results. Strike-rate/economy math and the run-out-excluded-from-
# bowling-figures convention mirror data-collection's criiq_data/stats.py
# exactly, so these numbers agree with the analytics DB's own player stats.
# --------------------------------------------------------------------------
def _innings_scorecard(rows: list) -> dict:
    bat_order: list[str] = []
    bat_runs: dict[str, int] = {}
    bat_balls: dict[str, int] = {}
    bat_out: dict[str, bool] = {}

    bowl_order: list[str] = []
    bowl_legal_balls: dict[str, int] = {}
    bowl_conceded: dict[str, int] = {}
    bowl_wkts: dict[str, int] = {}

    for r in rows:
        striker, bowler = r["striker"], r["bowler"]
        if striker not in bat_runs:
            bat_runs[striker], bat_balls[striker] = 0, 0
            bat_order.append(striker)
        bat_runs[striker] += int(r["runs_off_bat"] or 0)
        is_wide = bool(r["wides"])
        is_noball = bool(r["noballs"])
        if not is_wide:
            bat_balls[striker] += 1
        if r["player_dismissed"] == striker:
            bat_out[striker] = True

        if bowler not in bowl_conceded:
            bowl_legal_balls[bowler], bowl_conceded[bowler], bowl_wkts[bowler] = 0, 0, 0
            bowl_order.append(bowler)
        if not is_wide and not is_noball:
            bowl_legal_balls[bowler] += 1
        # runs conceded excludes byes/leg-byes (they're `extras` but not
        # `wides`/`noballs`) -- same as data-collection's stats.py.
        bowl_conceded[bowler] += int(r["runs_off_bat"] or 0) + int(r["wides"] or 0) + int(r["noballs"] or 0)
        if r["player_dismissed"] is not None and r["wicket_type"] in BOWLER_WICKETS:
            bowl_wkts[bowler] += 1

    batting = []
    for name in bat_order:
        b, runs = bat_balls[name], bat_runs[name]
        batting.append({
            "player_id": name, "name": name, "runs": runs, "balls": b,
            "strike_rate": round(100 * runs / b, 1) if b else None,
            "status": "out" if bat_out.get(name) else "not out", "highlight": None,
        })
    if batting:
        for row in batting:
            if row["runs"] >= 100:
                row["highlight"] = f"Century! ({row['runs']} off {row['balls']})"
            elif row["runs"] >= 50:
                row["highlight"] = f"Half-century ({row['runs']} off {row['balls']})"
        top = max(batting, key=lambda r: r["runs"])
        if top["highlight"] is None and top["runs"] > 0:
            top["highlight"] = f"Top scorer ({top['runs']} off {top['balls']})"

    bowling = []
    for name in bowl_order:
        legal = bowl_legal_balls[name]
        bowling.append({
            "player_id": name, "name": name,
            "overs": f"{legal // 6}.{legal % 6}",
            "runs_conceded": bowl_conceded[name], "wickets": bowl_wkts[name],
            "economy": round(6 * bowl_conceded[name] / legal, 2) if legal else None,
            "highlight": None,
        })
    if bowling:
        best = max(bowling, key=lambda r: (r["wickets"], -(r["economy"] if r["economy"] is not None else 999)))
        if best["wickets"] > 0:
            best["highlight"] = f"Pick of the bowlers ({best['wickets']}-for-{best['runs_conceded']})"
        qualified = [r for r in bowling if int(r["overs"].split(".")[0]) >= 2]
        if qualified:
            tightest = min(qualified, key=lambda r: r["economy"] if r["economy"] is not None else 999)
            if tightest["highlight"] is None:
                tightest["highlight"] = f"Most economical (ER {tightest['economy']})"

    return {"batting": batting, "bowling": bowling}


@router.get("/matches/{match_id}/scorecard")
def match_scorecard(match_id: str):
    if match_id.startswith("f") and match_id[1:].isdigit():
        raise HTTPException(400, "No scorecard yet -- this fixture hasn't been played")

    m = criiq_db.execute(
        "SELECT team1, team2 FROM matches WHERE match_id = ?", (match_id,)
    ).fetchone()
    if not m:
        raise HTTPException(404, "Unknown match id")

    deliveries = criiq_db.execute(
        """SELECT innings, batting_team, bowling_team, striker, bowler,
                  runs_off_bat, wides, noballs, wicket_type, player_dismissed
           FROM deliveries WHERE match_id = ? ORDER BY innings, over, ball_in_over, id""",
        (match_id,),
    ).fetchall()
    if not deliveries:
        raise HTTPException(404, "No ball-by-ball data on file for this match")

    by_innings: dict[int, list] = {}
    for r in deliveries:
        by_innings.setdefault(r["innings"], []).append(r)

    innings_cards = []
    for innings_no in sorted(by_innings):
        rows = by_innings[innings_no]
        card = _innings_scorecard(rows)
        innings_cards.append({
            "innings": innings_no,
            "batting_team": rows[0]["batting_team"],
            "bowling_team": rows[0]["bowling_team"],
            **card,
        })

    return {"data": {"match_id": match_id, "team1": m["team1"], "team2": m["team2"],
                      "innings": innings_cards}, "error": None}


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

from __future__ import annotations

from .logging_utils import get_logger

log = get_logger("h2h")

BOWLER_WICKETS = {"bowled", "caught", "lbw", "stumped", "caught and bowled", "hit wicket"}
_BW_PLACEHOLDERS = ",".join("?" for _ in BOWLER_WICKETS)


def names_for_player(conn, player_id: str) -> tuple[list[str], str | None]:
    """(display names, gender) for a player_id. `identifier_map` has no
    gender column and stores one shared name list per raw Cricsheet
    identifier -- for the handful of identifiers reused across two genuinely
    different real people of different genders (see identity.py), the name
    list alone can't tell them apart, and every query built from it MUST also
    filter by this returned `gender` or it will silently blend both real
    people's deliveries (a real bug this fixes, not a hypothetical one).
    `gender` is `players.gender` for this player_id -- `None` for the
    overwhelming majority of (unsplit, unambiguous) players, in which case no
    filter is needed at all since no other real person shares the identifier.
    """
    row = conn.execute(
        "SELECT cricsheet_identifier, gender FROM players WHERE player_id=?", (player_id,)
    ).fetchone()
    if not row or not row["cricsheet_identifier"]:
        return [], None
    names = [r["player_name"] for r in conn.execute(
        "SELECT player_name FROM identifier_map WHERE identifier=?",
        (row["cricsheet_identifier"],))]
    return names, row["gender"]


def _in(names: list[str]) -> str:
    return ",".join("?" for _ in names)


def batter_vs_bowler(conn, fmt: str, batter_names: list[str],
                     bowler_names: list[str], batter_gender: str | None = None,
                     bowler_gender: str | None = None) -> dict:
    """`batter_gender`/`bowler_gender`: from `names_for_player` -- pass these
    through whenever the names came from a resolved player_id, or a
    colliding identifier's two real people (of different genders) get their
    deliveries silently summed together. `None` means "no disambiguation
    needed" (the identifier isn't split), not "any gender".  A genuine match
    always has one gender, so if both are set they must agree or the filter
    (correctly) returns nothing -- these two names never actually played
    each other.
    """
    if not batter_names or not bowler_names:
        return {"balls": 0, "runs": 0, "dismissals": 0, "strike_rate": None,
                "dismissal_rate": None}
    gender = batter_gender or bowler_gender
    gender_clause = " AND m.gender=?" if gender else ""
    sql = f"""
        SELECT
            SUM(CASE WHEN d.wides=0 THEN 1 ELSE 0 END)            AS balls,
            SUM(d.runs_off_bat)                                   AS runs,
            SUM(CASE WHEN d.player_dismissed IN ({_in(batter_names)})
                      AND d.wicket_type IN ({_BW_PLACEHOLDERS})
                     THEN 1 ELSE 0 END)                           AS dismissals
        FROM deliveries d JOIN matches m ON d.match_id=m.match_id
        WHERE m.format=? AND m.team_type='international' AND d.striker IN ({_in(batter_names)})
          AND d.bowler IN ({_in(bowler_names)}){gender_clause}
    """
    params = (list(batter_names) + list(BOWLER_WICKETS) + [fmt]
              + list(batter_names) + list(bowler_names)
              + ([gender] if gender else []))
    row = conn.execute(sql, params).fetchone()
    balls = row["balls"] or 0
    runs = row["runs"] or 0
    dis = row["dismissals"] or 0
    return {
        "balls": balls, "runs": runs, "dismissals": dis,
        "strike_rate": round(100 * runs / balls, 1) if balls else None,
        "dismissal_rate": round(dis / balls, 4) if balls else None,
    }


def player_vs_team(conn, fmt: str, player_id: str, opponent_team: str) -> dict:
    names, gender = names_for_player(conn, player_id)
    if not names or not opponent_team:
        return {}
    gender_clause = " AND m.gender=?" if gender else ""
    gender_param = [gender] if gender else []

    bat_sql = f"""
        SELECT
            SUM(CASE WHEN d.wides=0 THEN 1 ELSE 0 END)  AS balls,
            SUM(d.runs_off_bat)                          AS runs,
            SUM(CASE WHEN d.player_dismissed IN ({_in(names)}) THEN 1 ELSE 0 END) AS outs
        FROM deliveries d JOIN matches m ON d.match_id=m.match_id
        WHERE m.format=? AND m.team_type='international'
          AND d.striker IN ({_in(names)}) AND d.bowling_team=?{gender_clause}
    """
    b = conn.execute(bat_sql, list(names) + [fmt] + list(names) + [opponent_team] + gender_param).fetchone()

    bowl_sql = f"""
        SELECT
            SUM(CASE WHEN d.wides=0 AND d.noballs=0 THEN 1 ELSE 0 END) AS balls,
            SUM(d.runs_off_bat + d.wides + d.noballs)                  AS runs,
            SUM(CASE WHEN d.wicket_type IN ({_BW_PLACEHOLDERS})
                          AND d.player_dismissed IS NOT NULL THEN 1 ELSE 0 END) AS wkts
        FROM deliveries d JOIN matches m ON d.match_id=m.match_id
        WHERE m.format=? AND m.team_type='international'
          AND d.bowler IN ({_in(names)}) AND d.batting_team=?{gender_clause}
    """
    w = conn.execute(bowl_sql, list(BOWLER_WICKETS) + [fmt] + list(names) + [opponent_team] + gender_param).fetchone()

    out = {"opponent": opponent_team}
    if (b["balls"] or 0) > 0:
        out["batting"] = {
            "balls": b["balls"], "runs": b["runs"] or 0, "dismissals": b["outs"] or 0,
            "strike_rate": round(100 * (b["runs"] or 0) / b["balls"], 1),
        }
    if (w["balls"] or 0) > 0:
        runs, balls, wkts = w["runs"] or 0, w["balls"], w["wkts"] or 0
        out["bowling"] = {
            "balls": balls, "runs_conceded": runs, "wickets": wkts,
            "economy": round(6 * runs / balls, 2),
        }
    return out

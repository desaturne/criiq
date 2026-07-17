from __future__ import annotations

import pandas as pd

from .h2h import BOWLER_WICKETS
from .logging_utils import get_logger

log = get_logger("stats")


def build_innings(conn, fmt: str, team_type: str | None = "international") -> pd.DataFrame:
    """One row per (identifier, match_id): batting + bowling for that match.

    `team_type='international'` (the default) is what every existing career/
    impact/phase/venue/opponent builder expects and has always effectively
    gotten -- before domestic leagues were ingested, every match *was*
    international, so this default preserves their behaviour unchanged.
    Pass `team_type=None` for every match regardless of competition, or
    `team_type='club'` for domestic-only (used by `wpa.py`'s domestic-form
    aggregate) -- never silently blend the two under one 'career' number.
    """
    tt_clause_aliased = " AND m.team_type = ?" if team_type is not None else ""
    tt_clause_plain = " AND team_type = ?" if team_type is not None else ""
    tt_params = (fmt, team_type) if team_type is not None else (fmt,)
    deliv = pd.read_sql_query(
        f"""
        SELECT d.match_id, d.striker, d.bowler, d.runs_off_bat, d.wides,
               d.noballs, d.runs_total, d.wicket_type, d.player_dismissed
        FROM deliveries d JOIN matches m ON d.match_id = m.match_id
        WHERE m.format = ?{tt_clause_aliased}
        """, conn, params=tt_params)
    if deliv.empty:
        return pd.DataFrame()

    matches = pd.read_sql_query(
        f"SELECT match_id, date, gender, team1, team2, winner, venue_id "
        f"FROM matches WHERE format = ?{tt_clause_plain}", conn, params=tt_params)
    mp = pd.read_sql_query("SELECT match_id, player_name, team FROM match_players", conn)
    idmap = pd.read_sql_query("SELECT player_name, identifier FROM identifier_map", conn)

    legal = deliv["wides"].fillna(0) == 0
    legal_bowl = legal & (deliv["noballs"].fillna(0) == 0)

    bat = deliv.assign(_balls=legal.astype(int)).groupby(["match_id", "striker"]).agg(
        runs=("runs_off_bat", "sum"), balls_faced=("_balls", "sum")).reset_index()
    bat = bat.rename(columns={"striker": "player_name"})

    outs = (deliv.loc[deliv["player_dismissed"].notna(), ["match_id", "player_dismissed"]]
            .drop_duplicates().assign(out=1)
            .rename(columns={"player_dismissed": "player_name"}))

    bowl_credit = deliv["wicket_type"].isin(BOWLER_WICKETS) & deliv["player_dismissed"].notna()
    bw = deliv.assign(
        _bb=legal_bowl.astype(int),
        _rc=(deliv["runs_off_bat"].fillna(0) + deliv["wides"].fillna(0) + deliv["noballs"].fillna(0)),
        _wk=bowl_credit.astype(int),
        # Dot ball: a legal delivery off which the batting team scored
        # nothing at all (the standard commentary definition). A wide/no-ball is
        # never a dot: the bowler has already conceded a run by bowling it.
        # A bye/leg-bye is also never a dot in practice: `runs_total` counts
        # any run scored off the delivery regardless of source, and a real
        # bye/leg-bye is by definition at least 1 run -- so this criterion
        # naturally excludes them too, it isn't a special case being made
        # here for byes specifically.
        _dot=(legal_bowl & (deliv["runs_total"].fillna(0) == 0)).astype(int),
        # Boundary conceded off the bat (4s/6s) -- containment quality that
        # economy alone doesn't distinguish from "gave away ones and twos".
        _bdry=(legal_bowl & (deliv["runs_off_bat"].fillna(0) >= 4)).astype(int),
    ).groupby(["match_id", "bowler"]).agg(
        balls_bowled=("_bb", "sum"), runs_conceded=("_rc", "sum"),
        wickets=("_wk", "sum"), dot_balls=("_dot", "sum"),
        boundary_balls=("_bdry", "sum")).reset_index()
    bw = bw.rename(columns={"bowler": "player_name"})

    pm = bat.merge(bw, on=["match_id", "player_name"], how="outer")
    pm = pm.merge(outs, on=["match_id", "player_name"], how="left")
    for c in ["runs", "balls_faced", "balls_bowled", "runs_conceded", "wickets",
              "dot_balls", "boundary_balls", "out"]:
        pm[c] = pm[c].fillna(0)

    pm = pm.merge(mp, on=["match_id", "player_name"], how="left")
    pm = pm.merge(matches, on="match_id", how="left")
    pm["opponent"] = pm.apply(
        lambda r: r["team2"] if r["team"] == r["team1"] else r["team1"], axis=1)
    pm["won"] = (pm["team"].notna() & (pm["team"] == pm["winner"])).astype(int)

    pm = pm.merge(idmap, on="player_name", how="left")
    pm = pm[pm["identifier"].notna()]

    agg = pm.groupby(["identifier", "match_id"]).agg(
        runs=("runs", "sum"), balls_faced=("balls_faced", "sum"),
        balls_bowled=("balls_bowled", "sum"), runs_conceded=("runs_conceded", "sum"),
        wickets=("wickets", "sum"), dot_balls=("dot_balls", "sum"),
        boundary_balls=("boundary_balls", "sum"), out=("out", "max"),
        team=("team", "first"), opponent=("opponent", "first"),
        won=("won", "max"), date=("date", "first"), gender=("gender", "first"),
        venue_id=("venue_id", "first"),
    ).reset_index()
    agg["date"] = pd.to_datetime(agg["date"], errors="coerce")
    return agg

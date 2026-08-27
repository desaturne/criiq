from __future__ import annotations

import datetime as dt

import pandas as pd

from .config import enabled_sources
from .db import set_meta
from .h2h import BOWLER_WICKETS
from .identity import player_id_map
from .logging_utils import get_logger
from .stats import build_innings

log = get_logger("phases")

MIN_BAT_BALLS = 30
MIN_BOWL_BALLS = 30


def phase_of(over) -> str:
    over = int(over) if over is not None else 0
    if over <= 5:
        return "powerplay"
    if over <= 14:
        return "middle"
    return "death"


def _team_map(conn, fmt: str) -> dict:
    inn = build_innings(conn, fmt)
    if inn.empty:
        return {}
    return (inn.dropna(subset=["team"]).groupby(["identifier", "gender"])["team"]
            .agg(lambda s: s.mode().iloc[0] if not s.mode().empty else None).to_dict())


def build_for_format(conn, fmt: str) -> int:
    d = pd.read_sql_query(
        "SELECT d.over, d.striker, d.bowler, d.runs_off_bat, d.wides, d.noballs, "
        "d.wicket_type, d.player_dismissed, m.gender "
        "FROM deliveries d JOIN matches m ON d.match_id=m.match_id "
        "WHERE m.format=? AND m.team_type='international'",
        conn, params=(fmt,))
    if d.empty:
        return 0
    n2i = {r["player_name"]: r["identifier"]
           for r in conn.execute("SELECT player_name, identifier FROM identifier_map")}
    unambiguous, split = player_id_map(conn)
    # keyed by (identifier, gender), not just identifier: a few Cricsheet ids
    # are shared by two different people (see identity.py), so without gender we'd rank the wrong person's peer group.
    teams = _team_map(conn, fmt)

    d["phase"] = d["over"].map(phase_of)
    d["rob"] = d["runs_off_bat"].fillna(0).astype(int)
    d["legal"] = (d["wides"].fillna(0) == 0).astype(int)
    d["legal_bowl"] = ((d["wides"].fillna(0) == 0) & (d["noballs"].fillna(0) == 0)).astype(int)
    d["rc"] = d["rob"] + d["wides"].fillna(0).astype(int) + d["noballs"].fillna(0).astype(int)
    d["sid"] = d["striker"].map(n2i)
    d["bid"] = d["bowler"].map(n2i)

    bat = d.dropna(subset=["sid"]).copy()
    bat["bdry"] = bat["rob"].isin([4, 6]).astype(int) * bat["legal"]
    bat["dot"] = ((bat["legal"] == 1) & (bat["rob"] == 0)).astype(int)
    bat["out_self"] = ((bat["player_dismissed"] == bat["striker"])).astype(int)
    bg = bat.groupby(["sid", "gender", "phase"]).agg(
        balls=("legal", "sum"), runs=("rob", "sum"), bdry=("bdry", "sum"),
        dots=("dot", "sum"), dis=("out_self", "sum")).reset_index()
    bg["sr"] = (100 * bg["runs"] / bg["balls"]).round(1)
    bg["team"] = [teams.get((s, g)) for s, g in zip(bg["sid"], bg["gender"])]

    bw = d.dropna(subset=["bid"]).copy()
    bw["dotb"] = ((bw["legal_bowl"] == 1) & (bw["rc"] == 0)).astype(int)
    bw["wkt"] = (bw["wicket_type"].isin(BOWLER_WICKETS) & bw["player_dismissed"].notna()).astype(int)
    wg = bw.groupby(["bid", "gender", "phase"]).agg(
        balls=("legal_bowl", "sum"), runs=("rc", "sum"), wkts=("wkt", "sum"),
        dots=("dotb", "sum")).reset_index()
    wg["econ"] = (6 * wg["runs"] / wg["balls"]).round(2)
    wg["team"] = [teams.get((b, g)) for b, g in zip(wg["bid"], wg["gender"])]

    def _rank(df, value, ascending, min_balls):
        df = df.copy()
        elig = df["balls"] >= min_balls
        df["rank"] = None
        df["size"] = None
        for (team, phase), grp in df[elig].groupby(["team", "phase"]):
            order = grp[value].rank(ascending=ascending, method="min")
            n = len(grp)
            df.loc[grp.index, "rank"] = order.astype(int)
            df.loc[grp.index, "size"] = n
        return df
    bg = _rank(bg, "sr", ascending=False, min_balls=MIN_BAT_BALLS)
    wg = _rank(wg, "econ", ascending=True, min_balls=MIN_BOWL_BALLS)

    bat_idx = {(r.sid, r.gender, r.phase): r for r in bg.itertuples(index=False)}
    bowl_idx = {(r.bid, r.gender, r.phase): r for r in wg.itertuples(index=False)}

    now = dt.datetime.now().isoformat(timespec="seconds")
    keys = {(s, g, p) for s, g, p in bat_idx} | {(b, g, p) for b, g, p in bowl_idx}
    rows = []
    for ident, gender, phase in keys:
        pid = unambiguous.get(ident) or split.get((ident, gender))
        if not pid:
            continue
        b = bat_idx.get((ident, gender, phase))
        w = bowl_idx.get((ident, gender, phase))
        bpct = (round(100 * (b.size - b.rank) / (b.size - 1), 0)
                if b is not None and pd.notna(b.rank) and b.size and b.size > 1 else
                (100.0 if b is not None and pd.notna(b.rank) else None))
        rows.append((
            pid, fmt, phase,
            int(b.balls) if b is not None else None,
            int(b.runs) if b is not None else None,
            float(b.sr) if b is not None else None,
            round(100 * b.bdry / b.balls, 1) if b is not None and b.balls else None,
            round(100 * b.dots / b.balls, 1) if b is not None and b.balls else None,
            int(b.dis) if b is not None else None,
            int(b.rank) if b is not None and pd.notna(b.rank) else None,
            int(b.size) if b is not None and pd.notna(b.size) else None, bpct,
            int(w.balls) if w is not None else None,
            int(w.runs) if w is not None else None,
            int(w.wkts) if w is not None else None,
            float(w.econ) if w is not None else None,
            round(100 * w.dots / w.balls, 1) if w is not None and w.balls else None,
            int(w.rank) if w is not None and pd.notna(w.rank) else None,
            int(w.size) if w is not None and pd.notna(w.size) else None, now,
        ))
    conn.executemany(
        "INSERT INTO player_phase(player_id, format, phase, bat_balls, bat_runs, "
        "bat_strike_rate, bat_boundary_pct, bat_dot_pct, bat_dismissals, bat_team_rank, "
        "bat_team_size, bat_team_percentile, bowl_balls, bowl_runs, bowl_wickets, "
        "bowl_economy, bowl_dot_pct, bowl_team_rank, bowl_team_size, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id, format, phase) DO UPDATE SET "
        "bat_balls=excluded.bat_balls, bat_runs=excluded.bat_runs, "
        "bat_strike_rate=excluded.bat_strike_rate, bat_boundary_pct=excluded.bat_boundary_pct, "
        "bat_dot_pct=excluded.bat_dot_pct, bat_dismissals=excluded.bat_dismissals, "
        "bat_team_rank=excluded.bat_team_rank, bat_team_size=excluded.bat_team_size, "
        "bat_team_percentile=excluded.bat_team_percentile, bowl_balls=excluded.bowl_balls, "
        "bowl_runs=excluded.bowl_runs, bowl_wickets=excluded.bowl_wickets, "
        "bowl_economy=excluded.bowl_economy, bowl_dot_pct=excluded.bowl_dot_pct, "
        "bowl_team_rank=excluded.bowl_team_rank, bowl_team_size=excluded.bowl_team_size, "
        "updated_at=excluded.updated_at", rows)
    conn.commit()
    log.info("phases %s: %d player-phase rows", fmt, len(rows))
    return len(rows)


def build_phases(conn) -> dict:
    out = {}
    for fmt in sorted({s.fmt for s in enabled_sources()}):
        out[fmt] = build_for_format(conn, fmt)
    set_meta(conn, "phases_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out


def get_phases(conn, player_id: str, fmt: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM player_phase WHERE player_id=? AND format=? "
        "ORDER BY CASE phase WHEN 'powerplay' THEN 1 WHEN 'middle' THEN 2 ELSE 3 END",
        (player_id, fmt))]


def phase_vs_opponent(conn, player_id: str, fmt: str) -> dict:
    from .h2h import names_for_player
    names, gender = names_for_player(conn, player_id)
    if not names:
        return {}
    ph = ",".join("?" for _ in names)
    gender_clause = " AND m.gender=?" if gender else ""
    rows = conn.execute(
        f"SELECT d.bowling_team AS opponent, d.over, d.runs_off_bat, d.wides, "
        f"d.player_dismissed, d.striker "
        f"FROM deliveries d JOIN matches m ON d.match_id=m.match_id "
        f"WHERE m.format=? AND m.team_type='international' AND d.striker IN ({ph}){gender_clause}",
        [fmt] + list(names) + ([gender] if gender else [])).fetchall()
    agg: dict = {}
    for r in rows:
        if (r["wides"] or 0) != 0:
            continue
        opp = r["opponent"]; phase = phase_of(r["over"])
        cell = agg.setdefault(opp, {}).setdefault(phase, {"balls": 0, "runs": 0, "dis": 0})
        cell["balls"] += 1
        cell["runs"] += r["runs_off_bat"] or 0
        if r["player_dismissed"] == r["striker"]:
            cell["dis"] += 1
    for opp in agg:
        for phase, c in agg[opp].items():
            c["strike_rate"] = round(100 * c["runs"] / c["balls"], 1) if c["balls"] else None
    return agg

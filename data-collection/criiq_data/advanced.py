from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from .config import enabled_sources
from .db import set_meta
from .h2h import BOWLER_WICKETS
from .logging_utils import get_logger
from . import styles

log = get_logger("advanced")

def _phase(over):
    if over <= 5:
        return "powerplay"
    if over <= 14:
        return "middle"
    return "death"

MIN_PHASE_BALLS = 24


def _name_to_id(conn) -> dict[str, str]:
    return {r["player_name"]: r["identifier"]
            for r in conn.execute("SELECT player_name, identifier FROM identifier_map")}


def _bat_rate(runs, balls):
    return round(100 * runs / balls, 1) if balls else None


def build_for_format(conn, fmt: str) -> int:
    deliv = pd.read_sql_query(
        "SELECT d.match_id, d.innings, d.over, d.ball_in_over, d.striker, d.bowler, "
        "d.runs_off_bat, d.wides, d.noballs, d.wicket_type, d.player_dismissed "
        "FROM deliveries d JOIN matches m ON d.match_id=m.match_id WHERE m.format=?",
        conn, params=(fmt,))
    if deliv.empty:
        log.info("advanced %s: no deliveries", fmt)
        return 0

    n2i = _name_to_id(conn)
    bowl_bucket = styles.bowler_buckets(conn)
    bat_hand = styles.batter_hands(conn)
    players = {r["cricsheet_identifier"]: r["player_id"]
               for r in conn.execute("SELECT cricsheet_identifier, player_id FROM players")}

    deliv["striker_id"] = deliv["striker"].map(n2i)
    deliv["bowler_id"] = deliv["bowler"].map(n2i)
    deliv["over"] = deliv["over"].fillna(0).astype(int)
    deliv["rob"] = deliv["runs_off_bat"].fillna(0).astype(int)
    deliv["wd"] = deliv["wides"].fillna(0).astype(int)
    deliv["nb"] = deliv["noballs"].fillna(0).astype(int)
    deliv["legal"] = (deliv["wd"] == 0)
    deliv["legal_bowl"] = (deliv["wd"] == 0) & (deliv["nb"] == 0)
    deliv["phase"] = deliv["over"].map(_phase)
    deliv["rc"] = deliv["rob"] + deliv["wd"] + deliv["nb"]
    deliv["bwkt"] = deliv["wicket_type"].isin(BOWLER_WICKETS) & deliv["player_dismissed"].notna()

    bat = deliv.dropna(subset=["striker_id"]).copy()
    bat["out_self"] = bat["player_dismissed"].notna() & (bat["player_dismissed"] == bat["striker"])
    bat["four"] = (bat["rob"] == 4).astype(int)
    bat["six"] = (bat["rob"] == 6).astype(int)
    bat["bdry"] = bat["four"] + bat["six"]
    bat["dot"] = (bat["legal"] & (bat["rob"] == 0)).astype(int)
    bat["scored"] = (bat["legal"] & (bat["rob"] > 0)).astype(int)
    bat["rotate"] = (bat["legal"] & bat["rob"].isin([1, 2, 3])).astype(int)
    bat["lb"] = bat["legal"].astype(int)

    bat_overall = bat.groupby("striker_id").agg(
        runs=("rob", "sum"), balls=("lb", "sum"), fours=("four", "sum"),
        sixes=("six", "sum"), bdry=("bdry", "sum"), dots=("dot", "sum"),
        rotate=("rotate", "sum"), outs=("out_self", "sum")).to_dict("index")
    bat_innings = (bat.drop_duplicates(["striker_id", "match_id", "innings"])
                   .groupby("striker_id").size().to_dict())

    def _nest_phase(df, idcol):
        d = df.groupby([idcol, "phase"]).agg(
            runs=("rob", "sum"), balls=("lb", "sum"), bdry=("bdry", "sum"),
            dots=("dot", "sum"), outs=("out_self", "sum"))
        out = {}
        for (pid, ph), row in d.iterrows():
            out.setdefault(pid, {})[ph] = row.to_dict()
        return out
    bat_phase = _nest_phase(bat, "striker_id")

    bat["bowl_bucket"] = bat["bowler"].map(bowl_bucket)
    vt = bat.dropna(subset=["bowl_bucket"]).groupby(["striker_id", "bowl_bucket"]).agg(
        runs=("rob", "sum"), balls=("lb", "sum"), outs=("out_self", "sum"))
    bat_vs_type: dict = {}
    for (pid, bk), row in vt.iterrows():
        bat_vs_type.setdefault(pid, {})[bk] = row.to_dict()

    legal = bat[bat["legal"]].sort_values(["match_id", "innings", "over", "ball_in_over"])
    legal["ball_no"] = legal.groupby(["match_id", "innings", "striker_id"]).cumcount() + 1
    legal["accel"] = (legal["ball_no"] > 10).map({False: "first10", True: "after10"})
    ac = legal.groupby(["striker_id", "accel"]).agg(runs=("rob", "sum"), balls=("ball_no", "count"))
    accel: dict = {}
    for (pid, a), row in ac.iterrows():
        accel.setdefault(pid, {})[a] = {"runs": int(row["runs"]), "balls": int(row["balls"])}

    bw = deliv.dropna(subset=["bowler_id"]).copy()
    bw["lbb"] = bw["legal_bowl"].astype(int)
    bw["dotb"] = (bw["legal_bowl"] & (bw["rc"] == 0)).astype(int)
    bw["wktb"] = bw["bwkt"].astype(int)
    bowl_overall = bw.groupby("bowler_id").agg(
        balls=("lbb", "sum"), runs=("rc", "sum"), wkts=("wktb", "sum"),
        dots=("dotb", "sum")).to_dict("index")

    bp = bw.groupby(["bowler_id", "phase"]).agg(
        balls=("lbb", "sum"), runs=("rc", "sum"), wkts=("wktb", "sum"), dots=("dotb", "sum"))
    bowl_phase: dict = {}
    for (pid, ph), row in bp.iterrows():
        bowl_phase.setdefault(pid, {})[ph] = row.to_dict()

    bw["bat_hand"] = bw["striker"].map(bat_hand)
    vh = bw.dropna(subset=["bat_hand"]).groupby(["bowler_id", "bat_hand"]).agg(
        balls=("lbb", "sum"), runs=("rc", "sum"), wkts=("wktb", "sum"))
    bowl_vs_hand: dict = {}
    for (pid, h), row in vh.iterrows():
        bowl_vs_hand.setdefault(pid, {})[h] = row.to_dict()

    now = dt.datetime.now().isoformat(timespec="seconds")
    rows = []
    all_ids = set(bat_overall) | set(bowl_overall)
    for ident in all_ids:
        pid = players.get(ident)
        if not pid:
            continue
        profile = {"format": fmt}
        archetype = None

        bo = bat_overall.get(ident)
        if bo and bo["balls"] > 0:
            profile["batting"] = _batting_block(bo, bat_innings.get(ident, 0),
                                                bat_phase.get(ident, {}),
                                                bat_vs_type.get(ident, {}),
                                                accel.get(ident, {}))
            archetype = profile["batting"]["archetype"]

        bwo = bowl_overall.get(ident)
        if bwo and bwo["balls"] > 0:
            profile["bowling"] = _bowling_block(bwo, bowl_phase.get(ident, {}),
                                                bowl_vs_hand.get(ident, {}))

        profile["strengths"] = _strengths_summary(profile)
        profile["meta"] = {"updated_at": now}
        rows.append((pid, fmt, archetype, json.dumps(profile), now))

    conn.executemany(
        "INSERT INTO player_advanced(player_id, format, archetype, profile_json, updated_at) "
        "VALUES(?,?,?,?,?) ON CONFLICT(player_id, format) DO UPDATE SET "
        "archetype=excluded.archetype, profile_json=excluded.profile_json, "
        "updated_at=excluded.updated_at", rows)
    conn.commit()
    log.info("advanced %s: %d profiles built", fmt, len(rows))
    return len(rows)


def _phase_block(d: dict) -> dict:
    balls = d["balls"]
    return {
        "runs": int(d["runs"]), "balls": int(balls),
        "strike_rate": _bat_rate(d["runs"], balls),
        "boundary_pct": round(100 * d["bdry"] / balls, 1) if balls else None,
        "dot_pct": round(100 * d["dots"] / balls, 1) if balls else None,
        "dismissals": int(d["outs"]),
    }


def _batting_block(bo, innings, phase, vs_type, accel) -> dict:
    balls = bo["balls"]
    block = {
        "innings": int(innings), "runs": int(bo["runs"]), "balls": int(balls),
        "strike_rate": _bat_rate(bo["runs"], balls),
        "average": round(bo["runs"] / bo["outs"], 1) if bo["outs"] else None,
        "boundary_pct": round(100 * bo["bdry"] / balls, 1) if balls else None,
        "dot_pct": round(100 * bo["dots"] / balls, 1) if balls else None,
        "scoring_pct": round(100 * (balls - bo["dots"]) / balls, 1) if balls else None,
        "rotation_pct": round(100 * bo["rotate"] / balls, 1) if balls else None,
        "fours": int(bo["fours"]), "sixes": int(bo["sixes"]),
        "by_phase": {ph: _phase_block(phase[ph]) for ph in phase},
    }
    if vs_type:
        block["vs_bowling_type"] = {
            t: {"balls": int(v["balls"]), "runs": int(v["runs"]),
                "strike_rate": _bat_rate(v["runs"], v["balls"]),
                "dismissals": int(v["outs"])}
            for t, v in vs_type.items()}
    if accel:
        block["acceleration"] = {
            k: {"balls": v["balls"], "strike_rate": _bat_rate(v["runs"], v["balls"])}
            for k, v in accel.items()}
    block["archetype"] = _archetype(block)
    return block


def _archetype(b: dict) -> str:
    by = b.get("by_phase", {})
    total = b["balls"] or 1
    death_balls = by.get("death", {}).get("balls", 0)
    pp_balls = by.get("powerplay", {}).get("balls", 0)
    sr = b.get("strike_rate") or 0
    death_share = death_balls / total
    pp_share = pp_balls / total
    if death_share > 0.30 and (by.get("death", {}).get("strike_rate") or 0) > 130:
        return "finisher"
    if sr >= 135:
        return "aggressor"
    if pp_share > 0.45 and sr < 115:
        return "anchor"
    return "balanced"


def _bowling_block(bo, phase, vs_hand) -> dict:
    balls = bo["balls"]
    block = {
        "balls": int(balls), "overs": f"{int(balls)//6}.{int(balls)%6}",
        "runs": int(bo["runs"]), "wickets": int(bo["wkts"]),
        "economy": round(6 * bo["runs"] / balls, 2) if balls else None,
        "dot_pct": round(100 * bo["dots"] / balls, 1) if balls else None,
        "strike_rate": round(balls / bo["wkts"], 1) if bo["wkts"] else None,
        "average": round(bo["runs"] / bo["wkts"], 1) if bo["wkts"] else None,
        "by_phase": {ph: {
            "overs": f"{int(phase[ph]['balls'])//6}.{int(phase[ph]['balls'])%6}",
            "economy": round(6 * phase[ph]["runs"] / phase[ph]["balls"], 2) if phase[ph]["balls"] else None,
            "wickets": int(phase[ph]["wkts"]),
            "dot_pct": round(100 * phase[ph]["dots"] / phase[ph]["balls"], 1) if phase[ph]["balls"] else None,
        } for ph in phase},
    }
    tot = sum(phase[ph]["balls"] for ph in phase) or 1
    block["usage_share"] = {ph: round(phase[ph]["balls"] / tot, 2) for ph in phase}
    if vs_hand:
        block["vs_batting_hand"] = {
            h: {"balls": int(v["balls"]), "economy": round(6 * v["runs"] / v["balls"], 2) if v["balls"] else None,
                "wickets": int(v["wkts"])}
            for h, v in vs_hand.items()}
    return block


def _strengths_summary(profile: dict) -> list[str]:
    out: list[str] = []
    b = profile.get("batting")
    if b:
        out.append(f"Batting archetype: {b['archetype']}")
        phases = {ph: v for ph, v in b.get("by_phase", {}).items()
                  if v["balls"] >= MIN_PHASE_BALLS and v["strike_rate"]}
        if phases:
            best = max(phases, key=lambda p: phases[p]["strike_rate"])
            out.append(f"Best phase: {best} (SR {phases[best]['strike_rate']}, "
                       f"{phases[best]['boundary_pct']}% boundaries)")
        if b.get("boundary_pct") and b["boundary_pct"] >= 16:
            out.append(f"Boundary-heavy ({b['boundary_pct']}% of balls)")
        vt = b.get("vs_bowling_type", {})
        if "pace" in vt and "spin" in vt and vt["pace"]["strike_rate"] and vt["spin"]["strike_rate"]:
            if vt["pace"]["strike_rate"] > vt["spin"]["strike_rate"] * 1.15:
                out.append(f"Stronger vs pace (SR {vt['pace']['strike_rate']} vs "
                           f"{vt['spin']['strike_rate']} vs spin) — attack with spin")
            elif vt["spin"]["strike_rate"] > vt["pace"]["strike_rate"] * 1.15:
                out.append(f"Stronger vs spin (SR {vt['spin']['strike_rate']} vs "
                           f"{vt['pace']['strike_rate']} vs pace) — attack with pace")
    bw = profile.get("bowling")
    if bw:
        phases = {ph: v for ph, v in bw.get("by_phase", {}).items()
                  if v["economy"] is not None}
        if phases:
            best = min(phases, key=lambda p: phases[p]["economy"])
            out.append(f"Most economical in {best} ({phases[best]['economy']} RPO)")
        if bw.get("usage_share", {}).get("death", 0) >= 0.3:
            out.append("Used as a death-overs bowler")
        if bw.get("usage_share", {}).get("powerplay", 0) >= 0.3:
            out.append("Used with the new ball (powerplay)")
        if bw.get("strike_rate"):
            out.append(f"Bowling strike rate {bw['strike_rate']} balls/wicket")
    return out


def build_advanced(conn) -> dict:
    formats = sorted({s.fmt for s in enabled_sources()})
    out = {}
    for fmt in formats:
        out[fmt] = build_for_format(conn, fmt)
    set_meta(conn, "advanced_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out


def get_advanced(conn, player_id: str, fmt: str) -> dict | None:
    row = conn.execute("SELECT profile_json FROM player_advanced WHERE player_id=? AND format=?",
                       (player_id, fmt)).fetchone()
    return json.loads(row["profile_json"]) if row else None

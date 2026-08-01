from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from .config import enabled_sources
from .db import set_meta
from .h2h import BOWLER_WICKETS
from .identity import player_id_map
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
        "d.runs_off_bat, d.wides, d.noballs, d.wicket_type, d.player_dismissed, m.gender "
        "FROM deliveries d JOIN matches m ON d.match_id=m.match_id "
        "WHERE m.format=? AND m.team_type='international'",
        conn, params=(fmt,))
    if deliv.empty:
        log.info("advanced %s: no deliveries", fmt)
        return 0

    n2i = _name_to_id(conn)
    bowl_bucket = styles.bowler_buckets(conn)
    bowl_bucket_detail = styles.bowler_buckets(conn, detail=True)
    bat_hand = styles.batter_hands(conn)
    unambiguous, split = player_id_map(conn)
    # (cricsheet_identifier, gender) -> (batting_hand, bowling_style); the
    # handful of identifiers reused across two different people (see
    # identity.py) can have different style metadata for each.
    style_meta = {}
    for r in conn.execute(
            "SELECT cricsheet_identifier, gender, batting_hand, bowling_style FROM players"):
        style_meta[(r["cricsheet_identifier"], r["gender"])] = (r["batting_hand"], r["bowling_style"])

    def _style_meta(ident, gender):
        return style_meta.get((ident, None)) or style_meta.get((ident, gender)) or (None, None)

    def _lookup_by_name_gender(names: pd.Series, genders: pd.Series, mapping: dict) -> pd.Series:
        """`bowler_buckets`/`batter_hands` are keyed (name, gender), `None`
        for unsplit names. tries the split-specific key first, falling back
        to the unsplit `None` key.
        """
        exact = pd.Series(list(zip(names, genders)), index=names.index).map(mapping)
        fallback = pd.Series(list(zip(names, [None] * len(names))), index=names.index).map(mapping)
        return exact.fillna(fallback)

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

    # gender kept in every group key throughout: colliding identifiers would
    # otherwise blend two different people's deliveries into one profile.
    bat_overall = bat.groupby(["striker_id", "gender"]).agg(
        runs=("rob", "sum"), balls=("lb", "sum"), fours=("four", "sum"),
        sixes=("six", "sum"), bdry=("bdry", "sum"), dots=("dot", "sum"),
        rotate=("rotate", "sum"), outs=("out_self", "sum")).to_dict("index")
    bat_innings = (bat.drop_duplicates(["striker_id", "gender", "match_id", "innings"])
                   .groupby(["striker_id", "gender"]).size().to_dict())

    def _nest_phase(df, idcol):
        d = df.groupby([idcol, "gender", "phase"]).agg(
            runs=("rob", "sum"), balls=("lb", "sum"), bdry=("bdry", "sum"),
            dots=("dot", "sum"), outs=("out_self", "sum"))
        out = {}
        for (pid, gender, ph), row in d.iterrows():
            out.setdefault((pid, gender), {})[ph] = row.to_dict()
        return out
    bat_phase = _nest_phase(bat, "striker_id")

    def _vs_type(col_map, colname):
        bat[colname] = _lookup_by_name_gender(bat["bowler"], bat["gender"], col_map)
        v = bat.dropna(subset=[colname]).groupby(["striker_id", "gender", colname]).agg(
            runs=("rob", "sum"), balls=("lb", "sum"), bdry=("bdry", "sum"),
            dots=("dot", "sum"), outs=("out_self", "sum"))
        nested: dict = {}
        for (pid, gender, bk), row in v.iterrows():
            nested.setdefault((pid, gender), {})[bk] = row.to_dict()
        return nested

    bat_vs_type = _vs_type(bowl_bucket, "bowl_bucket")                 # coarse pace/spin
    bat_vs_type_detail = _vs_type(bowl_bucket_detail, "bowl_bucket_detail")  # off-spin/leg-spin/...

    legal = bat[bat["legal"]].sort_values(["match_id", "innings", "over", "ball_in_over"])
    legal["ball_no"] = legal.groupby(["match_id", "innings", "striker_id"]).cumcount() + 1
    legal["accel"] = (legal["ball_no"] > 10).map({False: "first10", True: "after10"})
    ac = legal.groupby(["striker_id", "gender", "accel"]).agg(
        runs=("rob", "sum"), balls=("ball_no", "count"))
    accel: dict = {}
    for (pid, gender, a), row in ac.iterrows():
        accel.setdefault((pid, gender), {})[a] = {"runs": int(row["runs"]), "balls": int(row["balls"])}

    bw = deliv.dropna(subset=["bowler_id"]).copy()
    bw["lbb"] = bw["legal_bowl"].astype(int)
    bw["dotb"] = (bw["legal_bowl"] & (bw["rc"] == 0)).astype(int)
    bw["wktb"] = bw["bwkt"].astype(int)
    bowl_overall = bw.groupby(["bowler_id", "gender"]).agg(
        balls=("lbb", "sum"), runs=("rc", "sum"), wkts=("wktb", "sum"),
        dots=("dotb", "sum")).to_dict("index")

    bp = bw.groupby(["bowler_id", "gender", "phase"]).agg(
        balls=("lbb", "sum"), runs=("rc", "sum"), wkts=("wktb", "sum"), dots=("dotb", "sum"))
    bowl_phase: dict = {}
    for (pid, gender, ph), row in bp.iterrows():
        bowl_phase.setdefault((pid, gender), {})[ph] = row.to_dict()

    bw["bat_hand"] = _lookup_by_name_gender(bw["striker"], bw["gender"], bat_hand)
    vh = bw.dropna(subset=["bat_hand"]).groupby(["bowler_id", "gender", "bat_hand"]).agg(
        balls=("lbb", "sum"), runs=("rc", "sum"), wkts=("wktb", "sum"))
    bowl_vs_hand: dict = {}
    for (pid, gender, h), row in vh.iterrows():
        bowl_vs_hand.setdefault((pid, gender), {})[h] = row.to_dict()

    archetype_th = _gender_archetype_thresholds(bat_overall, bat_phase)

    now = dt.datetime.now().isoformat(timespec="seconds")
    rows = []
    all_ids = set(bat_overall) | set(bowl_overall)
    for (ident, gender) in all_ids:
        pid = unambiguous.get(ident) or split.get((ident, gender))
        if not pid:
            continue
        key = (ident, gender)
        profile = {"format": fmt}
        archetype = None

        hand_raw, bstyle = _style_meta(ident, gender)
        profile["style"] = {
            "batting_hand": styles.classify_hand(hand_raw),
            "batting_hand_raw": hand_raw,
            "bowling_style": bstyle,
            "bowling_type": styles.classify_bowling_detail(bstyle),
        }

        bo = bat_overall.get(key)
        if bo and bo["balls"] > 0:
            profile["batting"] = _batting_block(bo, bat_innings.get(key, 0),
                                                bat_phase.get(key, {}),
                                                bat_vs_type.get(key, {}),
                                                accel.get(key, {}),
                                                bat_vs_type_detail.get(key, {}),
                                                thresholds=archetype_th.get(gender, {}))
            archetype = profile["batting"]["archetype"]

        bwo = bowl_overall.get(key)
        if bwo and bwo["balls"] > 0:
            profile["bowling"] = _bowling_block(bwo, bowl_phase.get(key, {}),
                                                bowl_vs_hand.get(key, {}))

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


def _vs_type_block(vs: dict) -> dict:
    return {
        t: {"balls": int(v["balls"]), "runs": int(v["runs"]),
            "strike_rate": _bat_rate(v["runs"], v["balls"]),
            "boundary_pct": round(100 * v["bdry"] / v["balls"], 1) if v["balls"] else None,
            "dot_pct": round(100 * v["dots"] / v["balls"], 1) if v["balls"] else None,
            "dismissals": int(v["outs"]),
            "average": round(v["runs"] / v["outs"], 1) if v["outs"] else None}
        for t, v in vs.items()}


# minimum balls faced before a batter's stats count toward the per-gender
# archetype thresholds below, so a one-off cameo can't skew the percentile bars.
_ARCHETYPE_MIN_BALLS = 120

# minimum balls faced before an individual earns a specialist role label at
# all; below this a batter is just "balanced". lower than the percentile-bar
# minimum above since this is about describing one player, not a population.
_ARCHETYPE_MIN_CLASSIFY_BALLS = 60
_ARCHETYPE_MIN_DEATH_BALLS = 40  # death sample a finisher needs, matching the death-SR percentile gate


def _gender_archetype_thresholds(bat_overall: dict, bat_phase: dict) -> dict:
    """per-gender percentile bars for the archetype classifier. men's and
    women's T20 six-hitting/strike-rate distributions differ enough that a
    shared threshold would label most men "power hitters" and almost no
    women, so each gender gets its own population percentiles.
    """
    import numpy as np
    per_gender: dict = {}
    for (pid, gender), bo in bat_overall.items():
        balls = bo["balls"] or 0
        if balls < _ARCHETYPE_MIN_BALLS:
            continue
        d = per_gender.setdefault(gender, {"six_rate": [], "sr": [], "bdry": [],
                                            "rotation": [], "death_sr": []})
        d["six_rate"].append(100 * bo["sixes"] / balls)
        d["sr"].append(100 * bo["runs"] / balls)
        d["bdry"].append(100 * bo["bdry"] / balls)
        d["rotation"].append(100 * bo["rotate"] / balls)
        death = bat_phase.get((pid, gender), {}).get("death")
        if death and death.get("balls", 0) >= 40:
            d["death_sr"].append(100 * death["runs"] / death["balls"])

    out: dict = {}
    for gender, d in per_gender.items():
        def p(key, q, default):
            return float(np.percentile(d[key], q)) if d[key] else default
        out[gender] = {
            "six_rate_high": p("six_rate", 75, 1.0),    # clears the rope well above the gender norm
            "sr_high": p("sr", 75, 120.0),
            "sr_low": p("sr", 50, 100.0),               # "not aggressive" bar for anchor
            "boundary_high": p("bdry", 75, 12.0),
            "rotation_high": p("rotation", 75, 45.0),
            "death_sr_high": p("death_sr", 75, 130.0),  # genuinely destructive at the death
        }
    return out


def _batting_block(bo, innings, phase, vs_type, accel, vs_type_detail=None, thresholds=None) -> dict:
    balls = bo["balls"]
    block = {
        "innings": int(innings), "runs": int(bo["runs"]), "balls": int(balls),
        "strike_rate": _bat_rate(bo["runs"], balls),
        "average": round(bo["runs"] / bo["outs"], 1) if bo["outs"] else None,
        "boundary_pct": round(100 * bo["bdry"] / balls, 1) if balls else None,
        "dot_pct": round(100 * bo["dots"] / balls, 1) if balls else None,
        "scoring_pct": round(100 * (balls - bo["dots"]) / balls, 1) if balls else None,
        "rotation_pct": round(100 * bo["rotate"] / balls, 1) if balls else None,
        # sixes per 100 balls: a scale-stable "power" signal, unlike a raw
        # six count which just tracks career length.
        "six_rate": round(100 * bo["sixes"] / balls, 2) if balls else None,
        "fours": int(bo["fours"]), "sixes": int(bo["sixes"]),
        "by_phase": {ph: _phase_block(phase[ph]) for ph in phase},
    }
    if vs_type:
        block["vs_bowling_type"] = _vs_type_block(vs_type)
    if vs_type_detail:
        block["vs_bowling_type_detail"] = _vs_type_block(vs_type_detail)
    if accel:
        block["acceleration"] = {
            k: {"balls": v["balls"], "strike_rate": _bat_rate(v["runs"], v["balls"])}
            for k, v in accel.items()}
    block["archetype"] = _archetype(block, thresholds or {})
    return block


def _archetype(b: dict, th: dict) -> str:
    """descriptive batting role, classified against this batter's own
    gender's population bars (`th`):

      * finisher: bats a real share of death overs and is genuinely
        destructive there (SR and boundary% both above the gender's bar).
      * power hitter: six rate at/above the gender p75 with a high overall
        strike rate.
      * anchor: bats up top, rotates strike hard, but below-median SR.
      * balanced: none of the above stands out.

    finisher takes precedence over power hitter.
    """
    total = b["balls"] or 0
    if total < _ARCHETYPE_MIN_CLASSIFY_BALLS:
        return "balanced"  # too small a sample to earn a specialist role label

    by = b.get("by_phase", {})
    sr = b.get("strike_rate") or 0
    bdry = b.get("boundary_pct") or 0
    six_rate = b.get("six_rate") or 0
    rotation = b.get("rotation_pct") or 0
    death = by.get("death", {})
    death_balls = death.get("balls", 0)
    death_share = death_balls / total
    death_sr = death.get("strike_rate") or 0
    death_bdry = death.get("boundary_pct") or 0
    pp_share = by.get("powerplay", {}).get("balls", 0) / total

    six_hi = th.get("six_rate_high", 2.0)
    sr_hi = th.get("sr_high", 120.0)
    sr_lo = th.get("sr_low", 100.0)
    bdry_hi = th.get("boundary_high", 12.0)
    rot_hi = th.get("rotation_high", 45.0)
    death_sr_hi = th.get("death_sr_high", 130.0)

    if (death_balls >= _ARCHETYPE_MIN_DEATH_BALLS and death_share >= 0.25
            and death_sr >= death_sr_hi and death_bdry >= bdry_hi):
        return "finisher"
    if six_rate >= six_hi and sr >= sr_hi:
        return "power hitter"
    if pp_share >= 0.40 and sr <= sr_lo and rotation >= rot_hi:
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
            h: {"balls": int(v["balls"]),
                "economy": round(6 * v["runs"] / v["balls"], 2) if v["balls"] else None,
                "wickets": int(v["wkts"]),
                "strike_rate": round(v["balls"] / v["wkts"], 1) if v["wkts"] else None,
                "average": round(v["runs"] / v["wkts"], 1) if v["wkts"] else None}
            for h, v in vs_hand.items()}
    return block


def _strengths_summary(profile: dict) -> list[str]:
    out: list[str] = []
    st = profile.get("style", {})
    b = profile.get("batting")
    if b:
        if st.get("batting_hand"):
            out.append(f"{st['batting_hand']} batter")
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
        # weakest specific bowling type (enough sample), for targeted matchups
        vtd = {t: v for t, v in b.get("vs_bowling_type_detail", {}).items()
               if v["balls"] >= MIN_PHASE_BALLS and v["strike_rate"] is not None}
        if len(vtd) >= 2:
            weakest = min(vtd, key=lambda t: vtd[t]["strike_rate"])
            out.append(f"Least effective vs {weakest} (SR {vtd[weakest]['strike_rate']}, "
                       f"{vtd[weakest]['dismissals']} dismissals) — a matchup to exploit")
    bw = profile.get("bowling")
    if bw:
        if st.get("bowling_type"):
            out.append(f"Bowling type: {st['bowling_type']}")
        vh = bw.get("vs_batting_hand", {})
        if "RHB" in vh and "LHB" in vh and vh["RHB"]["economy"] and vh["LHB"]["economy"]:
            if vh["RHB"]["economy"] < vh["LHB"]["economy"] * 0.9:
                out.append(f"Tighter to RHB ({vh['RHB']['economy']} vs {vh['LHB']['economy']} RPO to LHB)")
            elif vh["LHB"]["economy"] < vh["RHB"]["economy"] * 0.9:
                out.append(f"Tighter to LHB ({vh['LHB']['economy']} vs {vh['RHB']['economy']} RPO to RHB)")
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

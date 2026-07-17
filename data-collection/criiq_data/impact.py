from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from .config import enabled_sources
from .db import set_meta
from .h2h import BOWLER_WICKETS
from .identity import player_id_map
from .logging_utils import get_logger
from .opponents import potm_match_to_ident
from .stats import build_innings

log = get_logger("impact")

TOP_ORDER = 4


def _wicket_events(deliv: pd.DataFrame, name2id: dict) -> pd.DataFrame:
    d = deliv.sort_values(["match_id", "innings", "over", "ball_in_over"]).reset_index(drop=True)
    d["cum"] = d.groupby(["match_id", "innings"])["runs_total"].cumsum()

    order = d.index.to_series()
    long = pd.concat([
        pd.DataFrame({"match_id": d["match_id"], "innings": d["innings"],
                      "batter": d["striker"], "o": order}),
        pd.DataFrame({"match_id": d["match_id"], "innings": d["innings"],
                      "batter": d["non_striker"], "o": order}),
    ])
    first = long.groupby(["match_id", "innings", "batter"], as_index=False)["o"].min()
    first["position"] = first.groupby(["match_id", "innings"])["o"].rank("first").astype(int)

    wk = d[d["player_dismissed"].notna()].copy()
    wk["prev_cum"] = wk.groupby(["match_id", "innings"])["cum"].shift(1).fillna(0)
    wk["partnership_broken"] = wk["cum"] - wk["prev_cum"]
    wk["credited"] = wk["wicket_type"].isin(BOWLER_WICKETS)
    wk = wk.merge(first[["match_id", "innings", "batter", "position"]],
                  left_on=["match_id", "innings", "player_dismissed"],
                  right_on=["match_id", "innings", "batter"], how="left")
    # identifier, NOT player_id, despite the name -- gender is threaded
    # alongside it (deliv already carries `gender`) so the final grouping
    # below can disambiguate the handful of Cricsheet registry identifiers
    # reused across two genuinely different people of different genders.
    wk["bowler_id"] = wk["bowler"].map(name2id)
    return wk[wk["credited"] & wk["bowler_id"].notna()]


def build_impact_for_format(conn, fmt: str) -> int:
    inn = build_innings(conn, fmt)
    if inn.empty:
        log.info("impact %s: no innings", fmt)
        return 0

    deliv = pd.read_sql_query(
        "SELECT d.match_id, d.innings, d.over, d.ball_in_over, d.batting_team, "
        "d.bowling_team, d.striker, d.non_striker, d.bowler, d.runs_off_bat, "
        "d.wides, d.runs_total, d.wicket_type, d.player_dismissed, m.gender "
        "FROM deliveries d JOIN matches m ON d.match_id=m.match_id "
        "WHERE m.format=? AND m.team_type='international'",
        conn, params=(fmt,))
    name2id = {r["player_name"]: r["identifier"]
               for r in conn.execute("SELECT player_name, identifier FROM identifier_map")}
    meta = {}
    for r in conn.execute("SELECT cricsheet_identifier, gender, canonical_name FROM players"):
        meta[(r["cricsheet_identifier"], r["gender"])] = dict(r)
    unambiguous, split = player_id_map(conn)
    potm = potm_match_to_ident(conn, fmt)

    team_runs = deliv.groupby(["match_id", "batting_team"])["runs_total"].sum()
    team_runs = {(m, t): v for (m, t), v in team_runs.items()}
    tw = deliv[deliv["player_dismissed"].notna()].groupby(["match_id", "bowling_team"]).size()
    team_wkts = {(m, t): v for (m, t), v in tw.items()}

    inn = inn.copy()
    inn["team_runs"] = [team_runs.get((m, t), 0) for m, t in zip(inn["match_id"], inn["team"])]
    inn["team_wkts"] = [team_wkts.get((m, t), 0) for m, t in zip(inn["match_id"], inn["team"])]
    inn["bat_contrib"] = inn.apply(
        lambda r: r["runs"] / r["team_runs"] if r["balls_faced"] > 0 and r["team_runs"] else None, axis=1)
    inn["bowl_contrib"] = inn.apply(
        lambda r: r["wickets"] / r["team_wkts"] if r["balls_bowled"] > 0 and r["team_wkts"] else None, axis=1)
    inn["potm"] = [potm.get(m) == i for m, i in zip(inn["match_id"], inn["identifier"])]

    deliv["legal"] = (deliv["wides"].fillna(0) == 0).astype(int)
    deliv["striker_id"] = deliv["striker"].map(name2id)
    sit = deliv[deliv["innings"].isin([1, 2]) & deliv["striker_id"].notna()]
    # gender kept alongside the identifier in every group key below, for the
    # same reason as career.py/ml_features.py -- see identity.py.
    sit_runs = sit.groupby(["striker_id", "gender", "innings"]).agg(
        runs=("runs_off_bat", "sum"), balls=("legal", "sum"))
    outs = (deliv[deliv["player_dismissed"].notna()].assign(
        did=lambda x: x["player_dismissed"].map(name2id))
        .dropna(subset=["did"]).groupby(["did", "gender", "innings"]).size())

    wk = _wicket_events(deliv, name2id)
    bowl_impact = wk.groupby(["bowler_id", "gender"]).agg(
        wkts=("credited", "size"),
        avg_pp=("partnership_broken", "mean"),
        top_order=("position", lambda s: int((s <= TOP_ORDER).sum())))

    now = dt.datetime.now().isoformat(timespec="seconds")
    rows = []
    for (ident, gender), g in inn.groupby(["identifier", "gender"]):
        pid = unambiguous.get(ident) or split.get((ident, gender))
        # unsplit (non-colliding) players are stored with gender=NULL.
        pm = meta.get((ident, gender)) or meta.get((ident, None))
        if not pid or not pm:
            continue
        matches = int(g["match_id"].nunique())
        batted = g[g["balls_faced"] > 0]
        bowled = g[g["balls_bowled"] > 0]

        bat_contrib = round(100 * batted["bat_contrib"].dropna().mean(), 1) if len(batted) else None
        bowl_contrib = round(100 * bowled["bowl_contrib"].dropna().mean(), 1) if len(bowled) else None
        win_pct = round(100 * g["won"].mean(), 1)
        runs_wins = batted[batted["won"] == 1]["runs"]
        runs_loss = batted[batted["won"] == 0]["runs"]
        potm_awards = int(g["potm"].sum())
        mwp = int((g["potm"] & (g["won"] == 1)).sum())

        bi_key = (ident, gender)
        bi = bowl_impact.loc[bi_key] if bi_key in bowl_impact.index else None
        avg_pp = round(float(bi["avg_pp"]), 1) if bi is not None else None
        top_scalps = int(bi["top_order"]) if bi is not None else 0
        total_wk = int(bi["wkts"]) if bi is not None else 0
        top_pct = round(100 * top_scalps / total_wk, 1) if total_wk else None

        # An "economical spell worth having" -- >=12 legal balls (2 overs, so
        # a single tidy over doesn't count) at economy<=6.0/over. Threshold
        # picked from the real distribution (`bowled` innings DB-wide,
        # balls_bowled>=12): rate of qualifying innings per match has
        # mean 0.402/median 0.389/75th-pctile 0.538 at this exact cutoff --
        # its 75th-percentile (0.538) lines up almost exactly with
        # top_order_scalps/matches's own 75th-percentile (0.538), so the two
        # bonuses hit their (now-equal, see below) caps at a comparably-rare
        # percentile of real bowlers, the same calibration discipline used
        # for `big_innings` below.
        spells = bowled[bowled["balls_bowled"] >= 12]
        economical_spells = int((spells["runs_conceded"] / spells["balls_bowled"] * 6 <= 6.0).sum())

        def _sit(innum):
            key = (ident, gender, innum)
            if key not in sit_runs.index:
                return None, None
            r = sit_runs.loc[key]
            o = int(outs.get(key, 0))
            sr = round(100 * r["runs"] / r["balls"], 1) if r["balls"] else None
            avg = round(r["runs"] / o, 1) if o else None
            return sr, avg
        set_sr, set_avg = _sit(1)
        chase_sr, chase_avg = _sit(2)

        # "A wicket worth having" (top_order_scalps, credited toward dangerous
        # top-order batters) needs a batting-side equivalent: "an innings worth
        # having". >=30 runs was picked, not guessed -- checked against the live
        # DB, (innings>=30)/matches has mean 0.135/median 0.100/75th-pctile 0.222,
        # and a multiplier of 70 lines its mean and 75th-percentile up with
        # top_order_scalps/matches's own mean 0.313/75th-pctile 0.538 under the
        # existing *30 multiplier -- both bonuses hit their 15.0 cap at a
        # comparably-rare percentile of real players, not an arbitrary round
        # number on one side only.
        big_innings = int((batted["runs"] >= 30).sum())

        overall_contrib = (bat_contrib or 0) + (bowl_contrib or 0)
        contribution_part = min(35.0, overall_contrib * 0.9)
        winning_part = 25.0 * (win_pct or 0) / 100
        standout_part = 25.0 * min(1.0, (potm_awards / matches) / 0.12) if matches else 0
        # Wicket-taking and economy now split the same 15pt bowling bonus
        # equally (7.5 each) rather than economy counting for nothing --
        # previously a bowler's *entire* bowling bonus came from top-order
        # wicket-taking rate alone, so two bowlers with identical wicket-rates
        # scored identically here even if one leaked boundaries every over and
        # the other built pressure with dot balls. Both halves use the same
        # halved multiplier (*15, not *30) so each still hits its own 7.5 cap
        # at the same rate-percentile the original *30/cap-15 bowling bonus
        # did -- the total 15pt ceiling for a bowler who's genuinely elite at
        # *both* is unchanged from before this split, it's just no longer
        # 100% wicket-driven.
        wicket_rate_part = min(7.5, (top_scalps / matches) * 15) if matches else 0
        economy_part = min(7.5, (economical_spells / matches) * 15) if matches else 0
        bowling_part = wicket_rate_part + economy_part
        batting_impact_part = min(15.0, (big_innings / matches) * 70) if matches else 0
        # A genuine dual-threat all-rounder can now earn both 15pt bonuses at
        # once (impossible before this fix) -- clamp the total back to the
        # intended 0-100 scale; pure specialists are unaffected, they only ever
        # earn one of the two bonuses so their ceiling was already <=100.
        importance = round(min(100.0, contribution_part + winning_part + standout_part
                                + bowling_part + batting_impact_part), 1)
        components = {
            "contribution_part": round(contribution_part, 1),
            "winning_part": round(winning_part, 1),
            "standout_part": round(standout_part, 1),
            "bowling_impact_part": round(bowling_part, 1),
            "wicket_rate_part": round(wicket_rate_part, 1),
            "economy_part": round(economy_part, 1),
            "batting_impact_part": round(batting_impact_part, 1),
            "inputs": {"bat_contribution_pct": bat_contrib, "bowl_contribution_pct": bowl_contrib,
                       "win_pct": win_pct, "potm_rate": round(potm_awards / matches, 3) if matches else None,
                       "top_order_scalps_per_match": round(top_scalps / matches, 3) if matches else None,
                       "economical_spells_per_match": round(economical_spells / matches, 3) if matches else None,
                       "big_innings_per_match": round(big_innings / matches, 3) if matches else None},
        }

        rows.append((
            pid, fmt, matches, bat_contrib, bowl_contrib, win_pct,
            round(runs_wins.mean(), 1) if len(runs_wins) else None,
            round(runs_loss.mean(), 1) if len(runs_loss) else None,
            potm_awards, round(potm_awards / matches, 3) if matches else None, mwp,
            avg_pp, top_scalps, top_pct,
            set_sr, chase_sr, set_avg, chase_avg,
            importance, json.dumps(components), now,
        ))

    conn.executemany(
        "INSERT INTO player_impact(player_id, format, matches, bat_contribution_pct, "
        "bowl_contribution_pct, win_pct, avg_runs_in_wins, avg_runs_in_losses, "
        "player_of_match, potm_rate, match_winning_perfs, avg_partnership_broken, "
        "top_order_scalps, top_order_scalp_pct, setting_strike_rate, chasing_strike_rate, "
        "setting_average, chasing_average, importance_score, importance_components, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id, format) DO UPDATE SET "
        "matches=excluded.matches, bat_contribution_pct=excluded.bat_contribution_pct, "
        "bowl_contribution_pct=excluded.bowl_contribution_pct, win_pct=excluded.win_pct, "
        "avg_runs_in_wins=excluded.avg_runs_in_wins, avg_runs_in_losses=excluded.avg_runs_in_losses, "
        "player_of_match=excluded.player_of_match, potm_rate=excluded.potm_rate, "
        "match_winning_perfs=excluded.match_winning_perfs, "
        "avg_partnership_broken=excluded.avg_partnership_broken, "
        "top_order_scalps=excluded.top_order_scalps, top_order_scalp_pct=excluded.top_order_scalp_pct, "
        "setting_strike_rate=excluded.setting_strike_rate, chasing_strike_rate=excluded.chasing_strike_rate, "
        "setting_average=excluded.setting_average, chasing_average=excluded.chasing_average, "
        "importance_score=excluded.importance_score, importance_components=excluded.importance_components, "
        "updated_at=excluded.updated_at", rows)
    conn.commit()
    log.info("impact %s: %d player impact records", fmt, len(rows))
    return len(rows)


def build_impact(conn) -> dict:
    out = {}
    for fmt in sorted({s.fmt for s in enabled_sources()}):
        out[fmt] = build_impact_for_format(conn, fmt)
    set_meta(conn, "impact_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out


def get_impact(conn, player_id: str, fmt: str) -> dict | None:
    row = conn.execute("SELECT * FROM player_impact WHERE player_id=? AND format=?",
                       (player_id, fmt)).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("importance_components"):
        d["importance_components"] = json.loads(d["importance_components"])
    return d

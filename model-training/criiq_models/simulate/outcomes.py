"""ball-outcome probability model.

phase-level (powerplay/middle/death) empirical frequencies per gender,
adjusted per-ball for the batter/bowler's own record and any head-to-head
history, shrunk toward the phase prior so a small sample can't swing it.

simplification: each delivery gets exactly one outcome bucket, so a wicket
never coincides with a wide/no-ball here. other wide/no-ball consequences
are modelled downstream in engine.py.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import SETTINGS
from ..features.common import shrink
from ..features.current import build_model_features

PHASES = ("powerplay", "middle", "death")
OUTCOMES = ("0", "1", "2", "3", "4", "6", "wicket", "wide", "noball", "bye")

# fallback league-wide numbers when no historical rows exist (e.g. a tiny
# synthetic test DB), never used when real data is available
_DEFAULT_LEAGUE_SR = 120.0
_DEFAULT_LEAGUE_ECONOMY = 7.5


def _phase(over: int) -> str:
    if over <= 5:
        return "powerplay"
    if over <= 14:
        return "middle"
    return "death"


def _classify_row(runs_off_bat, extras, wides, noballs, wicket_type) -> str:
    # wicket_type comes back as nan (not None) for a missing SQL NULL via
    # pandas, and nan is truthy, so pd.notna() is required here instead of
    # a plain `if wicket_type:` check
    if pd.notna(wides) and wides > 0:
        return "wide"
    if pd.notna(noballs) and noballs > 0:
        return "noball"
    if pd.notna(wicket_type) and wicket_type:
        return "wicket"
    runs = int(runs_off_bat or 0)
    if runs == 0 and pd.notna(extras) and extras > 0:
        return "bye"
    # rare running-run values (5, 7 from overthrows) get folded into the
    # nearest common bucket instead of their own category
    return str(runs) if runs in (0, 1, 2, 3, 4, 6) else "1"


def build_phase_baseline_rates(conn: sqlite3.Connection, fmt: str, gender: str) -> dict:
    """empirical per-phase outcome frequencies from real ball-by-ball data,
    scoped to (format, gender), never blended across genders.
    """
    df = pd.read_sql_query(
        "SELECT d.over AS over, d.runs_off_bat AS runs_off_bat, d.extras AS extras, "
        "d.wides AS wides, d.noballs AS noballs, d.wicket_type AS wicket_type "
        "FROM deliveries d JOIN matches m ON d.match_id = m.match_id "
        "WHERE m.format=? AND m.gender=?", conn, params=(fmt, gender))
    if df.empty:
        raise ValueError(f"no deliveries found for format={fmt} gender={gender} -- "
                          f"run data-collection's ingestion pipeline first")
    df["phase"] = df["over"].fillna(0).astype(int).apply(_phase)
    df["outcome"] = df.apply(
        lambda r: _classify_row(r["runs_off_bat"], r["extras"], r["wides"], r["noballs"], r["wicket_type"]),
        axis=1)

    overall_counts = df["outcome"].value_counts()
    overall_total = overall_counts.sum()
    overall = {o: overall_counts.get(o, 0) / overall_total for o in OUTCOMES}

    out = {}
    for phase, g in df.groupby("phase"):
        counts = g["outcome"].value_counts()
        total = counts.sum()
        out[phase] = {o: counts.get(o, 0) / total for o in OUTCOMES}
    for phase in PHASES:
        out.setdefault(phase, overall)
    return out


# a naive all-time average understates the modern game since it's dominated
# by brief cameos and older, slower-scoring eras. restricting to recent
# (2yr), settled innings (>=15 balls faced) gives a more realistic league
# average. same recency + minimum-sample logic applies to economy (>=18
# balls bowled).
_LEAGUE_RECENT_YEARS = 2
_LEAGUE_MIN_BALLS_FACED = 15
_LEAGUE_MIN_BALLS_BOWLED = 18


def league_averages(conn: sqlite3.Connection, fmt: str, gender: str) -> dict:
    row = conn.execute(
        "SELECT AVG(pmi.bat_strike_rate) AS sr FROM player_match_impact pmi "
        "JOIN matches m ON pmi.match_id = m.match_id "
        "WHERE pmi.format=? AND m.gender=? AND pmi.balls_faced >= ? "
        "AND pmi.date >= date('now', ?)",
        (fmt, gender, _LEAGUE_MIN_BALLS_FACED, f"-{_LEAGUE_RECENT_YEARS} years")).fetchone()
    econ_row = conn.execute(
        "SELECT AVG(pmi.economy) AS econ FROM player_match_impact pmi "
        "JOIN matches m ON pmi.match_id = m.match_id "
        "WHERE pmi.format=? AND m.gender=? AND pmi.balls_bowled >= ? "
        "AND pmi.date >= date('now', ?)",
        (fmt, gender, _LEAGUE_MIN_BALLS_BOWLED, f"-{_LEAGUE_RECENT_YEARS} years")).fetchone()

    sr = row["sr"] if row and row["sr"] is not None else _DEFAULT_LEAGUE_SR
    econ = econ_row["econ"] if econ_row and econ_row["econ"] is not None else _DEFAULT_LEAGUE_ECONOMY
    return {"sr": float(sr), "economy": float(econ)}


@dataclass
class BatterProfile:
    strike_rate: float | None = None
    # venue-conditioned strike rate, shrunk toward `strike_rate` by matches
    # played there. None unless a venue was supplied with recorded history.
    # engine picks setting (1st innings) vs chasing (2nd) by innings in
    # progress.
    setting_strike_rate: float | None = None
    chasing_strike_rate: float | None = None


@dataclass
class BowlerProfile:
    economy: float | None = None
    wickets_per_match: float | None = None
    # per-phase economy rank within their own team (rank 1 = most economical),
    # used by engine.select_bowler to pick a realistic bowling rotation.
    # None per phase with no qualifying sample.
    phase_rank: dict = field(default_factory=dict)


def _venue_strike_rates(conn: sqlite3.Connection, player_id: str, fmt: str,
                         venue_id: str | None, base_sr: float | None) -> tuple:
    if not venue_id:
        return None, None
    row = conn.execute(
        "SELECT matches, setting_strike_rate, chasing_strike_rate FROM player_by_venue "
        "WHERE player_id=? AND format=? AND venue_id=?", (player_id, fmt, venue_id)).fetchone()
    if not row:
        return None, None
    n = row["matches"] or 0
    setting = shrink(row["setting_strike_rate"], n, base_sr, prior_strength=SETTINGS.shrinkage_prior_matches)
    chasing = shrink(row["chasing_strike_rate"], n, base_sr, prior_strength=SETTINGS.shrinkage_prior_matches)
    return (None if setting is None or pd.isna(setting) else float(setting),
            None if chasing is None or pd.isna(chasing) else float(chasing))


def build_batter_profile(conn: sqlite3.Connection, player_id: str, fmt: str,
                          opponent: str = "", venue_id: str | None = None) -> BatterProfile:
    feats = build_model_features(conn, player_id, opponent=opponent, venue_id=venue_id, fmt=fmt)
    sr = feats.get("form_bat_sr")
    if sr is None or pd.isna(sr):
        sr = feats.get("career_bat_sr")
    base_sr = None if sr is None or pd.isna(sr) else float(sr)
    setting_sr, chasing_sr = _venue_strike_rates(conn, player_id, fmt, venue_id, base_sr)
    return BatterProfile(strike_rate=base_sr, setting_strike_rate=setting_sr, chasing_strike_rate=chasing_sr)


def _phase_ranks(conn: sqlite3.Connection, player_id: str, fmt: str) -> dict:
    rows = conn.execute(
        "SELECT phase, bowl_team_rank FROM player_phase WHERE player_id=? AND format=?",
        (player_id, fmt)).fetchall()
    return {r["phase"]: r["bowl_team_rank"] for r in rows if r["bowl_team_rank"] is not None}


def build_bowler_profile(conn: sqlite3.Connection, player_id: str, fmt: str, opponent: str = "") -> BowlerProfile:
    feats = build_model_features(conn, player_id, opponent=opponent, venue_id=None, fmt=fmt)
    econ = feats.get("form_bowl_economy")
    if econ is None or pd.isna(econ):
        econ = feats.get("career_bowl_economy")
    wpm = feats.get("form_bowl_wickets_per_match")
    if wpm is None or pd.isna(wpm):
        wpm = feats.get("career_bowl_wickets_per_match")
    return BowlerProfile(
        economy=None if econ is None or pd.isna(econ) else float(econ),
        wickets_per_match=None if wpm is None or pd.isna(wpm) else float(wpm),
        phase_rank=_phase_ranks(conn, player_id, fmt))


def build_player_profiles(conn: sqlite3.Connection, fmt: str, team1_ids: list, team2_ids: list,
                           team1_name: str = "", team2_name: str = "", venue_id: str | None = None) -> tuple:
    """one (batter_profiles, bowler_profiles) pair keyed by player_id, every
    player gets both since a bowler still needs a batting profile as a
    tailender and vice versa.

    each side is scored with the other side as `opponent` and the shared
    `venue_id`, both threaded through from the CLI's `--venue`.
    """
    batter_profiles, bowler_profiles = {}, {}
    for pid in team1_ids:
        batter_profiles[pid] = build_batter_profile(conn, pid, fmt, opponent=team2_name, venue_id=venue_id)
        bowler_profiles[pid] = build_bowler_profile(conn, pid, fmt, opponent=team2_name)
    for pid in team2_ids:
        batter_profiles[pid] = build_batter_profile(conn, pid, fmt, opponent=team1_name, venue_id=venue_id)
        bowler_profiles[pid] = build_bowler_profile(conn, pid, fmt, opponent=team1_name)
    return batter_profiles, bowler_profiles


def load_matchup_lookup(conn: sqlite3.Connection, fmt: str, ids_a: list, ids_b: list) -> dict:
    """`{(batter_id, bowler_id): {"balls","runs","dismissals"}}` for every
    real recorded pairing between the two rosters, from `dismissal_matchup`.
    """
    all_ids = list(dict.fromkeys(list(ids_a) + list(ids_b)))
    if not all_ids:
        return {}
    ph = ",".join("?" * len(all_ids))
    rows = conn.execute(
        f"SELECT batter_id, bowler_id, balls, runs, dismissals FROM dismissal_matchup "
        f"WHERE format=? AND batter_id IN ({ph}) AND bowler_id IN ({ph})",
        (fmt, *all_ids, *all_ids)).fetchall()
    return {(r["batter_id"], r["bowler_id"]): {"balls": r["balls"], "runs": r["runs"],
                                                "dismissals": r["dismissals"]} for r in rows}


class PlayerAdjustedOutcomeModel:
    """per-ball categorical outcome distribution: phase baseline scaled by
    the batter's strike rate and bowler's economy (boundary probability),
    plus the bowler's wicket rate and head-to-head history (wicket
    probability), shrunk toward the phase prior so small samples don't
    swing it.
    """

    def __init__(self, phase_baseline: dict, league_sr: float, league_economy: float,
                 matchup_lookup: dict | None = None):
        self.phase_baseline = phase_baseline
        self.league_sr = league_sr or _DEFAULT_LEAGUE_SR
        self.league_economy = league_economy or _DEFAULT_LEAGUE_ECONOMY
        self.matchup_lookup = matchup_lookup or {}

    def distribution(self, phase: str, batter: BatterProfile, bowler: BowlerProfile,
                      batter_id: str | None = None, bowler_id: str | None = None,
                      free_hit: bool = False, innings: int | None = None) -> dict:
        base = dict(self.phase_baseline[phase])

        # venue-conditioned strike rate, picked by which innings is in
        # progress. falls back to overall strike rate with no venue history.
        effective_sr = batter.strike_rate
        if innings == 1 and batter.setting_strike_rate is not None:
            effective_sr = batter.setting_strike_rate
        elif innings == 2 and batter.chasing_strike_rate is not None:
            effective_sr = batter.chasing_strike_rate

        sr_factor = (effective_sr or self.league_sr) / self.league_sr
        econ_factor = (bowler.economy or self.league_economy) / self.league_economy
        # a faster batter facing a pricier bowler pushes boundary probability
        # up, clipped to a plausible range so extremes can't blow it up
        boundary_scale = float(np.clip(sr_factor / max(econ_factor, 0.3), 0.4, 2.5))
        base["4"] = base["4"] * boundary_scale
        base["6"] = base["6"] * boundary_scale

        wkt_factor = 1.0
        if bowler.wickets_per_match:
            wkt_factor *= float(np.clip(bowler.wickets_per_match / 1.0, 0.3, 2.5))
        pairing = self.matchup_lookup.get((batter_id, bowler_id))
        if pairing and (pairing.get("balls") or 0) >= 6 and base["wicket"] > 0:
            balls = pairing["balls"]
            observed_rate = pairing["dismissals"] / balls
            shrunk_rate = shrink(observed_rate, balls, base["wicket"],
                                  prior_strength=SETTINGS.shrinkage_prior_matches)
            wkt_factor *= float(np.clip(shrunk_rate / base["wicket"], 0.2, 4.0))
        base["wicket"] = base["wicket"] * wkt_factor

        if free_hit:
            # only run out/obstructing the field/hit twice can dismiss on a
            # free hit, none of which this model buckets as "wicket", so
            # suppress wicket probability for that ball
            base["wicket"] = 0.0

        # wide/no-ball rates stay fixed at the phase-empirical rate since
        # sr/economy shouldn't affect discipline; everything else rescales
        # to fill the remaining probability mass
        fixed = base["wide"] + base["noball"]
        remaining_keys = [k for k in OUTCOMES if k not in ("wide", "noball")]
        remaining_total = sum(base[k] for k in remaining_keys)
        target_remaining = max(1e-6, 1.0 - fixed)
        if remaining_total > 0:
            scale = target_remaining / remaining_total
            for k in remaining_keys:
                base[k] = base[k] * scale

        total = sum(base.values())
        if total <= 0:
            # only reachable if the baseline had zero mass outside "wicket"
            # and a free hit just zeroed that too; fall back to a dot ball
            base["0"] = 1.0
            total = 1.0
        return {k: v / total for k, v in base.items()}

    def sample(self, phase: str, batter: BatterProfile, bowler: BowlerProfile,
               rng: np.random.Generator, batter_id: str | None = None,
               bowler_id: str | None = None, free_hit: bool = False,
               innings: int | None = None) -> str:
        dist = self.distribution(phase, batter, bowler, batter_id, bowler_id, free_hit, innings)
        keys = list(dist.keys())
        probs = np.array([dist[k] for k in keys], dtype=float)
        probs = probs / probs.sum()
        return str(rng.choice(keys, p=probs))


def build_outcome_model(conn: sqlite3.Connection, fmt: str, gender: str,
                         team1_ids: list, team2_ids: list) -> PlayerAdjustedOutcomeModel:
    baseline = build_phase_baseline_rates(conn, fmt, gender)
    league = league_averages(conn, fmt, gender)
    matchup_lookup = load_matchup_lookup(conn, fmt, team1_ids, team2_ids)
    return PlayerAdjustedOutcomeModel(baseline, league["sr"], league["economy"], matchup_lookup)

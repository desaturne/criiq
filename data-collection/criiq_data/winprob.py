"""Ball-by-ball win probability across all phases of a T20 game.

Win probability is P(the batting team wins | the game state at this ball). It is
computed at every legal ball, so plotting it down an innings gives a curve that
spans powerplay -> middle -> death for both innings.

This module ships an *empirical* estimator: it bins historical ball-states and
takes the actual win frequency, shrunk toward the innings prior so sparse buckets
stay stable. Setting (innings 1) and chasing (innings 2) are fundamentally
different problems (the target is known only in the chase), so they get separate
grids. The estimator implements a small ``fit`` / ``predict`` interface, so a
calibrated scikit-learn model can be dropped in behind the same surface later
without touching the build/CLI code.

Training data is ``data/features/ball_state_<fmt>.parquet`` (built by
``ml_features``); the fitted grids and a per-ball win-probability parquet are
written under ``data/models`` and ``data/features``.
"""
from __future__ import annotations

import datetime as dt
import json
import zlib

import numpy as np
import pandas as pd

from .config import FEATURES_DIR, MODELS_DIR, SETTINGS, enabled_sources
from .db import set_meta
from .logging_utils import get_logger

log = get_logger("winprob")

# Bin widths for the empirical grid. Coarse enough to stay well-populated with
# shrinkage; the scikit-learn upgrade is what buys smooth, fine-grained curves.
_BALLS_BIN = 6      # one over
_RR_BIN = 5         # runs-required band (chase)
_SCORE_BIN = 10     # score band (set)
_RR_CAP = 30        # cap on the runs-required band index


def _chase_keys(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "k_rem": (df["balls_remaining"].fillna(0) // _BALLS_BIN).astype(int),
        "k_wk": df["wickets"].fillna(0).astype(int).clip(0, 10),
        "k_rr": (df["runs_required"].clip(lower=0).fillna(0) // _RR_BIN)
                .clip(upper=_RR_CAP).astype(int),
    })


def _set_keys(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "k_bowled": (df["balls_bowled"].fillna(0) // _BALLS_BIN).astype(int),
        "k_wk": df["wickets"].fillna(0).astype(int).clip(0, 10),
        "k_score": (df["score"].fillna(0) // _SCORE_BIN).astype(int),
    })


class EmpiricalWinProb:
    """Historical-frequency win-probability model with shrinkage + backoff."""

    def __init__(self, alpha: float | None = None):
        self.alpha = SETTINGS.winprob_shrinkage if alpha is None else alpha
        self.prior_chase = 0.5
        self.prior_set = 0.5
        self.grids: dict[str, pd.DataFrame] = {}

    # --- fit -------------------------------------------------------------
    def _shrunk(self, keys: pd.DataFrame, y: np.ndarray, cols: list[str],
                prior: float) -> pd.DataFrame:
        g = keys[cols].assign(_y=y)
        agg = g.groupby(cols)["_y"].agg(sum="sum", count="count").reset_index()
        agg["wp"] = (agg["sum"] + self.alpha * prior) / (agg["count"] + self.alpha)
        return agg[cols + ["wp"]]

    def fit(self, balls: pd.DataFrame) -> "EmpiricalWinProb":
        df = balls.dropna(subset=["label_batting_team_won"]).copy()
        df["_y"] = df["label_batting_team_won"].astype(int)

        chase = df[df["innings"] == 2]
        setg = df[df["innings"] == 1]
        self.prior_chase = float(chase["_y"].mean()) if len(chase) else 0.5
        self.prior_set = float(setg["_y"].mean()) if len(setg) else 0.5

        ck = _chase_keys(chase)
        self.grids["chase_full"] = self._shrunk(ck, chase["_y"].to_numpy(),
                                                ["k_rem", "k_wk", "k_rr"], self.prior_chase)
        self.grids["chase_coarse"] = self._shrunk(ck, chase["_y"].to_numpy(),
                                                  ["k_rem", "k_wk"], self.prior_chase)
        sk = _set_keys(setg)
        self.grids["set_full"] = self._shrunk(sk, setg["_y"].to_numpy(),
                                              ["k_bowled", "k_wk", "k_score"], self.prior_set)
        self.grids["set_coarse"] = self._shrunk(sk, setg["_y"].to_numpy(),
                                                ["k_bowled", "k_wk"], self.prior_set)
        return self

    # --- predict ---------------------------------------------------------
    def _lookup(self, keys: pd.DataFrame, full: pd.DataFrame, coarse: pd.DataFrame,
                full_cols: list[str], coarse_cols: list[str], prior: float) -> np.ndarray:
        m = keys.merge(full, on=full_cols, how="left")  # left merge preserves order
        wp = np.array(m["wp"].to_numpy(dtype="float64"), copy=True)
        miss = np.isnan(wp)
        if miss.any():
            cm = keys.loc[miss, coarse_cols].merge(coarse, on=coarse_cols, how="left")
            wp[miss] = cm["wp"].to_numpy(dtype="float64")
        return np.where(np.isnan(wp), prior, wp)

    def predict(self, states: pd.DataFrame) -> np.ndarray:
        """P(batting team wins) for each row of ``states`` (order preserved)."""
        out = np.full(len(states), np.nan)
        s = states.reset_index(drop=True)
        is_chase = (s["innings"] == 2).to_numpy()

        if is_chase.any():
            ck = _chase_keys(s[is_chase])
            out[is_chase] = self._lookup(
                ck, self.grids["chase_full"], self.grids["chase_coarse"],
                ["k_rem", "k_wk", "k_rr"], ["k_rem", "k_wk"], self.prior_chase)
        if (~is_chase).any():
            sk = _set_keys(s[~is_chase])
            out[~is_chase] = self._lookup(
                sk, self.grids["set_full"], self.grids["set_coarse"],
                ["k_bowled", "k_wk", "k_score"], ["k_bowled", "k_wk"], self.prior_set)
        return out

    # --- persistence -----------------------------------------------------
    def save(self, fmt: str) -> str:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        for name, grid in self.grids.items():
            grid.to_parquet(MODELS_DIR / f"winprob_{fmt}_{name}.parquet", index=False)
        meta = {"kind": "empirical", "alpha": self.alpha,
                "prior_chase": self.prior_chase, "prior_set": self.prior_set}
        path = MODELS_DIR / f"winprob_{fmt}_meta.json"
        path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return str(path)

    @classmethod
    def load(cls, fmt: str) -> "EmpiricalWinProb":
        meta = json.loads((MODELS_DIR / f"winprob_{fmt}_meta.json").read_text(encoding="utf-8"))
        m = cls(alpha=meta["alpha"])
        m.prior_chase = meta["prior_chase"]
        m.prior_set = meta["prior_set"]
        for name in ("chase_full", "chase_coarse", "set_full", "set_coarse"):
            m.grids[name] = pd.read_parquet(MODELS_DIR / f"winprob_{fmt}_{name}.parquet")
        return m


# --- evaluation ----------------------------------------------------------
def _brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def _logloss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _test_mask(match_ids: pd.Series) -> np.ndarray:
    # Deterministic hold-out BY MATCH (never by ball): balls from one game are
    # highly correlated, so a random ball split would leak and flatter the score.
    cut = int(SETTINGS.winprob_test_fraction * 100)
    return match_ids.map(lambda mid: (zlib.crc32(str(mid).encode()) % 100) < cut).to_numpy()


def _ball_state_path(fmt: str):
    return FEATURES_DIR / f"ball_state_{fmt}.parquet"


# --- build ---------------------------------------------------------------
def build_for_format(conn, fmt: str) -> dict:
    path = _ball_state_path(fmt)
    if not path.exists():
        log.info("winprob %s: no ball_state parquet (run `ml` first) — skip", fmt)
        return {"format": fmt, "status": "no_ball_state"}

    balls = pd.read_parquet(path)
    labelled = balls.dropna(subset=["label_batting_team_won"]).copy()
    labelled["label_batting_team_won"] = labelled["label_batting_team_won"].astype(int)
    if labelled.empty:
        return {"format": fmt, "status": "no_labels"}

    # Honest calibration: fit on train matches, score held-out matches.
    test = _test_mask(labelled["match_id"])
    train_df, test_df = labelled[~test], labelled[test]
    eval_report = None
    if len(test_df) and len(train_df):
        m = EmpiricalWinProb().fit(train_df)
        p = m.predict(test_df)
        y = test_df["label_batting_team_won"].to_numpy()
        base = np.where(test_df["innings"].to_numpy() == 2, m.prior_chase, m.prior_set)
        eval_report = {
            "test_balls": int(len(test_df)),
            "brier": round(_brier(p, y), 4),
            "brier_baseline": round(_brier(base, y), 4),
            "logloss": round(_logloss(p, y), 4),
            "logloss_baseline": round(_logloss(base, y), 4),
        }

    # Final model on ALL labelled data, then persist + attach per-ball WP.
    model = EmpiricalWinProb().fit(labelled)
    model.save(fmt)

    out = balls.copy()
    out["win_prob_batting"] = np.round(model.predict(out), 4)
    out["win_prob_bowling"] = np.round(1 - out["win_prob_batting"], 4)
    out["ball_seq"] = out.groupby(["match_id", "innings"]).cumcount()
    keep = ["match_id", "gender", "innings", "ball_seq", "over", "phase",
            "batting_team", "bowling_team", "score", "wickets", "balls_remaining",
            "runs_required", "win_prob_batting", "win_prob_bowling",
            "label_batting_team_won"]
    wp_path = FEATURES_DIR / f"win_prob_{fmt}.parquet"
    out[keep].to_parquet(wp_path, index=False)

    log.info("winprob %s: %d balls scored -> %s%s", fmt, len(out), wp_path.name,
             f" | eval {eval_report}" if eval_report else "")
    return {"format": fmt, "balls": int(len(out)), "path": str(wp_path),
            "eval": eval_report}


def build_winprob(conn) -> dict:
    out = {}
    for fmt in sorted({s.fmt for s in enabled_sources()}):
        out[fmt] = build_for_format(conn, fmt)
    set_meta(conn, "winprob_built_at", dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return out


# --- query / display -----------------------------------------------------
_PHASE_END = {"powerplay": 5, "middle": 14, "death": 19}


def probability_for_state(fmt: str, *, innings: int, wickets: int,
                          balls_remaining: int | None = None,
                          runs_required: int | None = None,
                          balls_bowled: int | None = None,
                          score: int | None = None) -> float:
    """Ad-hoc win probability (batting team) for a single game state."""
    model = EmpiricalWinProb.load(fmt)
    row = {"innings": innings, "wickets": wickets,
           "balls_remaining": balls_remaining, "runs_required": runs_required,
           "balls_bowled": balls_bowled, "score": score}
    return float(round(model.predict(pd.DataFrame([row]))[0], 4))


def match_timeline(fmt: str, match_id: str) -> pd.DataFrame:
    """Per-over win-probability timeline for a match (all phases, both innings)."""
    df = pd.read_parquet(FEATURES_DIR / f"win_prob_{fmt}.parquet")
    df = df[df["match_id"].astype(str) == str(match_id)]
    if df.empty:
        return df
    # last ball of each (innings, over) is the over's closing state
    last = df.sort_values(["innings", "over", "ball_seq"]).groupby(
        ["innings", "over"], as_index=False).tail(1)
    return last.sort_values(["innings", "over"])[[
        "innings", "over", "phase", "batting_team", "score", "wickets",
        "runs_required", "win_prob_batting"]]

"""local read-only mirror of data-collection's EmpiricalWinProb /
probability_for_state (see data-collection/criiq_data/winprob.py).

loads the same persisted per-(format, gender) grid parquet files without
importing data-collection's own code, since this package never does that.
the lookup logic mirrors EmpiricalWinProb._lookup/predict directly.

WinProbLookup loads once per (format, gender) and is reused across a whole
simulated match, since reloading from disk per ball would be too slow.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ..config import ROOT_DIR

MODELS_DIR = ROOT_DIR.parent / "data-collection" / "data" / "models"

_BALLS_BIN = 6
_SCORE_BIN = 10
_RR_CAP = 30


def _chase_keys(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "k_rem": (df["balls_remaining"].fillna(0) // _BALLS_BIN).astype(int),
        "k_wk": df["wickets"].fillna(0).astype(int).clip(0, 10),
        "k_rr": (df["runs_required"].fillna(0) // 5).clip(upper=_RR_CAP).astype(int),
    })


def _set_keys(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "k_bowled": (df["balls_bowled"].fillna(0) // _BALLS_BIN).astype(int),
        "k_wk": df["wickets"].fillna(0).astype(int).clip(0, 10),
        "k_score": (df["score"].fillna(0) // _SCORE_BIN).astype(int),
    })


class WinProbLookup:
    def __init__(self, alpha: float, prior_chase: float, prior_set: float, grids: dict):
        self.alpha = alpha
        self.prior_chase = prior_chase
        self.prior_set = prior_set
        self.grids = grids

    @classmethod
    def load(cls, fmt: str, gender: str) -> "WinProbLookup":
        meta_path = MODELS_DIR / f"winprob_{fmt}_{gender}_meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(
                f"no win-probability model at {meta_path} -- run data-collection's "
                f"`criiq-data winprob` first for format={fmt} gender={gender}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        grids = {name: pd.read_parquet(MODELS_DIR / f"winprob_{fmt}_{gender}_{name}.parquet")
                 for name in ("chase_full", "chase_coarse", "set_full", "set_coarse")}
        return cls(meta["alpha"], meta["prior_chase"], meta["prior_set"], grids)

    def _lookup(self, keys: pd.DataFrame, full: pd.DataFrame, coarse: pd.DataFrame,
                full_cols: list, coarse_cols: list, prior: float) -> np.ndarray:
        m = keys.merge(full, on=full_cols, how="left")
        wp = np.array(m["wp"].to_numpy(dtype="float64"), copy=True)
        miss = np.isnan(wp)
        if miss.any():
            cm = keys.loc[miss, coarse_cols].merge(coarse, on=coarse_cols, how="left")
            wp[miss] = cm["wp"].to_numpy(dtype="float64")
        return np.where(np.isnan(wp), prior, wp)

    def predict_one(self, *, innings: int, wickets: int, balls_remaining: int | None = None,
                     runs_required: int | None = None, balls_bowled: int | None = None,
                     score: int | None = None) -> float:
        row = pd.DataFrame([{
            "innings": innings, "wickets": wickets, "balls_remaining": balls_remaining,
            "runs_required": runs_required, "balls_bowled": balls_bowled, "score": score,
        }])
        if innings == 2:
            keys = _chase_keys(row)
            wp = self._lookup(keys, self.grids["chase_full"], self.grids["chase_coarse"],
                               ["k_rem", "k_wk", "k_rr"], ["k_rem", "k_wk"], self.prior_chase)
        else:
            keys = _set_keys(row)
            wp = self._lookup(keys, self.grids["set_full"], self.grids["set_coarse"],
                               ["k_bowled", "k_wk", "k_score"], ["k_bowled", "k_wk"], self.prior_set)
        return float(round(wp[0], 4))

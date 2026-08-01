"""temporal holdout evaluation for the two contribution regressors.

split by match date, never by row, since rows from the same match are
correlated. also reports a top-quartile hit rate per target: within each
held-out match, does the model's top predicted performers overlap with the
actual top performers among players who played.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from ..config import SETTINGS
from ..features.historical import build_training_table
from ..features.schema import MODEL_FEATURES, TARGETS
from ..recommend.train import _clip_target, _make_model


def _top_quartile_hit_rate(df: pd.DataFrame, target: str) -> float | None:
    hits = []
    for _, g in df.groupby("match_id"):
        if len(g) < 4:
            continue
        pred_thresh = g["_pred"].quantile(0.75)
        actual_thresh = g[target].quantile(0.75)
        actual_top = set(g.loc[g[target] >= actual_thresh, "player_id"])
        if not actual_top:
            continue
        pred_top = set(g.loc[g["_pred"] >= pred_thresh, "player_id"])
        hits.append(len(pred_top & actual_top) / len(actual_top))
    return round(float(np.mean(hits)), 3) if hits else None


def backtest(conn: sqlite3.Connection, fmt: str = SETTINGS.format,
             gender: str = SETTINGS.gender) -> dict:
    table = build_training_table(conn, fmt, gender)
    if table.empty:
        return {"note": "no training data"}

    dates = pd.to_datetime(table["date"])
    cutoff = dates.quantile(1 - SETTINGS.backtest_test_fraction)
    train_df, test_df = table[dates < cutoff], table[dates >= cutoff]

    report = {
        "cutoff_date": str(cutoff.date()),
        "n_train_rows": int(len(train_df)), "n_test_rows": int(len(test_df)),
        "targets": {},
    }

    for target in TARGETS:
        train_rows = train_df.dropna(subset=[target])
        test_rows = test_df.dropna(subset=[target]).copy()
        if len(train_rows) < 50 or test_rows.empty:
            report["targets"][target] = {"note": "insufficient data for a temporal holdout"}
            continue

        model = _make_model(target, gender)
        # trains on the same clipped labels production uses, scores against raw actuals
        model.fit(train_rows[MODEL_FEATURES], _clip_target(train_rows[target]))
        pred = model.predict(test_rows[MODEL_FEATURES])
        actual = test_rows[target].to_numpy()

        mae = float(np.mean(np.abs(pred - actual)))
        baseline_mae = float(np.mean(np.abs(actual - train_rows[target].mean())))
        corr = float(np.corrcoef(pred, actual)[0, 1]) if len(pred) > 1 else None

        test_rows["_pred"] = pred
        report["targets"][target] = {
            "n_test_rows": int(len(test_rows)),
            "mae": round(mae, 3),
            "baseline_mae_mean_predictor": round(baseline_mae, 3),
            "corr_pred_vs_actual": round(corr, 3) if corr is not None else None,
            "top_quartile_hit_rate_within_match": _top_quartile_hit_rate(test_rows, target),
        }

    return report

"""is a dedicated learning-to-rank model worth adding over the existing WPA
regressors for ranking players?

fits a ranker (recommend.train_ranker) on the same temporal holdout as
evaluate/backtest.py and compares it against ranking by the two persisted
WPA regressors, using top-11 hit rate and spearman rank correlation (not
NDCG, since WPA is continuous and often negative).
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
from lightgbm import LGBMRanker
from scipy.stats import spearmanr

from ..config import SETTINGS
from ..features.historical import build_training_table
from ..features.schema import MODEL_FEATURES


def _combined_label(df: pd.DataFrame) -> pd.Series:
    return df["batting_wpa"].fillna(0) + df["bowling_wpa"].fillna(0)


def _graded_relevance(label: pd.Series, n_grades: int = 5) -> pd.Series:
    """lambdarank needs small non-negative integer grades, not raw values, so
    bin the combined WPA label into quantiles. duplicates="drop" handles the
    large exact-zero mass collapsing some quantile edges together.
    """
    grades = pd.qcut(label, n_grades, labels=False, duplicates="drop")
    return grades.fillna(0).astype(int)


def _group_sizes(df: pd.DataFrame) -> list[int]:
    return df.groupby("match_id", sort=False).size().tolist()


def _top_k_hit_rate(df: pd.DataFrame, score_col: str, label_col: str, k: int = 11) -> float | None:
    hits = []
    for _, g in df.groupby("match_id"):
        if len(g) < k:
            continue
        actual_top = set(g.nlargest(k, label_col).index)
        pred_top = set(g.nlargest(k, score_col).index)
        hits.append(len(actual_top & pred_top) / k)
    return round(float(np.mean(hits)), 3) if hits else None


def _mean_spearman(df: pd.DataFrame, score_col: str, label_col: str) -> float | None:
    corrs = []
    for _, g in df.groupby("match_id"):
        if len(g) < 3 or g[label_col].nunique() < 2:
            continue
        rho, _ = spearmanr(g[score_col], g[label_col])
        if not np.isnan(rho):
            corrs.append(rho)
    return round(float(np.mean(corrs)), 3) if corrs else None


def rank_backtest(conn: sqlite3.Connection, fmt: str = SETTINGS.format,
                   gender: str = SETTINGS.gender) -> dict:
    from ..recommend.train import load_models

    table = build_training_table(conn, fmt, gender)
    if table.empty:
        return {"note": "no training data"}

    table = table.dropna(subset=["batting_wpa", "bowling_wpa"], how="all").reset_index(drop=True)
    table["label"] = _combined_label(table)

    dates = pd.to_datetime(table["date"])
    cutoff = dates.quantile(1 - SETTINGS.backtest_test_fraction)
    train_df = table[dates < cutoff].sort_values("match_id").reset_index(drop=True)
    test_df = table[dates >= cutoff].reset_index(drop=True)

    report = {"cutoff_date": str(cutoff.date()), "n_train_rows": int(len(train_df)),
              "n_test_rows": int(len(test_df))}
    if len(train_df) < 200 or len(test_df) < 50:
        report["note"] = "insufficient data for a temporal holdout rank-backtest"
        return report

    ranker = LGBMRanker(objective="lambdarank", n_estimators=300, max_depth=6,
                        learning_rate=0.05, random_state=SETTINGS.random_state, verbosity=-1)
    train_grades = _graded_relevance(train_df["label"])
    ranker.fit(train_df[MODEL_FEATURES], train_grades, group=_group_sizes(train_df))
    test_df["ranker_score"] = ranker.predict(test_df[MODEL_FEATURES])

    report["ranker"] = {
        "top_11_hit_rate": _top_k_hit_rate(test_df, "ranker_score", "label"),
        "spearman": _mean_spearman(test_df, "ranker_score", "label"),
    }

    models = load_models(fmt, gender)
    if "batting_wpa" in models and "bowling_wpa" in models:
        test_df["regression_score"] = (
            models["batting_wpa"].predict(test_df[MODEL_FEATURES])
            + models["bowling_wpa"].predict(test_df[MODEL_FEATURES]))
        report["regression_baseline"] = {
            "top_11_hit_rate": _top_k_hit_rate(test_df, "regression_score", "label"),
            "spearman": _mean_spearman(test_df, "regression_score", "label"),
        }
    else:
        report["regression_baseline"] = {"note": "no persisted regressors to compare against — run `train` first"}

    return report

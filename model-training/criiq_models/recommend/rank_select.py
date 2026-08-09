"""learning-to-rank alternative to score.py + selection/optimize.py's
score-then-MILP pipeline: one fine-tuned LGBMRanker predicts each player's
rank directly, and the playing XI / top-20 pool are simply that ranking's
top 11 / top 20 -- no composite score, no constrained optimization step.
this is the model *itself* doing the selection, not just feeding scores to
something else that selects.

evaluate/rank_backtest.py already found an untuned ranker like this loses to
the two WPA regressors on this codebase's data. that comparison was never
run against a *tuned* ranker, so this module gives it a real, automated
hyperparameter search (mirroring recommend/tune.py's temporal-CV approach)
before evaluate/compare_engines.py repeats the comparison honestly.

trade-off worth being upfront about (selection/optimize.py's own docstring
makes the same point about a naive top-11): nothing here enforces a legal,
balanced side -- a model that rates five specialist batters above every
bowler will happily hand back an unplayable XI. select_xi_by_model reports
role-balance counts alongside its pick so that cost is visible, not hidden,
rather than silently enforcing it (which would just make this MILP again).
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRanker
from scipy.stats import spearmanr
from sklearn.model_selection import ParameterSampler

from ..config import RECOMMENDATION_ARTIFACTS_DIR, SETTINGS, ensure_dirs
from ..features.common import batting_capable, bowling_capable
from ..features.current import build_model_features
from ..features.historical import build_training_table
from ..features.schema import MODEL_FEATURES, NUMERIC_FEATURES
from .tune import _temporal_cv_splits

RANKER_FILENAME = "ranker.joblib"
METADATA_FILENAME = "ranker_metadata.json"

# num_leaves/min_child_samples are LightGBM's usual tuning knobs; ranges kept
# modest since a single-match candidate pool is small (dozens of rows).
PARAM_DISTRIBUTIONS = {
    "n_estimators": [100, 200, 300, 400, 500],
    "max_depth": [3, 4, 5, 6, 8, -1],
    "learning_rate": [0.02, 0.05, 0.08, 0.1, 0.15],
    "num_leaves": [15, 31, 63, 127],
    "min_child_samples": [10, 20, 30, 50],
}

MIN_ROWS_TO_TUNE = 200
DEFAULT_XI_SIZE = SETTINGS.xi_size
DEFAULT_POOL_SIZE = SETTINGS.pool_size


def _artifacts_dir(fmt: str, gender: str):
    d = RECOMMENDATION_ARTIFACTS_DIR / f"{gender}_{fmt}_ranker"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _combined_label(df: pd.DataFrame) -> pd.Series:
    return df["batting_wpa"].fillna(0) + df["bowling_wpa"].fillna(0)


def _graded_relevance(label: pd.Series, n_grades: int = 5) -> pd.Series:
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


def _fit_ranker(train_df: pd.DataFrame, params: dict) -> LGBMRanker:
    ranker = LGBMRanker(objective="lambdarank", random_state=SETTINGS.random_state, verbosity=-1, **params)
    grades = _graded_relevance(train_df["label"])
    ranker.fit(train_df[MODEL_FEATURES], grades, group=_group_sizes(train_df))
    return ranker


def tune_ranker(table: pd.DataFrame, n_iter: int = 20, random_state: int = SETTINGS.random_state) -> dict:
    """manual randomized search: LGBMRanker's grouped fit(group=...) doesn't
    fit RandomizedSearchCV's per-row scoring assumptions cleanly, so this
    loops ParameterSampler candidates itself over recommend/tune.py's same
    temporal splits, scored by mean top-11 hit rate -- the metric
    evaluate/rank_backtest.py already treats as the one that matters for a
    ranking task, not a generic regression loss.
    """
    rows = table.dropna(subset=["batting_wpa", "bowling_wpa"], how="all").reset_index(drop=True)
    if len(rows) < MIN_ROWS_TO_TUNE:
        return {"note": f"only {len(rows)} rows, need >= {MIN_ROWS_TO_TUNE} to tune"}
    rows["label"] = _combined_label(rows)

    splits = _temporal_cv_splits(rows, n_splits=4)
    if not splits:
        return {"note": "not enough distinct matches for temporal cross-validation"}

    def _cv_hit_rate(params: dict) -> float:
        scores = []
        for train_idx, test_idx in splits:
            train_fold = rows.iloc[train_idx].sort_values("match_id").reset_index(drop=True)
            test_fold = rows.iloc[test_idx].reset_index(drop=True).copy()
            ranker = _fit_ranker(train_fold, params)
            test_fold["_pred"] = ranker.predict(test_fold[MODEL_FEATURES])
            hit = _top_k_hit_rate(test_fold, "_pred", "label")
            if hit is not None:
                scores.append(hit)
        return float(np.mean(scores)) if scores else -1.0

    default_params = {"n_estimators": 300, "max_depth": 6, "learning_rate": 0.05}  # rank_backtest.py's untuned defaults
    best_params, best_score = default_params, _cv_hit_rate(default_params)
    baseline_hit_rate = best_score

    candidates = list(ParameterSampler(PARAM_DISTRIBUTIONS, n_iter=n_iter,
                                        random_state=np.random.RandomState(random_state)))
    for params in candidates:
        score = _cv_hit_rate(params)
        if score > best_score:
            best_params, best_score = params, score

    return {
        "n_rows": int(len(rows)), "n_splits": len(splits), "n_iter": n_iter,
        "best_params": best_params,
        "tuned_cv_top11_hit_rate": round(best_score, 4),
        "baseline_cv_top11_hit_rate": round(baseline_hit_rate, 4),
    }


def tune_and_train_ranker(conn: sqlite3.Connection, fmt: str = SETTINGS.format,
                           gender: str = SETTINGS.gender, n_iter: int = 20) -> dict:
    ensure_dirs()
    table = build_training_table(conn, fmt, gender)
    if table.empty:
        raise RuntimeError(f"No training rows for format={fmt} gender={gender}")

    tune_report = tune_ranker(table, n_iter=n_iter)
    metadata = {
        "format": fmt, "gender": gender,
        "trained_at": dt.datetime.now().isoformat(timespec="seconds"),
        "n_rows_total": int(len(table)), "tuning": tune_report,
    }

    artifacts_dir = _artifacts_dir(fmt, gender)
    if "best_params" in tune_report:
        rows = table.dropna(subset=["batting_wpa", "bowling_wpa"], how="all").reset_index(drop=True)
        rows["label"] = _combined_label(rows)
        rows = rows.sort_values("match_id").reset_index(drop=True)
        ranker = _fit_ranker(rows, tune_report["best_params"])
        joblib.dump(ranker, artifacts_dir / RANKER_FILENAME)
        # role_bucket is LightGBM-categorical by pandas dtype -- persisting the
        # exact category list fit() saw is what lets a live, single-row predict
        # (rank_pool below) map "batter"/"bowler"/etc. back to the same integer
        # codes training used. a fresh .astype("category") on a one-row frame
        # would instead assign code 0 to whatever's present, silently wrong.
        metadata["role_categories"] = list(rows["role_bucket"].cat.categories)

    (artifacts_dir / METADATA_FILENAME).write_text(json.dumps(metadata, indent=2, default=str))
    return metadata


def load_ranker(fmt: str = SETTINGS.format, gender: str = SETTINGS.gender):
    path = _artifacts_dir(fmt, gender) / RANKER_FILENAME
    return joblib.load(path) if path.exists() else None


def load_ranker_metadata(fmt: str = SETTINGS.format, gender: str = SETTINGS.gender) -> dict | None:
    path = _artifacts_dir(fmt, gender) / METADATA_FILENAME
    if not path.exists():
        return None
    return json.loads(path.read_text())


def rank_pool(conn: sqlite3.Connection, ranker, role_categories: list[str], player_ids: list[str],
              opponent: str, fmt: str, venue_id: str | None = None) -> list[dict]:
    """ranks player_ids by the fine-tuned model's own predicted relevance --
    this *is* the selection engine's ordering, not an input to one.
    """
    rows, ids = [], []
    for pid in player_ids:
        feats = build_model_features(conn, pid, opponent, venue_id, fmt)
        rows.append({f: feats[f] for f in MODEL_FEATURES})
        ids.append(pid)
    X = pd.DataFrame(rows)
    # a single live row's None (no data for that feature) makes pandas infer
    # "object" dtype, not float64+NaN like a multi-row training frame would --
    # LightGBM's native predict rejects object dtype outright, unlike sklearn's
    # own imputers, so cast explicitly rather than relying on inference.
    X[NUMERIC_FEATURES] = X[NUMERIC_FEATURES].astype(float)
    X["role_bucket"] = pd.Categorical(X["role_bucket"], categories=role_categories)
    preds = ranker.predict(X)
    ranked = sorted(zip(ids, preds, X["role_bucket"].astype(str)), key=lambda t: -t[1])
    return [{"player_id": pid, "model_score": float(score), "role_bucket": bucket}
            for pid, score, bucket in ranked]


def select_xi_by_model(conn: sqlite3.Connection, ranker, role_categories: list[str], player_ids: list[str],
                        opponent: str, fmt: str, venue_id: str | None = None,
                        xi_size: int = DEFAULT_XI_SIZE, pool_size: int = DEFAULT_POOL_SIZE) -> dict:
    ranked = rank_pool(conn, ranker, role_categories, player_ids, opponent, fmt, venue_id)
    xi = ranked[:xi_size]
    role_counts = {
        "batting_capable": sum(1 for p in xi if batting_capable(p["role_bucket"])),
        "bowling_capable": sum(1 for p in xi if bowling_capable(p["role_bucket"])),
    }
    return {"xi": xi, "pool": ranked[:pool_size], "method": "model_ranker",
            "role_balance": role_counts}

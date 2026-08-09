"""hyperparameter search for the batting/bowling wpa regressors.

train.py's hyperparameters were hand-picked once against
model_comparison.ipynb/training_and_selection_walkthrough.ipynb and hardcoded
-- no automated search has ever run against the current feature set. this
module adds that search (RandomizedSearchCV, already a project dependency,
so nothing new to install) and persists its own tuned artifacts alongside
(not over) train.py's, so the production models this ships today are
untouched.

cross-validation must never split a match's rows across train/test (they're
correlated -- same match, same conditions) or let a later match end up in an
earlier fold's training data (a strictly-past-only model would then be
tuned against a leak it'll never get in production). _temporal_cv_splits
enforces both: matches are bucketed by date into ordered folds, and each
fold's "train" side is every match before it (an expanding window), mirroring
evaluate/backtest.py's single train/test cutoff but repeated across several
cutoffs for a sturdier hyperparameter estimate.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.model_selection import RandomizedSearchCV

from ..config import RECOMMENDATION_ARTIFACTS_DIR, SETTINGS, ensure_dirs
from ..features.historical import build_training_table
from ..features.schema import MODEL_FEATURES
from .train import METADATA_FILENAME, MODEL_FILENAME, _clip_target, _make_model

# nested-param addressing follows sklearn's usual pipeline/ensemble
# convention (<estimator_name>__<param>): batting_wpa's model is the RF
# pipeline itself ("model" step); bowling_wpa is a VotingRegressor of
# ("hgb", HistGradientBoostingRegressor) + ("rf", the same kind of RF
# pipeline), so its RF params need the extra "rf__" hop.
PARAM_DISTRIBUTIONS = {
    "batting_wpa": {
        "model__n_estimators": [150, 200, 300, 400, 500],
        "model__max_depth": [4, 6, 8, 10, 12, None],
        "model__min_samples_leaf": [2, 5, 10, 20, 30],
        "model__max_features": [None, "sqrt", "log2", 0.5, 0.7],
    },
    "bowling_wpa": {
        "hgb__max_depth": [2, 3, 4, 5, 6],
        "hgb__min_samples_leaf": [20, 30, 50, 75, 100],
        "hgb__learning_rate": [0.03, 0.05, 0.08, 0.1, 0.15],
        "hgb__max_iter": [100, 150, 200, 300],
        "rf__model__max_depth": [4, 6, 8, 10],
        "rf__model__min_samples_leaf": [20, 50, 75, 100],
        "weights": [[0.7, 0.3], [0.6, 0.4], [0.8, 0.2], [0.5, 0.5], [0.65, 0.35]],
    },
}

MIN_ROWS_TO_TUNE = 100
DEFAULT_N_SPLITS = 4


def _tuned_artifacts_dir(fmt: str, gender: str):
    d = RECOMMENDATION_ARTIFACTS_DIR / f"{gender}_{fmt}_tuned"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _temporal_cv_splits(rows: pd.DataFrame, n_splits: int = DEFAULT_N_SPLITS) -> list[tuple[np.ndarray, np.ndarray]]:
    """expanding-window folds ordered by each match's earliest date. fold i's
    test rows are strictly later than every row in fold i's train set, and a
    match's rows always land in exactly one side. returns [] if there aren't
    enough distinct matches to form at least one usable fold.
    """
    match_dates = pd.to_datetime(rows["date"]).groupby(rows["match_id"]).min().sort_values()
    match_order = match_dates.index.to_numpy()
    n_matches = len(match_order)
    if n_matches < n_splits + 1:
        return []

    match_rank = pd.Series(np.arange(n_matches), index=match_order)
    positions = rows["match_id"].map(match_rank).to_numpy()

    fold_bounds = np.linspace(0, n_matches, n_splits + 1, dtype=int)
    splits = []
    for i in range(1, n_splits):
        train_idx = np.where(positions < fold_bounds[i])[0]
        test_idx = np.where((positions >= fold_bounds[i]) & (positions < fold_bounds[i + 1]))[0]
        if len(train_idx) and len(test_idx):
            splits.append((train_idx, test_idx))
    return splits


def tune_target(table: pd.DataFrame, target: str, gender: str = SETTINGS.gender,
                 n_iter: int = 25, random_state: int = SETTINGS.random_state) -> dict:
    """RandomizedSearchCV over target's param distribution, scored by
    negative MAE across _temporal_cv_splits. also reports the untuned
    (production defaults) model's CV MAE on the identical folds, so the gain
    from tuning is a direct, apples-to-apples number rather than an
    isolated score.
    """
    rows = table.dropna(subset=[target]).reset_index(drop=True)
    if len(rows) < MIN_ROWS_TO_TUNE:
        return {"target": target, "note": f"only {len(rows)} rows, need >= {MIN_ROWS_TO_TUNE} to tune"}

    splits = _temporal_cv_splits(rows)
    if not splits:
        return {"target": target, "note": "not enough distinct matches for temporal cross-validation"}

    X, y = rows[MODEL_FEATURES], _clip_target(rows[target])
    base_model = _make_model(target, gender)

    baseline_maes = []
    for train_idx, test_idx in splits:
        probe = clone(base_model)
        probe.fit(X.iloc[train_idx], y.iloc[train_idx])
        pred = probe.predict(X.iloc[test_idx])
        baseline_maes.append(float(np.mean(np.abs(pred - y.iloc[test_idx].to_numpy()))))

    search = RandomizedSearchCV(
        clone(base_model), PARAM_DISTRIBUTIONS[target], n_iter=n_iter, cv=splits,
        scoring="neg_mean_absolute_error", random_state=random_state, n_jobs=-1, refit=False)
    search.fit(X, y)

    return {
        "target": target, "n_rows": int(len(rows)), "n_splits": len(splits), "n_iter": n_iter,
        "best_params": search.best_params_,
        "tuned_cv_mae": round(float(-search.best_score_), 4),
        "baseline_cv_mae": round(float(np.mean(baseline_maes)), 4),
    }


def tune_and_train(conn: sqlite3.Connection, fmt: str = SETTINGS.format,
                    gender: str = SETTINGS.gender, n_iter: int = 25) -> dict:
    """tunes then fits+persists the tuned regressors, mirroring train.train()
    but writing to a `{gender}_{fmt}_tuned` artifacts directory instead of
    train.py's `{gender}_{fmt}` -- the production artifacts train() manages
    are never read or written here.
    """
    ensure_dirs()
    table = build_training_table(conn, fmt, gender)
    if table.empty:
        raise RuntimeError(f"No training rows for format={fmt} gender={gender}")

    metadata = {
        "format": fmt, "gender": gender,
        "trained_at": dt.datetime.now().isoformat(timespec="seconds"),
        "n_rows_total": int(len(table)),
        "date_range": [str(table["date"].min()), str(table["date"].max())],
        "n_iter": n_iter, "targets": {},
    }

    artifacts_dir = _tuned_artifacts_dir(fmt, gender)
    for target, filename in MODEL_FILENAME.items():
        tune_report = tune_target(table, target, gender, n_iter=n_iter)
        metadata["targets"][target] = tune_report
        if "best_params" not in tune_report:
            continue  # insufficient data for this target -- nothing to persist

        rows = table.dropna(subset=[target])
        model = clone(_make_model(target, gender))
        model.set_params(**tune_report["best_params"])
        model.fit(rows[MODEL_FEATURES], _clip_target(rows[target]))
        joblib.dump(model, artifacts_dir / filename)

    (artifacts_dir / METADATA_FILENAME).write_text(json.dumps(metadata, indent=2, default=str))
    return metadata


def load_tuned_models(fmt: str = SETTINGS.format, gender: str = SETTINGS.gender) -> dict[str, object]:
    artifacts_dir = _tuned_artifacts_dir(fmt, gender)
    models = {}
    for target, filename in MODEL_FILENAME.items():
        path = artifacts_dir / filename
        if path.exists():
            models[target] = joblib.load(path)
    return models


def load_tuned_metadata(fmt: str = SETTINGS.format, gender: str = SETTINGS.gender) -> dict | None:
    path = _tuned_artifacts_dir(fmt, gender) / METADATA_FILENAME
    if not path.exists():
        return None
    return json.loads(path.read_text())

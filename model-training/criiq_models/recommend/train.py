"""fits and saves the batting/bowling wpa regressors.

two separate models, not one blended target, since a pure bowler's near-zero
batting wpa would otherwise drag down a shared label. model choice per target
comes from model_comparison.ipynb's holdout results, see README for details.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

import joblib
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor, VotingRegressor
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from ..config import RECOMMENDATION_ARTIFACTS_DIR, SETTINGS, ensure_dirs
from ..features.historical import build_training_table
from ..features.schema import CATEGORICAL_FEATURES, MODEL_FEATURES, NUMERIC_FEATURES, TARGETS

MODEL_FILENAME = {target: f"model_{target}.joblib" for target in TARGETS}
METADATA_FILENAME = "training_metadata.json"
BACKGROUND_FILENAME = "shap_background.joblib"


def _artifacts_dir(fmt: str, gender: str):
    """models live under a `{gender}_{fmt}` subdirectory so different scopes
    don't overwrite each other's files."""
    d = RECOMMENDATION_ARTIFACTS_DIR / f"{gender}_{fmt}"
    d.mkdir(parents=True, exist_ok=True)
    return d

# (lower, upper) quantiles training labels are clipped to, tuned per target
# against holdout data, see training_and_selection_walkthrough.ipynb
TARGET_CLIP_QUANTILES = {"batting_wpa": (0.05, 0.95), "bowling_wpa": (0.02, 0.98)}


def _clip_target(y: pd.Series) -> pd.Series:
    lo_q, hi_q = TARGET_CLIP_QUANTILES.get(y.name, (0.0, 1.0))
    if (lo_q, hi_q) == (0.0, 1.0):
        return y
    return y.clip(y.quantile(lo_q), y.quantile(hi_q))


def _rf_pipeline(max_depth: int, min_samples_leaf: int, max_features=None,
                  random_state: int = SETTINGS.random_state) -> Pipeline:
    # defaults to the production seed, only overridden for exploratory checks
    pre = ColumnTransformer([
        ("num", SimpleImputer(strategy="median"), NUMERIC_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
    ])
    return Pipeline([
        ("pre", pre),
        ("model", RandomForestRegressor(
            n_estimators=300, max_depth=max_depth, min_samples_leaf=min_samples_leaf,
            max_features=max_features, random_state=random_state, n_jobs=-1)),
    ])


def _make_model(target: str, gender: str = SETTINGS.gender):
    if target == "batting_wpa":
        # params tuned against holdout data, see training_and_selection_walkthrough.ipynb
        # max_features="sqrt" only helps the female scope, so it's gender-gated
        return _rf_pipeline(max_depth=10, min_samples_leaf=5,
                             max_features="sqrt" if gender == "female" else None)
    hgb = HistGradientBoostingRegressor(
        categorical_features="from_dtype", random_state=SETTINGS.random_state,
        max_depth=2, min_samples_leaf=50)
    rf = _rf_pipeline(max_depth=6, min_samples_leaf=50)
    # weights favor hgb over rf per the same holdout tuning
    return VotingRegressor([("hgb", hgb), ("rf", rf)], weights=[0.7, 0.3])


def _fit_one(df: pd.DataFrame, target: str, gender: str = SETTINGS.gender) -> tuple[object, dict]:
    rows = df.dropna(subset=[target])
    if rows.empty:
        raise RuntimeError(f"no non-null training rows for target={target}")
    X = rows[MODEL_FEATURES]
    y = rows[target]

    model = _make_model(target, gender)

    metrics = {"n_rows": int(len(rows))}
    if len(rows) >= 50:
        X_tr, X_te, y_tr, y_te = train_test_split(
            X, y, test_size=0.2, random_state=SETTINGS.random_state)
        probe = clone(model)
        probe.fit(X_tr, _clip_target(y_tr))
        pred = probe.predict(X_te)
        # metrics are always against the raw, unclipped holdout labels
        metrics["holdout_mae"] = float((pred - y_te).abs().mean())
        metrics["holdout_r2"] = float(probe.score(X_te, y_te))

    model.fit(X, _clip_target(y))
    return model, metrics


def train(conn: sqlite3.Connection, fmt: str = SETTINGS.format,
          gender: str = SETTINGS.gender) -> dict:
    ensure_dirs()
    table = build_training_table(conn, fmt, gender)
    if table.empty:
        raise RuntimeError(f"No training rows for format={fmt} gender={gender}")

    metadata = {
        "format": fmt, "gender": gender,
        "trained_at": dt.datetime.now().isoformat(timespec="seconds"),
        "n_rows_total": int(len(table)),
        "date_range": [str(table["date"].min()), str(table["date"].max())],
        "features": MODEL_FEATURES, "categorical_features": CATEGORICAL_FEATURES,
        "targets": {},
    }

    artifacts_dir = _artifacts_dir(fmt, gender)
    for target, filename in MODEL_FILENAME.items():
        model, metrics = _fit_one(table, target, gender)
        joblib.dump(model, artifacts_dir / filename)
        metadata["targets"][target] = metrics

    (artifacts_dir / METADATA_FILENAME).write_text(json.dumps(metadata, indent=2))

    _save_background(table, artifacts_dir)

    return metadata


def _save_background(table: pd.DataFrame, artifacts_dir) -> None:
    background = table[MODEL_FEATURES].sample(
        n=min(SETTINGS.shap_background_size, len(table)), random_state=SETTINGS.random_state)
    joblib.dump(background, artifacts_dir / BACKGROUND_FILENAME)


def rebuild_background(conn: sqlite3.Connection, fmt: str = SETTINGS.format,
                        gender: str = SETTINGS.gender) -> dict:
    """(Re)writes just shap_background.joblib for an already-trained scope,
    without refitting or overwriting the models themselves -- for artifact
    sets saved before this file existed (VotingRegressor bowling_wpa targets
    can't produce SHAP without it, see recommend/shap_explain.py, so every
    all-rounder/bowler silently lost their bowling-side "Feature impact"
    breakdown until the file is regenerated once).
    """
    ensure_dirs()
    table = build_training_table(conn, fmt, gender)
    if table.empty:
        raise RuntimeError(f"No training rows for format={fmt} gender={gender}")
    artifacts_dir = _artifacts_dir(fmt, gender)
    _save_background(table, artifacts_dir)
    return {"format": fmt, "gender": gender, "background_rows": min(SETTINGS.shap_background_size, len(table)),
            "path": str(artifacts_dir / BACKGROUND_FILENAME)}


def load_models(fmt: str = SETTINGS.format, gender: str = SETTINGS.gender) -> dict[str, object]:
    artifacts_dir = _artifacts_dir(fmt, gender)
    models = {}
    for target, filename in MODEL_FILENAME.items():
        path = artifacts_dir / filename
        if path.exists():
            models[target] = joblib.load(path)
    return models


def load_metadata(fmt: str = SETTINGS.format, gender: str = SETTINGS.gender) -> dict | None:
    path = _artifacts_dir(fmt, gender) / METADATA_FILENAME
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_background(fmt: str = SETTINGS.format, gender: str = SETTINGS.gender) -> pd.DataFrame | None:
    path = _artifacts_dir(fmt, gender) / BACKGROUND_FILENAME
    if not path.exists():
        return None
    return joblib.load(path)

"""Fit + persist the two expected-Win-Probability-Added regressors.

Two independent models (batting WPA, bowling WPA) rather than one blended
label — a pure bowler's near-zero batting WPA would otherwise drag down a
single blended target during training, and all-rounders need both axes
scored. Targets are WPA (`criiq_data/wpa.py` — how much a player's
batting/bowling actually swung their team's win probability), not
contribution-share: contribution-share couldn't distinguish a proven
match-winner from a fringe player with a good-looking stat line in
low-stakes matches.

The two targets use different model families, picked per-target from
`model_comparison.ipynb`'s real holdout numbers rather than assumed —
re-run that notebook after any feature change and re-check this choice:

  * `bowling_wpa`: a `VotingRegressor` averaging a shallow
    `HistGradientBoostingRegressor` (`max_depth=2`) with a regularized
    `RandomForestRegressor` (`max_depth=6`). Bowling-WPA is the noisier of
    the two targets (see README's Known Limitations), and every one of these
    choices was checked against the real temporal holdout, not assumed:
    shrinking HistGB from its unconstrained default down to `max_depth=2`
    alone lifted correlation from ~0.088 to ~0.105 (deeper trees just
    memorize per-match noise on a target this weak); blending in the RF
    added another few points on top (~0.105 -> ~0.110) with lower run-to-run
    variance than either alone. Both checked across 3 different holdout
    fractions (0.15/0.2/0.25) and 5 random seeds each, not a single lucky
    split.
  * `batting_wpa`: `RandomForestRegressor` (`max_depth=10, min_samples_leaf=5`)
    has the better R2/correlation than HistGB even though the two are within
    noise on MAE. Unlike HistGB it needs NaNs imputed and `role_bucket`
    one-hot encoded, so it's wrapped in a small `Pipeline`.

Both targets' *training* labels (never the holdout labels used to report
metrics) are winsorized before fitting — see `TARGET_CLIP_QUANTILES` below —
for the same reason a shallower tree helps bowling: a single freak over (a
hat-trick, a 30-run over) swings per-match WPA far more than a typical
performance does, and without clipping, the model spends its limited
capacity chasing those rare extremes instead of the typical signal that
actually generalizes.
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

# (lower, upper) quantiles training labels are clipped to before fitting --
# tuned per-target against the real temporal holdout (see module docstring).
# Bowling gets the more aggressive clip: its per-match WPA has fatter tails
# (a single over can swing it far more than a single over's-worth of batting
# swings batting WPA), so it benefits from more protection against them.
TARGET_CLIP_QUANTILES = {"batting_wpa": (0.05, 0.95), "bowling_wpa": (0.10, 0.90)}


def _clip_target(y: pd.Series) -> pd.Series:
    lo_q, hi_q = TARGET_CLIP_QUANTILES.get(y.name, (0.0, 1.0))
    if (lo_q, hi_q) == (0.0, 1.0):
        return y
    return y.clip(y.quantile(lo_q), y.quantile(hi_q))


def _rf_pipeline(max_depth: int, min_samples_leaf: int) -> Pipeline:
    pre = ColumnTransformer([
        ("num", SimpleImputer(strategy="median"), NUMERIC_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
    ])
    return Pipeline([
        ("pre", pre),
        ("model", RandomForestRegressor(
            n_estimators=300, max_depth=max_depth, min_samples_leaf=min_samples_leaf,
            random_state=SETTINGS.random_state, n_jobs=-1)),
    ])


def _make_model(target: str):
    if target == "batting_wpa":
        # max_depth/min_samples_leaf mirror model_comparison.ipynb's tested
        # config exactly -- an unregularized RandomForestRegressor overfits
        # this noisy per-match WPA target badly enough to fall *below* the
        # mean-predictor baseline on holdout (confirmed by running it).
        return _rf_pipeline(max_depth=10, min_samples_leaf=5)
    hgb = HistGradientBoostingRegressor(
        categorical_features="from_dtype", random_state=SETTINGS.random_state,
        max_depth=2, min_samples_leaf=50)
    rf = _rf_pipeline(max_depth=6, min_samples_leaf=50)
    return VotingRegressor([("hgb", hgb), ("rf", rf)])


def _fit_one(df: pd.DataFrame, target: str) -> tuple[object, dict]:
    rows = df.dropna(subset=[target])
    X = rows[MODEL_FEATURES]
    y = rows[target]

    model = _make_model(target)

    metrics = {"n_rows": int(len(rows))}
    if len(rows) >= 50:
        X_tr, X_te, y_tr, y_te = train_test_split(
            X, y, test_size=0.2, random_state=SETTINGS.random_state)
        probe = clone(model)
        probe.fit(X_tr, _clip_target(y_tr))
        pred = probe.predict(X_te)
        # Metrics are always against the RAW (unclipped) holdout labels --
        # clipping only ever touches what the model trains on, never what
        # it's judged against, so these numbers stay an honest read of
        # real-world error.
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

    for target, filename in MODEL_FILENAME.items():
        model, metrics = _fit_one(table, target)
        joblib.dump(model, RECOMMENDATION_ARTIFACTS_DIR / filename)
        metadata["targets"][target] = metrics

    (RECOMMENDATION_ARTIFACTS_DIR / METADATA_FILENAME).write_text(
        json.dumps(metadata, indent=2))
    return metadata


def load_models() -> dict[str, object]:
    models = {}
    for target, filename in MODEL_FILENAME.items():
        path = RECOMMENDATION_ARTIFACTS_DIR / filename
        if path.exists():
            models[target] = joblib.load(path)
    return models


def load_metadata() -> dict | None:
    path = RECOMMENDATION_ARTIFACTS_DIR / METADATA_FILENAME
    if not path.exists():
        return None
    return json.loads(path.read_text())

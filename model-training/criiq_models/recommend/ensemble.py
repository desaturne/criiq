"""blends the production regressor with its fine-tuned counterpart, so the
final score commits to neither alone.

RecommendationScorer already accepts a `models` dict in its constructor
(see recommend/score.py) precisely so a caller can hand it something other
than train.load_models()'s output -- AveragedRegressor slots into that dict
unchanged, needing no edits to score.py or selection/optimize.py. the MILP
selector still runs exactly as it does today; only the score it optimizes
over can come from this blend instead.
"""
from __future__ import annotations

import numpy as np

from ..config import SETTINGS
from .train import load_models
from .tune import load_tuned_models


class AveragedRegressor:
    """predict(X) = mean of every member model's predict(X). members must
    share scikit-learn's predict(X) -> array-like interface; that's all this
    needs, so a production model and a freshly re-tuned one -- or any other
    number of variants -- can be blended interchangeably.
    """

    def __init__(self, models: list):
        if not models:
            raise ValueError("AveragedRegressor needs at least one model")
        self.models = models

    def predict(self, X):
        preds = np.column_stack([m.predict(X) for m in self.models])
        return preds.mean(axis=1)


def build_ensemble_models(fmt: str = SETTINGS.format, gender: str = SETTINGS.gender) -> dict[str, object]:
    """averages the persisted production model with the persisted tuned one,
    per target. a target only present on one side (tuning hasn't run yet,
    or produced too little data to persist) falls back to whichever single
    model exists rather than dropping the target -- same "no worse than the
    weaker input" behavior a caller would want from an ensemble.
    """
    baseline = load_models(fmt, gender)
    tuned = load_tuned_models(fmt, gender)

    out = {}
    for target in set(baseline) | set(tuned):
        members = [m for m in (baseline.get(target), tuned.get(target)) if m is not None]
        out[target] = AveragedRegressor(members) if len(members) > 1 else members[0]
    return out

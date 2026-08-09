from __future__ import annotations

import numpy as np
import pytest

from criiq_models.recommend import ensemble as ensemble_module
from criiq_models.recommend.ensemble import AveragedRegressor, build_ensemble_models


class _FixedRegressor:
    def __init__(self, value: float):
        self.value = value

    def predict(self, X):
        return np.full(len(X), self.value)


def test_averaged_regressor_predicts_the_elementwise_mean():
    ensemble = AveragedRegressor([_FixedRegressor(2.0), _FixedRegressor(4.0)])
    preds = ensemble.predict([0, 0, 0])
    assert list(preds) == [3.0, 3.0, 3.0]


def test_averaged_regressor_of_one_model_returns_that_models_prediction():
    ensemble = AveragedRegressor([_FixedRegressor(5.0)])
    assert list(ensemble.predict([0, 0])) == [5.0, 5.0]


def test_averaged_regressor_rejects_an_empty_model_list():
    with pytest.raises(ValueError):
        AveragedRegressor([])


def test_build_ensemble_models_averages_when_both_sides_have_the_target(monkeypatch):
    monkeypatch.setattr(ensemble_module, "load_models",
                         lambda fmt, gender: {"batting_wpa": _FixedRegressor(1.0)})
    monkeypatch.setattr(ensemble_module, "load_tuned_models",
                         lambda fmt, gender: {"batting_wpa": _FixedRegressor(3.0)})

    models = build_ensemble_models("T20", "female")
    assert isinstance(models["batting_wpa"], AveragedRegressor)
    assert list(models["batting_wpa"].predict([0])) == [2.0]


def test_build_ensemble_models_falls_back_to_the_single_side_that_exists(monkeypatch):
    monkeypatch.setattr(ensemble_module, "load_models",
                         lambda fmt, gender: {"batting_wpa": _FixedRegressor(1.0), "bowling_wpa": _FixedRegressor(9.0)})
    monkeypatch.setattr(ensemble_module, "load_tuned_models", lambda fmt, gender: {})

    models = build_ensemble_models("T20", "female")
    assert models["batting_wpa"].predict([0])[0] == 1.0
    assert not isinstance(models["batting_wpa"], AveragedRegressor)


def test_build_ensemble_models_is_empty_when_neither_side_has_anything(monkeypatch):
    monkeypatch.setattr(ensemble_module, "load_models", lambda fmt, gender: {})
    monkeypatch.setattr(ensemble_module, "load_tuned_models", lambda fmt, gender: {})

    assert build_ensemble_models("T20", "female") == {}

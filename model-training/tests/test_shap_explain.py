from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LinearRegression

from criiq_models.config import SETTINGS
from criiq_models.features.schema import CATEGORICAL_FEATURES, MODEL_FEATURES, NUMERIC_FEATURES
from criiq_models.recommend import shap_explain
from criiq_models.recommend.train import _make_model


def _synthetic_table(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    df = pd.DataFrame({f: rng.randn(n) for f in NUMERIC_FEATURES})
    df["role_bucket"] = pd.Series(
        rng.choice(["batter", "bowler", "all-rounder", "unknown"], size=n)).astype("category")
    return df


def _synthetic_target(df: pd.DataFrame) -> pd.Series:
    signal = df[NUMERIC_FEATURES[:5]].sum(axis=1) + (df["role_bucket"] == "bowler").astype(float) * 2
    return signal + np.random.RandomState(1).randn(len(df)) * 0.1


def _fit(target: str, gender: str = "female", n: int = 400):
    df = _synthetic_table(n)
    y = _synthetic_target(df)
    model = _make_model(target, gender)
    model.fit(df[MODEL_FEATURES], y)
    return model, df


def _one_row(df: pd.DataFrame, i: int = 7) -> pd.DataFrame:
    return df[MODEL_FEATURES].iloc[[i]]


def test_pipeline_shap_reconstructs_prediction_exactly():
    model, df = _fit("batting_wpa")
    row = _one_row(df)

    values, base_value = shap_explain.compute_shap_values(model, row)

    assert values.shape == (1, len(MODEL_FEATURES))
    reconstructed = base_value + values.sum()
    assert reconstructed == pytest.approx(float(model.predict(row)[0]), abs=1e-6)


def test_voting_regressor_shap_reconstructs_prediction_exactly():
    model, df = _fit("bowling_wpa")
    row = _one_row(df)
    background = df[MODEL_FEATURES].sample(20, random_state=2)

    values, base_value = shap_explain.compute_shap_values(model, row, background)

    assert values.shape == (1, len(MODEL_FEATURES))
    reconstructed = base_value + values.sum()
    assert reconstructed == pytest.approx(float(model.predict(row)[0]), abs=1e-4)


def test_voting_regressor_shap_requires_background():
    model, df = _fit("bowling_wpa")
    row = _one_row(df)

    with pytest.raises(ValueError):
        shap_explain.compute_shap_values(model, row, background=None)


def test_categorical_vocab_matches_pipeline_onehotencoder():
    model, _ = _fit("bowling_wpa")
    rf_pipeline = model.named_estimators_["rf"]
    expected = list(rf_pipeline.named_steps["pre"].named_transformers_["cat"].categories_[0])

    vocab = shap_explain._categorical_vocab(model)

    assert vocab["role_bucket"] == expected


def test_compute_shap_values_rejects_unknown_model_type():
    with pytest.raises(TypeError):
        shap_explain.compute_shap_values(LinearRegression(), pd.DataFrame())


def test_explain_prediction_reports_a_per_target_error_without_background():
    batting_model, df = _fit("batting_wpa")
    bowling_model, _ = _fit("bowling_wpa")
    feats = df[MODEL_FEATURES].iloc[7].to_dict()

    result = shap_explain.explain_prediction(
        {"batting_wpa": batting_model, "bowling_wpa": bowling_model}, feats, background=None)

    assert "contributions" in result["batting_wpa"]
    assert "error" in result["bowling_wpa"]


def test_explain_prediction_output_shape_and_ranking():
    batting_model, df = _fit("batting_wpa")
    bowling_model, _ = _fit("bowling_wpa", n=400)
    background = df[MODEL_FEATURES].sample(20, random_state=3)
    feats = df[MODEL_FEATURES].iloc[7].to_dict()

    result = shap_explain.explain_prediction(
        {"batting_wpa": batting_model, "bowling_wpa": bowling_model}, feats, background)

    assert set(result) == {"batting_wpa", "bowling_wpa"}
    for target_result in result.values():
        assert set(target_result["contributions"]) == set(MODEL_FEATURES)
        assert target_result["predicted_value"] == pytest.approx(
            target_result["base_value"] + sum(target_result["contributions"].values()), abs=1e-4)
        assert len(target_result["top_contributions"]) <= SETTINGS.shap_top_features
        magnitudes = [abs(entry["value"]) for entry in target_result["top_contributions"]]
        assert magnitudes == sorted(magnitudes, reverse=True)
        for entry in target_result["top_contributions"]:
            assert entry["value"] == target_result["contributions"][entry["feature"]]

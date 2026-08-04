from __future__ import annotations

import numpy as np
import pandas as pd
import shap
from sklearn.ensemble import VotingRegressor
from sklearn.pipeline import Pipeline

from ..config import SETTINGS
from ..features.schema import CATEGORICAL_FEATURES, MODEL_FEATURES, NUMERIC_FEATURES


def _feature_groups(transformed_names: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {f: [] for f in MODEL_FEATURES}
    for name in transformed_names:
        transformer, _, original = name.partition("__")
        if transformer == "num":
            groups[original].append(name)
        else:
            feature = next(f for f in CATEGORICAL_FEATURES if original.startswith(f"{f}_"))
            groups[feature].append(name)
    return groups


def _pipeline_shap(pipeline: Pipeline, X: pd.DataFrame) -> tuple[np.ndarray, float]:
    pre, model = pipeline.named_steps["pre"], pipeline.named_steps["model"]
    transformed_names = list(pre.get_feature_names_out())
    groups = _feature_groups(transformed_names)
    name_to_col = {name: i for i, name in enumerate(transformed_names)}

    explainer = shap.TreeExplainer(model, feature_perturbation="tree_path_dependent")
    raw_values = np.asarray(explainer.shap_values(pre.transform(X)))
    if raw_values.ndim == 3:
        raw_values = raw_values[0]

    values = np.zeros((raw_values.shape[0], len(MODEL_FEATURES)))
    for j, feature in enumerate(MODEL_FEATURES):
        cols = [name_to_col[n] for n in groups[feature]]
        values[:, j] = raw_values[:, cols].sum(axis=1)
    base_value = float(np.asarray(explainer.expected_value).reshape(-1)[0])
    return values, base_value


def _categorical_vocab(voting_regressor: VotingRegressor) -> dict[str, list]:
    for name, _ in voting_regressor.estimators:
        estimator = voting_regressor.named_estimators_[name]
        if isinstance(estimator, Pipeline):
            encoder = estimator.named_steps["pre"].named_transformers_["cat"]
            return {feature: list(categories)
                    for feature, categories in zip(CATEGORICAL_FEATURES, encoder.categories_)}
    raise ValueError("VotingRegressor has no Pipeline sub-estimator to source the categorical "
                      "vocabulary from")


def _hist_gradient_boosting_shap(model, X: pd.DataFrame, background: pd.DataFrame,
                                  vocab: dict[str, list]) -> tuple[np.ndarray, float]:
    code_maps = {f: {cat: i for i, cat in enumerate(cats)} for f, cats in vocab.items()}
    decode_maps = {f: np.asarray(cats) for f, cats in vocab.items()}
    n_numeric = len(NUMERIC_FEATURES)

    def _encode(df: pd.DataFrame) -> np.ndarray:
        numeric_part = df[NUMERIC_FEATURES].to_numpy(dtype=float)
        code_parts = [df[f].map(code_maps[f]).fillna(0).to_numpy(dtype=float).reshape(-1, 1)
                      for f in CATEGORICAL_FEATURES]
        return np.hstack([numeric_part, *code_parts])

    def _predict(encoded: np.ndarray) -> np.ndarray:
        encoded = np.atleast_2d(encoded)
        frame = pd.DataFrame(encoded[:, :n_numeric], columns=NUMERIC_FEATURES)
        for i, f in enumerate(CATEGORICAL_FEATURES):
            codes = np.clip(np.round(encoded[:, n_numeric + i]).astype(int),
                             0, len(decode_maps[f]) - 1)
            frame[f] = decode_maps[f][codes]
        return model.predict(frame[MODEL_FEATURES])

    background_encoded = _encode(background)
    masker = shap.maskers.Independent(background_encoded, max_samples=len(background_encoded))
    explainer = shap.explainers.Permutation(_predict, masker)
    explanation = explainer(_encode(X), silent=True)

    base_value = float(np.asarray(explanation.base_values).reshape(-1)[0])
    return np.asarray(explanation.values), base_value


def _voting_regressor_shap(model: VotingRegressor, X: pd.DataFrame,
                            background: pd.DataFrame | None) -> tuple[np.ndarray, float]:
    names = [name for name, _ in model.estimators]
    raw_weights = model.weights if model.weights is not None else [1.0] * len(names)
    weights = np.asarray(raw_weights, dtype=float)
    weights = weights / weights.sum()

    values = np.zeros((len(X), len(MODEL_FEATURES)))
    base_value = 0.0
    vocab = None
    for name, weight in zip(names, weights):
        estimator = model.named_estimators_[name]
        if isinstance(estimator, Pipeline):
            est_values, est_base = _pipeline_shap(estimator, X)
        else:
            if background is None or background.empty:
                raise ValueError("a background sample is required to explain this "
                                  "VotingRegressor's non-Pipeline sub-estimator")
            vocab = vocab or _categorical_vocab(model)
            est_values, est_base = _hist_gradient_boosting_shap(estimator, X, background, vocab)
        values += est_values * weight
        base_value += est_base * weight
    return values, base_value


def compute_shap_values(model, X: pd.DataFrame,
                         background: pd.DataFrame | None = None) -> tuple[np.ndarray, float]:
    if isinstance(model, Pipeline):
        return _pipeline_shap(model, X)
    if isinstance(model, VotingRegressor):
        return _voting_regressor_shap(model, X, background)
    raise TypeError(f"no SHAP strategy for model type {type(model).__name__}")


def explain_prediction(models: dict[str, object], feats: dict,
                        background: pd.DataFrame | None = None) -> dict:
    row = pd.DataFrame([{f: feats[f] for f in MODEL_FEATURES}])
    result = {}
    for target, model in models.items():
        try:
            values, base_value = compute_shap_values(model, row, background)
        except ValueError as exc:
            result[target] = {"error": str(exc)}
            continue
        contributions = {feature: round(float(values[0, j]), 6)
                          for j, feature in enumerate(MODEL_FEATURES)}
        ranked = sorted(contributions.items(), key=lambda kv: -abs(kv[1]))
        result[target] = {
            "base_value": round(base_value, 6),
            "predicted_value": round(base_value + float(values.sum()), 6),
            "contributions": contributions,
            "top_contributions": [{"feature": f, "value": v}
                                   for f, v in ranked[:SETTINGS.shap_top_features]],
        }
    return result

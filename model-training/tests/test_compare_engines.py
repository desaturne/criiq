from __future__ import annotations

from criiq_models.evaluate import compare_engines as compare_module
from criiq_models.recommend import train as train_module
from criiq_models.recommend import tune as tune_module


def test_xi_overlap_comparison_notes_when_no_production_models_exist(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(train_module, "RECOMMENDATION_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(tune_module, "RECOMMENDATION_ARTIFACTS_DIR", tmp_path)

    result = compare_module.xi_overlap_comparison(conn, "T20", "female")
    assert "no persisted production models" in result["note"]


def test_regression_backtest_comparison_reports_insufficient_data_note(conn):
    result = compare_module.regression_backtest_comparison(conn, "T20", "female")
    assert result["note"] == "no training data"

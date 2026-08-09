from __future__ import annotations

import math

from criiq_models.recommend import rank_select as rank_select_module
from criiq_models.recommend import tune as tune_module
from tests.test_tune import _seed_many_matches


def test_tune_ranker_reports_a_note_when_rows_are_too_few(conn):
    from criiq_models.features.historical import build_training_table
    _seed_many_matches(conn, "female", n_matches=3, players=["p0", "p1"], team="India", opponent="Australia")
    conn.commit()
    table = build_training_table(conn, "T20", "female")
    report = rank_select_module.tune_ranker(table, n_iter=1)
    assert "note" in report
    assert "best_params" not in report


def test_tune_and_train_ranker_persists_role_categories_and_powers_live_selection(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(rank_select_module, "RECOMMENDATION_ARTIFACTS_DIR", tmp_path)

    players = [f"p{i}" for i in range(6)]
    _seed_many_matches(conn, "female", n_matches=40, players=players, team="India", opponent="Australia")
    conn.commit()

    metadata = rank_select_module.tune_and_train_ranker(conn, "T20", "female", n_iter=1)
    assert "best_params" in metadata["tuning"]
    assert set(metadata["role_categories"]) <= {"batter", "bowler", "all-rounder", "unknown"}

    ranker = rank_select_module.load_ranker("T20", "female")
    reloaded_metadata = rank_select_module.load_ranker_metadata("T20", "female")
    assert ranker is not None
    assert reloaded_metadata["role_categories"] == metadata["role_categories"]

    result = rank_select_module.select_xi_by_model(
        conn, ranker, reloaded_metadata["role_categories"], players, "Australia", "T20")

    assert len(result["xi"]) == min(11, len(players))
    assert {p["player_id"] for p in result["xi"]} <= set(players)
    assert all(math.isfinite(p["model_score"]) for p in result["pool"])
    assert result["method"] == "model_ranker"
    assert "batting_capable" in result["role_balance"]


def test_load_ranker_and_metadata_are_none_when_nothing_tuned_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(rank_select_module, "RECOMMENDATION_ARTIFACTS_DIR", tmp_path)
    assert rank_select_module.load_ranker("T20", "female") is None
    assert rank_select_module.load_ranker_metadata("T20", "female") is None

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from criiq_models.features.schema import CATEGORICAL_FEATURES, MODEL_FEATURES, NUMERIC_FEATURES
from criiq_models.recommend import train as train_module
from criiq_models.recommend import tune as tune_module
from tests.conftest import add_match, add_match_impact, add_match_wpa, register_player
from tests.test_train import _stub_fit_one


def _synthetic_table(n_matches: int, players_per_match: int = 4, seed: int = 0) -> pd.DataFrame:
    """a MODEL_FEATURES-shaped table with match_id/date, bypassing the DB
    entirely -- tune_target only ever needs the dataframe, and building one
    directly is far cheaper than seeding enough realistic rows through
    build_training_table's full join pipeline just to exercise the search
    logic itself.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for m in range(n_matches):
        date = pd.Timestamp("2023-01-01") + pd.Timedelta(days=m)
        for p in range(players_per_match):
            row = {f: rng.normal(size=1)[0] for f in NUMERIC_FEATURES}
            row["role_bucket"] = rng.choice(["batter", "bowler", "all-rounder"])
            row["match_id"] = f"m{m}"
            row["date"] = date.isoformat()
            # target correlated with one feature + noise, so tuning has a real signal to find
            row["batting_wpa"] = 0.3 * row["career_matches"] + rng.normal(scale=0.5)
            rows.append(row)
    df = pd.DataFrame(rows)
    df["role_bucket"] = df["role_bucket"].astype("category")
    return df


def test_temporal_cv_splits_never_lets_a_test_row_precede_its_train_rows():
    table = _synthetic_table(n_matches=8, players_per_match=3)
    splits = tune_module._temporal_cv_splits(table, n_splits=4)
    assert len(splits) == 3  # n_splits - 1 usable expanding folds

    dates = pd.to_datetime(table["date"])
    for train_idx, test_idx in splits:
        assert dates.iloc[train_idx].max() <= dates.iloc[test_idx].min()
        assert set(train_idx) & set(test_idx) == set()


def test_temporal_cv_splits_never_splits_one_match_across_train_and_test():
    table = _synthetic_table(n_matches=8, players_per_match=3)
    splits = tune_module._temporal_cv_splits(table, n_splits=4)
    for train_idx, test_idx in splits:
        train_matches = set(table.iloc[train_idx]["match_id"])
        test_matches = set(table.iloc[test_idx]["match_id"])
        assert train_matches & test_matches == set()


def test_temporal_cv_splits_returns_empty_when_too_few_matches():
    table = _synthetic_table(n_matches=3, players_per_match=3)
    assert tune_module._temporal_cv_splits(table, n_splits=4) == []


def test_tune_target_reports_a_note_when_rows_are_too_few():
    table = _synthetic_table(n_matches=3, players_per_match=2)
    report = tune_module.tune_target(table, "batting_wpa", "female", n_iter=2)
    assert "note" in report
    assert "best_params" not in report


def test_tune_target_returns_best_params_and_a_comparable_baseline_score():
    table = _synthetic_table(n_matches=20, players_per_match=6)
    report = tune_module.tune_target(table, "batting_wpa", "female", n_iter=3)

    assert report["target"] == "batting_wpa"
    assert set(report["best_params"]) == set(tune_module.PARAM_DISTRIBUTIONS["batting_wpa"])
    assert report["tuned_cv_mae"] >= 0
    assert report["baseline_cv_mae"] >= 0
    assert report["n_splits"] == 3


def _seed_many_matches(conn, gender: str, n_matches: int, players: list[str], team: str, opponent: str) -> None:
    for i, pid in enumerate(players):
        register_player(conn, pid, pid)
        # domestic_form_* (features/historical._attach_domestic_form) is
        # sourced from player_match_wpa rows with team_type='club', dated
        # before the international matches below. otherwise it's entirely
        # NaN across every row, which crashes HistGradientBoostingRegressor's
        # binning on this synthetic dataset (real criiq.db always has some
        # domestic rows for players with enough history to be tuning-eligible).
        add_match_wpa(conn, pid, f"club_{pid}", batting_wpa=0.01 * i, bowling_wpa=0.005 * i,
                      date="2022-12-01", team_type="club")
    for m in range(n_matches):
        date = (pd.Timestamp("2023-01-01") + pd.Timedelta(days=m)).date().isoformat()
        mid = f"match_{gender}_{m}"
        add_match(conn, mid, date, team, opponent, gender=gender)
        for i, pid in enumerate(players):
            add_match_impact(conn, pid, mid, date, team, opponent, won=1,
                              bat_sr=90.0 + 5 * i + m, bat_contrib=10.0 + i + (m % 5),
                              economy=6.0 + i * 0.1, bowl_contrib=8.0 + i, wickets=i % 3, balls_bowled=18)
            add_match_wpa(conn, pid, mid, batting_wpa=0.01 * i + 0.001 * m, bowling_wpa=0.005 * i, date=date)


def test_tune_and_train_persists_to_a_tuned_dir_distinct_from_production(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(train_module, "RECOMMENDATION_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(tune_module, "RECOMMENDATION_ARTIFACTS_DIR", tmp_path)

    players = [f"p{i}" for i in range(6)]
    _seed_many_matches(conn, "female", n_matches=20, players=players, team="India", opponent="Australia")
    conn.commit()

    # train()'s own model quality isn't under test here (that's test_train.py's
    # job) -- only that tuning writes elsewhere and never touches it. the real
    # HGB/RF fit needs more realistically-varied data than this synthetic seed
    # gives it, so swap in the same lightweight stub test_train.py uses.
    monkeypatch.setattr(train_module, "_fit_one", _stub_fit_one)
    baseline_metadata = train_module.train(conn, "T20", "female")
    tuned_metadata = tune_module.tune_and_train(conn, "T20", "female", n_iter=2)

    assert (tmp_path / "female_T20").is_dir()
    assert (tmp_path / "female_T20_tuned").is_dir()
    assert (tmp_path / "female_T20").resolve() != (tmp_path / "female_T20_tuned").resolve()

    # production artifacts are untouched by tuning -- reloading them still
    # matches what train() itself just reported.
    reloaded_baseline = train_module.load_metadata("T20", "female")
    assert reloaded_baseline["n_rows_total"] == baseline_metadata["n_rows_total"]

    tuned_models = tune_module.load_tuned_models("T20", "female")
    assert set(tuned_models) == {"batting_wpa", "bowling_wpa"}
    assert tune_module.load_tuned_metadata("T20", "female")["n_rows_total"] == tuned_metadata["n_rows_total"]

    baseline_models = train_module.load_models("T20", "female")
    assert baseline_models["batting_wpa"] is not tuned_models["batting_wpa"]


def test_load_tuned_models_and_metadata_are_empty_when_nothing_tuned_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(tune_module, "RECOMMENDATION_ARTIFACTS_DIR", tmp_path)
    assert tune_module.load_tuned_models("T20", "female") == {}
    assert tune_module.load_tuned_metadata("T20", "female") is None

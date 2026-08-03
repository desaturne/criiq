from __future__ import annotations

from sklearn.dummy import DummyRegressor

from criiq_models.recommend import train as train_module
from tests.conftest import add_match, add_match_impact, add_match_wpa, register_player


def _seed_gender(conn, gender: str, player_id: str, opponent: str) -> None:
    for i, d in enumerate(["2024-01-01", "2024-02-01"]):
        mid = f"{player_id}_{i}"
        add_match(conn, mid, d, "India", opponent, gender=gender)
        add_match_impact(conn, player_id, mid, d, "India", opponent, won=1,
                          bat_sr=110.0, bat_contrib=12.0, economy=7.0, bowl_contrib=10.0,
                          wickets=1, balls_bowled=18)
        add_match_wpa(conn, player_id, mid, batting_wpa=0.05, bowling_wpa=0.02, date=d)


def _stub_fit_one(df, target, gender=None):
    """real `_fit_one` needs realistically-sized data for sklearn pipelines
    to bin/split on, already covered by the end-to-end training run. this
    stub isolates what's under test here: train()'s orchestration, not
    model quality.
    """
    rows = df.dropna(subset=[target])
    model = DummyRegressor().fit(rows[["career_matches"]].fillna(0), rows[target])
    return model, {"n_rows": int(len(rows))}


def test_artifacts_dir_is_scoped_by_format_and_gender(tmp_path, monkeypatch):
    monkeypatch.setattr(train_module, "RECOMMENDATION_ARTIFACTS_DIR", tmp_path)

    female_dir = train_module._artifacts_dir("T20", "female")
    male_dir = train_module._artifacts_dir("T20", "male")

    assert female_dir != male_dir
    assert female_dir == tmp_path / "female_T20"
    assert male_dir == tmp_path / "male_T20"
    assert female_dir.is_dir() and male_dir.is_dir()


def test_training_one_gender_does_not_clobber_the_others_artifacts(conn, tmp_path, monkeypatch):
    # the bug this guards against: before artifacts were scoped by
    # (format, gender), every scope shared filenames, so training a second
    # gender silently overwrote the first's models.
    monkeypatch.setattr(train_module, "RECOMMENDATION_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(train_module, "_fit_one", _stub_fit_one)

    register_player(conn, "p_female", "A Player", role="batter")
    _seed_gender(conn, "female", "p_female", "Australia")
    register_player(conn, "p_male", "B Player", role="batter")
    _seed_gender(conn, "male", "p_male", "England")
    conn.commit()

    female_metadata = train_module.train(conn, "T20", "female")
    male_metadata = train_module.train(conn, "T20", "male")

    assert female_metadata["gender"] == "female"
    assert male_metadata["gender"] == "male"

    # re-loading female metadata after training male proves training male
    # never touched female's files.
    reloaded_female = train_module.load_metadata("T20", "female")
    reloaded_male = train_module.load_metadata("T20", "male")
    assert reloaded_female["gender"] == "female"
    assert reloaded_female["n_rows_total"] == female_metadata["n_rows_total"]
    assert reloaded_male["gender"] == "male"
    assert reloaded_male["n_rows_total"] == male_metadata["n_rows_total"]

    female_models = train_module.load_models("T20", "female")
    male_models = train_module.load_models("T20", "male")
    assert set(female_models) == {"batting_wpa", "bowling_wpa"}
    assert set(male_models) == {"batting_wpa", "bowling_wpa"}
    # distinct fitted estimators, not the same object/file reused across genders.
    assert female_models["batting_wpa"] is not male_models["batting_wpa"]


def test_load_models_and_metadata_are_scoped_when_nothing_trained_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(train_module, "RECOMMENDATION_ARTIFACTS_DIR", tmp_path)

    assert train_module.load_models("T20", "male") == {}
    assert train_module.load_metadata("T20", "male") is None


def test_train_persists_a_shap_background_sample(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(train_module, "RECOMMENDATION_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(train_module, "_fit_one", _stub_fit_one)

    register_player(conn, "p_female", "A Player", role="batter")
    _seed_gender(conn, "female", "p_female", "Australia")
    conn.commit()

    metadata = train_module.train(conn, "T20", "female")

    background = train_module.load_background("T20", "female")
    from criiq_models.features.schema import MODEL_FEATURES
    assert background is not None
    assert list(background.columns) == MODEL_FEATURES
    assert len(background) == min(metadata["n_rows_total"], background.shape[0])
    assert len(background) <= metadata["n_rows_total"]


def test_load_background_is_scoped_when_nothing_trained_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(train_module, "RECOMMENDATION_ARTIFACTS_DIR", tmp_path)

    assert train_module.load_background("T20", "male") is None

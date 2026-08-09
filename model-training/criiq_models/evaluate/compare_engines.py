"""does hyperparameter-tuning + ensembling the wpa regressors actually beat
the model that's been feeding the existing MILP-based selection pipeline?

two independent, honest checks:

1. regression_backtest_comparison -- the same temporal split
   evaluate/backtest.py uses (by match date, never by row, since same-match
   rows are correlated). baseline/tuned/ensemble are all freshly fit on the
   train side only inside this function -- tuning itself only ever sees
   train_df, so no hyperparameter search can leak test-period matches into
   the reported numbers.

2. xi_overlap_comparison -- the stronger, pipeline-level check: how often
   does each engine's scores, run through the *unchanged* MILP selector
   (selection/optimize.select_xi), pick the real, actually-fielded XI on
   matches_holdout -- a genuinely unseen forward holdout none of the
   persisted artifacts trained on (same methodology as
   model_evaluation_suite.ipynb Part B / VALIDATION_REPORT.md 11/14). this
   one legitimately uses the persisted artifacts, since matches_holdout was
   never part of any of their training data.
"""
from __future__ import annotations

import random
import sqlite3

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.base import clone
from sklearn.metrics import r2_score, root_mean_squared_error

from ..config import SETTINGS
from ..features.historical import build_training_table
from ..features.schema import MODEL_FEATURES, TARGETS
from ..recommend.ensemble import AveragedRegressor, build_ensemble_models
from ..recommend.rank_select import load_ranker, load_ranker_metadata, select_xi_by_model
from ..recommend.score import RecommendationScorer
from ..recommend.train import _clip_target, _make_model, load_models
from ..recommend.tune import load_tuned_metadata, load_tuned_models, tune_target
from ..roster import _player_id_map, team_pool
from ..selection.optimize import select_xi
from .backtest import _top_quartile_hit_rate


def _fit_variant(train_rows: pd.DataFrame, target: str, gender: str, best_params: dict | None = None):
    model = clone(_make_model(target, gender))
    if best_params:
        model.set_params(**best_params)
    model.fit(train_rows[MODEL_FEATURES], _clip_target(train_rows[target]))
    return model


def _eval_variant(model, test_rows: pd.DataFrame, target: str) -> dict:
    """the full metric set model_evaluation_suite.ipynb's Part A reports for
    a WPA regressor -- MAE/RMSE/R2, Pearson + Spearman correlation, sign
    agreement, and the within-match top-quartile hit rate -- so a tuned or
    ensembled variant is judged the same way the shipped baseline already is.
    """
    pred = model.predict(test_rows[MODEL_FEATURES])
    actual = test_rows[target].to_numpy()
    corr = float(np.corrcoef(pred, actual)[0, 1]) if len(pred) > 1 else None
    spearman = float(spearmanr(pred, actual).statistic) if len(pred) > 1 else None
    scored = test_rows.copy()
    scored["_pred"] = pred
    return {
        "mae": round(float(np.mean(np.abs(pred - actual))), 4),
        "rmse": round(float(root_mean_squared_error(actual, pred)), 4),
        "r2": round(float(r2_score(actual, pred)), 4),
        "corr_pred_vs_actual": round(corr, 3) if corr is not None else None,
        "spearman_pred_vs_actual": round(spearman, 3) if spearman is not None else None,
        "sign_agreement_accuracy": round(float(np.mean(np.sign(pred) == np.sign(actual))), 3),
        "top_quartile_hit_rate_within_match": _top_quartile_hit_rate(scored, target),
    }


def regression_backtest_comparison(conn: sqlite3.Connection, fmt: str = SETTINGS.format,
                                    gender: str = SETTINGS.gender, n_iter: int = 25) -> dict:
    table = build_training_table(conn, fmt, gender)
    if table.empty:
        return {"note": "no training data"}

    dates = pd.to_datetime(table["date"])
    cutoff = dates.quantile(1 - SETTINGS.backtest_test_fraction)
    train_df, test_df = table[dates < cutoff], table[dates >= cutoff]

    report = {"cutoff_date": str(cutoff.date()), "n_train_rows": int(len(train_df)),
              "n_test_rows": int(len(test_df)), "targets": {}}

    for target in TARGETS:
        train_rows = train_df.dropna(subset=[target])
        test_rows = test_df.dropna(subset=[target]).copy()
        if len(train_rows) < 100 or test_rows.empty:
            report["targets"][target] = {"note": "insufficient data for a temporal holdout"}
            continue

        tune_report = tune_target(train_df, target, gender, n_iter=n_iter)
        baseline_model = _fit_variant(train_rows, target, gender)

        target_report = {"tuning": tune_report, "baseline": _eval_variant(baseline_model, test_rows, target)}
        if "best_params" in tune_report:
            tuned_model = _fit_variant(train_rows, target, gender, tune_report["best_params"])
            ensemble_model = AveragedRegressor([baseline_model, tuned_model])
            target_report["tuned"] = _eval_variant(tuned_model, test_rows, target)
            target_report["ensemble"] = _eval_variant(ensemble_model, test_rows, target)
        report["targets"][target] = target_report

    return report


def _resolve_name_fn(conn: sqlite3.Connection):
    ident_by_name = {r["player_name"]: r["identifier"] for r in
                      conn.execute("SELECT player_name, identifier FROM identifier_map")}
    unambiguous, split_map = _player_id_map(conn)

    def resolve(name: str, gender: str) -> str | None:
        ident = ident_by_name.get(name)
        if ident is None:
            return None
        return unambiguous.get(ident) or split_map.get((ident, gender))

    return resolve


def _actual_xi(conn: sqlite3.Connection, resolve, match_id: str, team: str, gender: str) -> list[str]:
    names = [r["player_name"] for r in conn.execute(
        "SELECT player_name FROM match_players_holdout WHERE match_id=? AND team=?", (match_id, team))]
    ids = [resolve(n, gender) for n in names]
    return [i for i in ids if i]


def xi_overlap_comparison(conn: sqlite3.Connection, fmt: str = SETTINGS.format,
                           gender: str = SETTINGS.gender, limit: int = 40,
                           seed: int = SETTINGS.random_state) -> dict:
    """real-world overlap with the actually-fielded XI, per engine, on
    matches_holdout. "tuned"/"ensemble" columns are omitted (with a note)
    until `tune` has been run at least once for this (fmt, gender) scope.
    """
    baseline_models = load_models(fmt, gender)
    if not baseline_models:
        return {"note": "no persisted production models -- run `train` first"}

    engines = {"baseline": baseline_models}
    if load_tuned_metadata(fmt, gender) is not None:
        tuned_models = load_tuned_models(fmt, gender)
        if tuned_models:
            engines["tuned"] = tuned_models
            engines["ensemble"] = build_ensemble_models(fmt, gender)
    else:
        engines["_note"] = "tuned/ensemble omitted -- run `tune` first to compare them"

    scorers = {name: RecommendationScorer(conn, fmt, gender, models=models)
               for name, models in engines.items() if name != "_note"}

    # the model-driven selector (recommend/rank_select.py): the fine-tuned
    # ranker itself picks the top 11/20, no MILP involved at all -- compared
    # here against the score-then-MILP engines above on the identical
    # holdout matches.
    ranker = load_ranker(fmt, gender)
    ranker_metadata = load_ranker_metadata(fmt, gender)
    ranker_note = None
    if ranker is None or not ranker_metadata or "role_categories" not in ranker_metadata:
        ranker_note = "model_ranker omitted -- run `tune-ranker` first to compare it"
    role_categories = ranker_metadata.get("role_categories") if ranker_metadata else None

    resolve = _resolve_name_fn(conn)
    holdout_matches = pd.read_sql_query(
        "SELECT match_id, team1, team2, venue_id FROM matches_holdout WHERE gender=? "
        "ORDER BY match_id LIMIT ?", conn, params=(gender, limit))

    rng = random.Random(seed)
    overlap_rows = []
    for _, m in holdout_matches.iterrows():
        for team, opponent in ((m.team1, m.team2), (m.team2, m.team1)):
            actual_ids = _actual_xi(conn, resolve, m.match_id, team, gender)
            if len(actual_ids) < 10:
                continue
            pool = team_pool(conn, team, fmt, gender)
            if len(pool) < 11:
                continue
            row = {"team": team, "opponent": opponent,
                   "random_baseline": np.mean([len(set(rng.sample(pool, 11)) & set(actual_ids))
                                                for _ in range(100)])}
            for name, scorer in scorers.items():
                scored = scorer.score_many(pool, opponent, venue_id=m.venue_id)
                result = select_xi(scored)
                xi_ids = {p["player_id"] for p in result["xi"]}
                pool20_ids = {p["player_id"] for p in result["pool"]}
                row[f"{name}_overlap"] = len(xi_ids & set(actual_ids))
                # top-20 recall: what fraction of the real fielded XI would a
                # coach still have found in the shortlist, not just the picked 11.
                row[f"{name}_pool20_recall"] = len(pool20_ids & set(actual_ids)) / len(actual_ids)
            if ranker is not None and role_categories is not None:
                model_result = select_xi_by_model(conn, ranker, role_categories, pool, opponent, fmt,
                                                   venue_id=m.venue_id)
                model_xi_ids = {p["player_id"] for p in model_result["xi"]}
                model_pool20_ids = {p["player_id"] for p in model_result["pool"]}
                row["model_ranker_overlap"] = len(model_xi_ids & set(actual_ids))
                row["model_ranker_pool20_recall"] = len(model_pool20_ids & set(actual_ids)) / len(actual_ids)
                row["model_ranker_batting_capable"] = model_result["role_balance"]["batting_capable"]
                row["model_ranker_bowling_capable"] = model_result["role_balance"]["bowling_capable"]
            overlap_rows.append(row)

    overlap_df = pd.DataFrame(overlap_rows)
    if overlap_df.empty:
        return {"note": "no comparable holdout matches resolved"}

    summary = {"n_comparisons": len(overlap_df),
               "random_baseline_mean": round(float(overlap_df["random_baseline"].mean()), 3)}
    for name in engines:
        col = f"{name}_overlap"
        if col in overlap_df:
            mean_overlap = float(overlap_df[col].mean())
            summary[name] = {"mean_overlap_of_11": round(mean_overlap, 3),
                              "mean_overlap_pct": round(100 * mean_overlap / 11, 1),
                              "mean_pool20_recall": round(float(overlap_df[f"{name}_pool20_recall"].mean()), 3)}
    if "model_ranker_overlap" in overlap_df:
        mean_overlap = float(overlap_df["model_ranker_overlap"].mean())
        # role-balance violation: fewer than the MILP's own min_batting/bowling_capable
        # floor among the model's unconstrained top-11 -- the cost the MILP step exists
        # to eliminate, made visible instead of assumed away.
        violations = (overlap_df["model_ranker_batting_capable"] < SETTINGS.min_batting_capable) | \
                     (overlap_df["model_ranker_bowling_capable"] < SETTINGS.min_bowling_capable)
        summary["model_ranker"] = {
            "mean_overlap_of_11": round(mean_overlap, 3),
            "mean_overlap_pct": round(100 * mean_overlap / 11, 1),
            "mean_pool20_recall": round(float(overlap_df["model_ranker_pool20_recall"].mean()), 3),
            "role_balance_violation_rate": round(float(violations.mean()), 3),
        }
    if "_note" in engines:
        summary["note"] = engines["_note"]
    if ranker_note:
        summary["model_ranker_note"] = ranker_note

    return {"summary": summary, "rows": overlap_df.to_dict(orient="records")}


def compare_engines(conn: sqlite3.Connection, fmt: str = SETTINGS.format, gender: str = SETTINGS.gender,
                     n_iter: int = 25, holdout_limit: int = 40) -> dict:
    return {
        "regression_backtest": regression_backtest_comparison(conn, fmt, gender, n_iter=n_iter),
        "xi_overlap_vs_real_history": xi_overlap_comparison(conn, fmt, gender, limit=holdout_limit),
    }

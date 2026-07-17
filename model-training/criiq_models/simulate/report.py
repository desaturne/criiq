"""Charts + artifact persistence for simulated matches.

Mirrors the `data/features/*.parquet` + `*_meta.json` persistence pattern
`data-collection/criiq_data/winprob.py` already uses, under this package's
own `artifacts/simulation/` directory (sibling to the existing
`artifacts/{match_result,player_recommendation,win_prob}` dirs).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
# Force a headless-safe backend for the CLI (no display server to assume),
# but never override a Jupyter kernel's own backend (`%matplotlib inline` or
# the auto-configured inline backend) -- unconditionally calling `use("Agg")`
# here previously clobbered that whenever this module was imported inside a
# notebook cell, silently breaking `plt.show()` (a real bug found live: charts
# stopped rendering in `simulation_demo.ipynb` with a "FigureCanvasAgg is
# non-interactive" warning, even after adding the `%matplotlib inline` magic,
# because this import ran afterward in the same cell and switched the backend
# back). `ipykernel` is only ever imported when running inside a Jupyter
# kernel, never a plain CLI invocation, so it's a reliable signal here.
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ..config import ARTIFACTS_DIR

SIMULATION_ARTIFACTS_DIR = ARTIFACTS_DIR / "simulation"

_MOMENT_MARKERS = {
    "batting_milestone": ("o", "tab:blue"),
    "boundary": (".", "tab:gray"),
    "bowling_milestone": ("^", "tab:red"),
    "hat_trick": ("*", "tab:purple"),
    "turning_point": ("D", "tab:orange"),
}


def _concat_match_log(rep: dict) -> pd.DataFrame:
    """Both innings' ball logs, concatenated with a continuous x-axis
    (`match_ball_index`) and the win probability re-expressed as the
    `batting_first_team`'s win probability throughout, so the chart reads as
    one continuous story rather than flipping perspective at the innings
    break.
    """
    log1 = rep["first_innings_log"].copy()
    log2 = rep["second_innings_log"].copy()
    log1["win_prob_team1_perspective"] = log1["win_prob_batting"]
    log2["win_prob_team1_perspective"] = 1.0 - log2["win_prob_batting"]
    combined = pd.concat([log1, log2], ignore_index=True)
    combined["match_ball_index"] = range(len(combined))
    return combined


def plot_win_probability(rep: dict, out_path: str | Path, scenario_rep: dict | None = None,
                          key_moments: list | None = None) -> Path:
    """Ball-by-ball win-probability line chart for `batting_first_team`.
    `scenario_rep` (e.g. a forced-dismissal run from `engine.simulate_match`)
    overlays a second trace for direct comparison. `key_moments` (from
    `keymoments.detect_key_moments`) annotates fifties/centuries/wickets/
    hat-tricks/boundaries and the biggest win-probability swings.
    """
    combined = _concat_match_log(rep)
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(combined["match_ball_index"], combined["win_prob_team1_perspective"] * 100,
            label=f"{rep['batting_first_team']} win probability", color="tab:blue", linewidth=1.5)

    if scenario_rep is not None:
        scenario_combined = _concat_match_log(scenario_rep)
        ax.plot(scenario_combined["match_ball_index"],
                scenario_combined["win_prob_team1_perspective"] * 100,
                label="scenario (forced dismissal)", color="tab:red", linewidth=1.5, linestyle="--")

    innings_break = len(rep["first_innings_log"])
    ax.axvline(innings_break, color="black", linestyle=":", linewidth=1)
    ax.axhline(50, color="gray", linestyle=":", linewidth=0.8)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Ball (match sequence)")
    ax.set_ylabel(f"{rep['batting_first_team']} win probability (%)")
    ax.set_title(f"{rep['batting_first_team']} vs {rep['bowling_first_team']} -- win probability")

    if key_moments:
        seen_types = set()
        for m in key_moments:
            marker, color = _MOMENT_MARKERS.get(m["type"], ("x", "black"))
            offset = 0 if m["innings"] == 1 else innings_break
            # over/ball -> approximate position within that innings' log
            idx = offset + (m["over"] * 6 + m["ball"] - 1)
            idx = max(0, min(idx, len(combined) - 1))
            y = combined.iloc[idx]["win_prob_team1_perspective"] * 100
            label = m["type"] if m["type"] not in seen_types else None
            seen_types.add(m["type"])
            ax.scatter([idx], [y], marker=marker, color=color, s=60, zorder=5, label=label)

    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def save_simulation_artifacts(rep: dict, out_dir: str | Path, key_moments: list | None = None,
                               ga_history: dict | None = None) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    combined = _concat_match_log(rep)
    ball_log_path = out_dir / "ball_log.parquet"
    combined.to_parquet(ball_log_path, index=False)

    summary = {
        "batting_first_team": rep["batting_first_team"], "bowling_first_team": rep["bowling_first_team"],
        "first_innings_score": rep["first_innings_score"], "first_innings_wickets": rep["first_innings_wickets"],
        "second_innings_score": rep["second_innings_score"], "second_innings_wickets": rep["second_innings_wickets"],
        "target": rep["target"], "winner": rep["winner"],
        "super_over_rounds": [
            {k: v for k, v in so.items() if k not in ("bat_first_log", "bowl_first_log")}
            for so in rep.get("super_over_rounds", [])
        ],
        "key_moments": key_moments or [],
    }
    if ga_history is not None:
        summary["ga_history"] = ga_history
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    return {"ball_log_path": str(ball_log_path), "summary_path": str(summary_path)}


def aggregate_win_probability(reps: list) -> pd.DataFrame:
    """Mean + 10th/90th percentile win-probability band across Monte Carlo
    `reps` (from `engine.simulate_match(..., n_reps=N)`), aligned by ball
    index within each innings. Reps that end early (all-out or chase won
    before ball 120) hold their final win probability flat for the remaining
    balls -- the outcome is already effectively decided by that point.
    """
    frames = []
    for rep in reps:
        combined = _concat_match_log(rep)
        frames.append(combined[["match_ball_index", "win_prob_team1_perspective"]])

    max_len = max(len(f) for f in frames)
    padded = []
    for f in frames:
        f = f.set_index("match_ball_index").reindex(range(max_len))
        f["win_prob_team1_perspective"] = f["win_prob_team1_perspective"].ffill()
        padded.append(f["win_prob_team1_perspective"].to_numpy())

    arr = np.array(padded)
    return pd.DataFrame({
        "match_ball_index": range(max_len),
        "mean": arr.mean(axis=0),
        "p10": np.percentile(arr, 10, axis=0),
        "p90": np.percentile(arr, 90, axis=0),
    })

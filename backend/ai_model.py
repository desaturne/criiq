"""
ai_model.py — the REAL AI, wired in to replace ai_stub.

The recommendation engine (`model-training/criiq_models`) and the win-probability
model (`data-collection/criiq_data`) each live in their OWN folder with their own
virtualenv and their own (heavy, pinned) dependencies — numpy/scikit-learn for the
model, pandas/pyarrow for the pipeline. Rather than cram all of that into the
backend's environment, the backend calls each one as a subprocess: we run its CLI
with its own Python, and it prints JSON to stdout, which we parse here.

Both functions keep the EXACT SAME return shape as the old ai_stub, so nothing
downstream (selection.py, matches.py, the frontend) has to change. If a subprocess
fails for any reason — model not trained yet, a bad argument, a timeout — we fall
back to ai_stub so the API always answers instead of erroring.
"""

import json
import subprocess
from pathlib import Path

import ai_stub  # graceful fallback

# The three sibling folders, located relative to this file (backend/ai_model.py).
CRIIQ_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = CRIIQ_ROOT / "model-training"
DATA_DIR = CRIIQ_ROOT / "data-collection"
MODEL_PY = MODEL_DIR / ".venv" / "bin" / "python"
DATA_PY = DATA_DIR / ".venv" / "bin" / "python"

TIMEOUT_SECONDS = 90  # the recommendation model loads + scores a full pool


def _run_json(python: Path, cwd: Path, args: list[str]) -> dict | list:
    """Run a CLI subcommand that prints JSON, and return the parsed object.
    Raises on any failure so the callers can fall back to the stub."""
    proc = subprocess.run(
        [str(python), "-m", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[-400:] or "subprocess failed")
    # The CLI may print a log line or two before the JSON; parse from the first
    # '{' so a stray banner never breaks us.
    text = proc.stdout
    start = text.find("{")
    if start == -1:
        raise RuntimeError("no JSON in output")
    return json.loads(text[start:])


# --------------------------------------------------------------------------
# Recommendations — real player-recommendation engine (criiq_models)
# --------------------------------------------------------------------------
def get_recommendations(match_context: dict) -> list[dict]:
    """
    match_context = {"team": "India", "opponent": "Australia",
                     "venue": "Wankhede", "gender": "female", "format": "T20I"}
    Returns the ranked shortlist in the stub's shape:
        [{"rank", "player_name", "role", "score", "reason"}, ...]
    """
    team = match_context.get("team") or "India"
    opponent = match_context.get("opponent", "Australia")
    venue = match_context.get("venue")
    gender = match_context.get("gender") or "female"

    args = ["criiq_models.cli", "recommend",
            "--team", team, "--opponent", opponent,
            "--gender", gender, "--format", "T20", "--explain"]
    if venue:
        args += ["--venue", venue]

    try:
        result = _run_json(MODEL_PY, MODEL_DIR, args)
        pool = result.get("pool", [])
        recs = []
        for i, p in enumerate(pool, start=1):
            reasoning = p.get("reasoning")
            # reasoning is a list of sentences; the first two make a tidy one-liner
            if isinstance(reasoning, list):
                reason = " ".join(reasoning[:2])
            else:
                reason = reasoning or ""
            recs.append({
                "rank": i,
                "player_name": p.get("name"),
                "role": p.get("role_bucket"),
                "score": round(p.get("score", 0), 1),
                "reason": reason,
                "player_id": p.get("player_id"),   # extra, harmless to the frontend
                "in_xi": False,
            })
        # tag the players who made the final constrained XI
        xi_ids = {p.get("player_id") for p in result.get("xi", [])}
        for r in recs:
            r["in_xi"] = r["player_id"] in xi_ids
        if recs:
            return recs
    except Exception as exc:  # model not trained, bad team name, timeout, ...
        print(f"[ai_model] recommendations fell back to stub: {exc}")
    return ai_stub.get_recommendations(match_context)


# --------------------------------------------------------------------------
# Win probability — real empirical model (criiq_data)
# --------------------------------------------------------------------------
def get_win_probability(state: dict) -> dict:
    """
    state = {"innings": 2, "balls_remaining": 30, "wickets": 4,
             "runs_required": 40, "gender": "female"}
    Returns the stub's shape:
        {"win_probability_batting", "win_probability_bowling", "phase", "model"}
    """
    gender = state.get("gender") or "female"
    parts = [f"innings={int(state.get('innings', 1))}",
             f"balls_remaining={int(state.get('balls_remaining', 120))}",
             f"wickets={int(state.get('wickets', 0))}"]
    if state.get("runs_required") is not None:
        parts.append(f"runs_required={int(state['runs_required'])}")
    state_arg = ",".join(parts)

    args = ["criiq_data.cli", "winprob", "--state", state_arg,
            "--gender", gender, "--format", "T20"]
    try:
        result = _run_json(DATA_PY, DATA_DIR, args)
        bat = result.get("win_prob_batting")
        if bat is not None:
            balls_remaining = int(state.get("balls_remaining", 120))
            over = (120 - balls_remaining) // 6
            phase = "powerplay" if over < 6 else ("middle" if over < 16 else "death")
            return {
                "win_probability_batting": round(bat, 3),
                "win_probability_bowling": round(result.get("win_prob_bowling", 1 - bat), 3),
                "phase": phase,
                "model": "empirical",   # the real model, not "stub"
            }
    except Exception as exc:
        print(f"[ai_model] win probability fell back to stub: {exc}")
    return ai_stub.get_win_probability(state)

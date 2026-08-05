"""model_bridge.py — calls criiq_models via subprocess (its ML deps stay out of this venv)."""

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent
MODEL_TRAINING_DIR = Path(os.environ.get("MODEL_TRAINING_DIR", BACKEND_DIR.parent / "model-training"))


def _default_model_training_python() -> str:
    """Falls back to model-training's own .venv, then this process's interpreter."""
    for candidate in (
        MODEL_TRAINING_DIR / ".venv" / "Scripts" / "python.exe",
        MODEL_TRAINING_DIR / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


MODEL_TRAINING_PYTHON = os.environ.get("MODEL_TRAINING_PYTHON") or _default_model_training_python()

DEFAULT_FORMAT = "T20"
DEFAULT_GENDER = "female"

# criiq.db and the artifact scopes (artifacts/player_recommendation/<gender>_T20)
# only ever use "T20", but callers naturally write "T20I" for the international
# flavour -- and the UI's own format selector is labelled "T20I". Passing that
# through unchanged makes every model call fall back to an empty roster, so
# normalize once here, where every entry point below already funnels through.
_FORMAT_ALIASES = {"t20": "T20", "t20i": "T20"}


def normalize_format(fmt: str | None) -> str:
    if not fmt:
        return DEFAULT_FORMAT
    fmt = fmt.strip()
    return _FORMAT_ALIASES.get(fmt.lower(), fmt)


class ModelBridgeError(Exception):
    """criiq_models CLI exited without usable JSON; message is whatever it printed."""


def run_cli(args: list[str], timeout: int = 120) -> dict:
    cmd = [MODEL_TRAINING_PYTHON, "-m", "criiq_models.cli", *args]
    try:
        proc = subprocess.run(cmd, cwd=MODEL_TRAINING_DIR, capture_output=True,
                               text=True, encoding="utf-8", timeout=timeout)
    except FileNotFoundError as exc:
        raise ModelBridgeError(f"model-training interpreter not found ({MODEL_TRAINING_PYTHON}): {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ModelBridgeError(f"criiq_models {args[0]} timed out after {timeout}s") from exc

    output = proc.stdout.strip()
    try:
        return json.loads(output)
    except (json.JSONDecodeError, ValueError) as exc:
        message = output or proc.stderr.strip() or f"criiq_models {args[0]} exited {proc.returncode} with no output"
        raise ModelBridgeError(message) from exc


def _opt(flag: str, value) -> list[str]:
    return [flag, str(value)] if value not in (None, "") else []


def recommend(team: str, opponent: str, venue: str | None = None,
              fmt: str = DEFAULT_FORMAT, gender: str = DEFAULT_GENDER,
              opponent_player_ids: list[str] | None = None) -> dict:
    args = ["recommend", "--team", team, "--opponent", opponent, "--format", normalize_format(fmt),
            "--gender", gender, "--explain", *_opt("--venue", venue)]
    if opponent_player_ids:
        args += ["--opponent-player-ids", ",".join(opponent_player_ids)]
    return run_cli(args)


def winprob(innings: int, wickets: int = 0, balls_remaining: int | None = None,
            runs_required: int | None = None, fmt: str = DEFAULT_FORMAT, gender: str = DEFAULT_GENDER) -> dict:
    args = ["winprob", "--innings", str(innings), "--wickets", str(wickets),
            "--format", normalize_format(fmt), "--gender", gender,
            *_opt("--balls-remaining", balls_remaining), *_opt("--runs-required", runs_required)]
    return run_cli(args)


# player_ids, not names -- names can be ambiguous (e.g. two "A Reddy"s).
def analyze_xi(team: str, opponent: str, player_ids: list[str], venue: str | None = None,
               fmt: str = DEFAULT_FORMAT, gender: str = DEFAULT_GENDER) -> dict:
    args = ["analyze-xi", "--team", team, "--opponent", opponent, "--format", normalize_format(fmt),
            "--gender", gender, "--player-ids", ",".join(player_ids), "--explain", *_opt("--venue", venue)]
    return run_cli(args)


# One player at a time (the "explain" subcommand), so a coach expanding one card's SHAP doesn't cost the whole pool.
def explain_player(player_id: str, opponent: str, venue: str | None = None,
                   fmt: str = DEFAULT_FORMAT, gender: str = DEFAULT_GENDER) -> dict:
    args = ["explain", "--player-id", player_id, "--opponent", opponent, "--format", normalize_format(fmt),
            "--gender", gender, "--shap", *_opt("--venue", venue)]
    return run_cli(args)


def simulate(team1: str, team2: str, team1_player_ids: list[str], team2_player_ids: list[str], toss_winner: str,
             n_simulations: int = 20, venue: str | None = None, force_dismissal: str | None = None,
             fmt: str = DEFAULT_FORMAT, gender: str = DEFAULT_GENDER) -> dict:
    args = ["simulate", "--team1", team1, "--team2", team2,
            "--team1-player-ids", ",".join(team1_player_ids), "--team2-player-ids", ",".join(team2_player_ids),
            "--toss-winner", toss_winner, "--n-simulations", str(n_simulations),
            "--format", normalize_format(fmt), "--gender", gender, "--json",
            *_opt("--venue", venue), *_opt("--force-dismissal", force_dismissal)]
    return run_cli(args, timeout=300)


# The CLI's own --pop-size/--generations defaults (40/60) are tuned for an
# offline notebook run, not a synchronous HTTP request -- with the GA's
# default n_reps=8, that's ~19,200 full ball-by-ball innings simulations
# (pop_size * generations * n_reps, plus re-verification passes on every new
# best), measured at 10+ minutes for a live matchup. pop_size=16/generations=
# 20 (~19s measured for the same matchup) is the default here instead; a
# caller can still ask for a deeper search via the pop_size/generations args.
FAST_POP_SIZE = 16
FAST_GENERATIONS = 20


def optimize_bowling(bowling_team: str, batting_team: str, bowling_player_ids: list[str], batting_player_ids: list[str],
                      venue: str | None = None, pop_size: int = FAST_POP_SIZE, generations: int = FAST_GENERATIONS,
                      fmt: str = DEFAULT_FORMAT, gender: str = DEFAULT_GENDER) -> dict:
    args = ["optimize-bowling", "--bowling-team", bowling_team, "--batting-team", batting_team,
            "--bowling-player-ids", ",".join(bowling_player_ids), "--batting-player-ids", ",".join(batting_player_ids),
            "--format", normalize_format(fmt), "--gender", gender, "--json", "--explain",
            "--pop-size", str(pop_size), "--generations", str(generations),
            *_opt("--venue", venue)]
    return run_cli(args, timeout=300)


def optimize_batting(batting_team: str, bowling_team: str, batting_player_ids: list[str], bowling_player_ids: list[str],
                      target: int | None = None, venue: str | None = None,
                      pop_size: int = FAST_POP_SIZE, generations: int = FAST_GENERATIONS,
                      fmt: str = DEFAULT_FORMAT, gender: str = DEFAULT_GENDER) -> dict:
    args = ["optimize-batting", "--batting-team", batting_team, "--bowling-team", bowling_team,
            "--batting-player-ids", ",".join(batting_player_ids), "--bowling-player-ids", ",".join(bowling_player_ids),
            "--format", normalize_format(fmt), "--gender", gender, "--json", "--explain",
            "--pop-size", str(pop_size), "--generations", str(generations),
            *_opt("--target", target), *_opt("--venue", venue)]
    return run_cli(args, timeout=300)

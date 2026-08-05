"""simulation.py — match simulation, GA optimizers, and XI analysis. No fake-data fallback: errors surface as 422."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import model_bridge
import players
from auth import require_user

router = APIRouter(tags=["simulation"], dependencies=[Depends(require_user)])


def _reject_retired(player_ids: list[str], fmt: str) -> None:
    # These endpoints accept player_ids directly, so re-validate rather than
    # trust that the caller only ever got them from the filtered /players list.
    retired = players.retired_names(player_ids, fmt)
    if retired:
        names = ", ".join(sorted(retired.values()))
        raise HTTPException(422, f"Retired player(s) cannot be selected: {names}")


def _run(fn, /, *args, **kwargs) -> dict:
    try:
        return fn(*args, **kwargs)
    except model_bridge.ModelBridgeError as exc:
        raise HTTPException(422, str(exc))


# --------------------------------------------------------------------------
# POST /analyze-xi — score + check a coach's own hand-picked XI
# --------------------------------------------------------------------------
class AnalyzeXiBody(BaseModel):
    team: str
    opponent: str = Field(min_length=2)
    player_ids: list[str] = Field(min_length=11, max_length=11)
    venue: str | None = None
    format: str = "T20"
    gender: str = "female"


@router.post("/analyze-xi")
def analyze_xi(body: AnalyzeXiBody):
    _reject_retired(body.player_ids, model_bridge.normalize_format(body.format))
    result = _run(model_bridge.analyze_xi, team=body.team, opponent=body.opponent,
                  player_ids=body.player_ids, venue=body.venue, fmt=body.format, gender=body.gender)
    return {"data": result, "error": None}


# --------------------------------------------------------------------------
# POST /simulate — ball-by-ball Monte Carlo match simulation
# --------------------------------------------------------------------------
class SimulateBody(BaseModel):
    team1: str
    team2: str
    team1_player_ids: list[str] = Field(min_length=11, max_length=11)
    team2_player_ids: list[str] = Field(min_length=11, max_length=11)
    toss_winner: str
    n_simulations: int = Field(default=20, ge=1, le=200)
    venue: str | None = None
    force_dismissal: str | None = None
    format: str = "T20"
    gender: str = "female"


@router.post("/simulate")
def simulate(body: SimulateBody):
    if body.toss_winner not in (body.team1, body.team2):
        raise HTTPException(400, "toss_winner must equal team1 or team2")
    fmt = model_bridge.normalize_format(body.format)
    _reject_retired(body.team1_player_ids + body.team2_player_ids, fmt)
    result = _run(model_bridge.simulate, team1=body.team1, team2=body.team2,
                  team1_player_ids=body.team1_player_ids, team2_player_ids=body.team2_player_ids,
                  toss_winner=body.toss_winner, n_simulations=body.n_simulations,
                  venue=body.venue, force_dismissal=body.force_dismissal,
                  fmt=body.format, gender=body.gender)
    return {"data": result, "error": None}


# --------------------------------------------------------------------------
# POST /optimize-bowling — GA search over legal bowler-to-over rotations
# --------------------------------------------------------------------------
class OptimizeBowlingBody(BaseModel):
    bowling_team: str
    batting_team: str
    bowling_player_ids: list[str] = Field(min_length=11, max_length=11)
    batting_player_ids: list[str] = Field(min_length=11, max_length=11)
    venue: str | None = None
    # Fast defaults (~19s measured) -- raise for a deeper, slower search.
    pop_size: int = Field(default=model_bridge.FAST_POP_SIZE, ge=4, le=60)
    generations: int = Field(default=model_bridge.FAST_GENERATIONS, ge=5, le=80)
    format: str = "T20"
    gender: str = "female"


@router.post("/optimize-bowling")
def optimize_bowling(body: OptimizeBowlingBody):
    fmt = model_bridge.normalize_format(body.format)
    _reject_retired(body.bowling_player_ids + body.batting_player_ids, fmt)
    result = _run(model_bridge.optimize_bowling, bowling_team=body.bowling_team,
                  batting_team=body.batting_team, bowling_player_ids=body.bowling_player_ids,
                  batting_player_ids=body.batting_player_ids, venue=body.venue,
                  pop_size=body.pop_size, generations=body.generations,
                  fmt=body.format, gender=body.gender)
    return {"data": result, "error": None}


# --------------------------------------------------------------------------
# POST /optimize-batting — GA search over batting order
# --------------------------------------------------------------------------
class OptimizeBattingBody(BaseModel):
    batting_team: str
    bowling_team: str
    batting_player_ids: list[str] = Field(min_length=11, max_length=11)
    bowling_player_ids: list[str] = Field(min_length=11, max_length=11)
    target: int | None = None
    venue: str | None = None
    pop_size: int = Field(default=model_bridge.FAST_POP_SIZE, ge=4, le=60)
    generations: int = Field(default=model_bridge.FAST_GENERATIONS, ge=5, le=80)
    format: str = "T20"
    gender: str = "female"


@router.post("/optimize-batting")
def optimize_batting(body: OptimizeBattingBody):
    fmt = model_bridge.normalize_format(body.format)
    _reject_retired(body.batting_player_ids + body.bowling_player_ids, fmt)
    result = _run(model_bridge.optimize_batting, batting_team=body.batting_team,
                  bowling_team=body.bowling_team, batting_player_ids=body.batting_player_ids,
                  bowling_player_ids=body.bowling_player_ids, target=body.target, venue=body.venue,
                  pop_size=body.pop_size, generations=body.generations,
                  fmt=body.format, gender=body.gender)
    return {"data": result, "error": None}

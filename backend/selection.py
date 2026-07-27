"""
selection.py — Playing XI save/load + the AI endpoints (Phase 4).

Squad selections are OUR data, so they live in app.db.
Recommendations and win probability call ai_stub — the teammate's real model
will replace that module later with the same function signatures.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import ai_stub  # calls the real model via model_bridge, falls back to stub data
from auth import require_user
from database import app_db

router = APIRouter(tags=["selection"], dependencies=[Depends(require_user)])


# --------------------------------------------------------------------------
# 15. GET + PUT /selection/{match_id} — the Playing XI panel
# --------------------------------------------------------------------------
class SelectionBody(BaseModel):
    xi: list[str] = []          # the Playing XI (max 11 player ids)
    extra: list[str] = []       # reserves / bench
    excluded: list[str] = []    # explicitly ruled out


@router.get("/selection/{match_id}")
def get_selection(match_id: str):
    row = app_db.execute(
        "SELECT squad_json, updated_at FROM selections WHERE match_id = ?",
        (match_id,),
    ).fetchone()
    if not row:
        # no squad saved yet -> empty lists, not an error
        return {"data": {"match_id": match_id, "xi": [], "extra": [],
                         "excluded": [], "updated_at": None}, "error": None}
    squad = json.loads(row["squad_json"])
    return {"data": {"match_id": match_id, **squad,
                     "updated_at": row["updated_at"]}, "error": None}


@router.put("/selection/{match_id}")
def save_selection(match_id: str, body: SelectionBody):
    if len(body.xi) > 11:
        raise HTTPException(400, f"The XI has {len(body.xi)} players — maximum is 11")

    everyone = body.xi + body.extra + body.excluded
    if len(everyone) != len(set(everyone)):
        raise HTTPException(400, "A player appears twice in the selection")

    squad_json = json.dumps(body.model_dump())
    app_db.execute(
        """INSERT INTO selections (match_id, squad_json, updated_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(match_id)
           DO UPDATE SET squad_json = excluded.squad_json,
                         updated_at = datetime('now')""",
        (match_id, squad_json),
    )
    app_db.commit()
    return {"data": {"match_id": match_id, **body.model_dump(),
                     "saved": True}, "error": None}


# --------------------------------------------------------------------------
# 16. POST /recommendations — ranked players for a match context
# --------------------------------------------------------------------------
class RecommendationBody(BaseModel):
    opponent: str = Field(min_length=2)
    venue: str | None = None
    team: str = "India"        # which side we are picking for
    gender: str = "female"     # "female" | "male"
    format: str = "T20I"
    auto_opponent_xi: bool = False   # also recommend the opponent's probable XI, and use it to activate player-vs-player head-to-head matchups


@router.post("/recommendations")
def recommendations(body: RecommendationBody):
    result = ai_stub.get_recommendations(body.model_dump())
    return {"data": {"match_context": body.model_dump(),
                     "recommendations": result["recommendations"],
                     "opponent_xi": result.get("opponent_xi")}, "error": None}


# --------------------------------------------------------------------------
# 17. GET /winprob — win probability for a game state
# --------------------------------------------------------------------------
@router.get("/winprob")
def winprob(innings: int = 1, balls_remaining: int = 120,
            wickets: int = 0, runs_required: int | None = None, gender: str = "female"):
    if not 1 <= innings <= 2:
        raise HTTPException(400, "innings must be 1 or 2")
    if not 0 <= wickets <= 10:
        raise HTTPException(400, "wickets must be 0–10")
    result = ai_stub.get_win_probability({
        "innings": innings, "balls_remaining": balls_remaining,
        "wickets": wickets, "runs_required": runs_required, "gender": gender,
    })
    return {"data": result, "error": None}

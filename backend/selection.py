"""
selection.py — Playing XI save/load + the AI endpoints (Phase 4).

Squad selections are OUR data, so they live in app.db.
Recommendations and win probability go through ai_stub, which calls the real
criiq_models engine via model_bridge (a subprocess, so its ML dependencies stay
out of this venv). The module keeps its original name and its hard-coded
fallbacks: those are only served if that subprocess is unreachable.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import ai_stub  # calls the real model via model_bridge, falls back to stub data
import model_bridge
import players
from auth import require_user
from database import app_db

router = APIRouter(tags=["selection"], dependencies=[Depends(require_user)])

# mirrors criiq_models' SETTINGS.xi_size; a named opposition XI must be a
# full XI, not a partial list.
SETTINGS_XI_SIZE = 11


def _reject_retired(player_ids: list[str], fmt: str = model_bridge.DEFAULT_FORMAT) -> None:
    retired = players.retired_names(player_ids, fmt)
    if retired:
        names = ", ".join(sorted(retired.values()))
        raise HTTPException(422, f"Retired player(s) cannot be selected: {names}")


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
    # Old rows can hold a since-retired player's id -- nothing else
    # re-validates a saved selection, so strip and persist the cleanup here.
    retired = players.retired_names(squad.get("xi", []) + squad.get("extra", []))
    if retired:
        squad["xi"] = [pid for pid in squad.get("xi", []) if pid not in retired]
        squad["extra"] = [pid for pid in squad.get("extra", []) if pid not in retired]
        app_db.execute(
            "UPDATE selections SET squad_json = ? WHERE match_id = ?",
            (json.dumps(squad), match_id),
        )
        app_db.commit()
    return {"data": {"match_id": match_id, **squad,
                     "updated_at": row["updated_at"]}, "error": None}


@router.put("/selection/{match_id}")
def save_selection(match_id: str, body: SelectionBody):
    if len(body.xi) > 11:
        raise HTTPException(400, f"The XI has {len(body.xi)} players — maximum is 11")

    everyone = body.xi + body.extra + body.excluded
    if len(everyone) != len(set(everyone)):
        raise HTTPException(400, "A player appears twice in the selection")
    # excluded is where a coach puts players ruled out on purpose, retirees
    # included -- only the actually-selectable lists need checking.
    _reject_retired(body.xi + body.extra)

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
    # "T20I" is accepted and normalized to "T20" by model_bridge; the default
    # matches simulation.py's so both AI route groups agree.
    format: str = "T20"
    auto_opponent_xi: bool = False   # also recommend the opponent's probable XI, and use it to activate player-vs-player head-to-head matchups
    # The opposition XI to pick against, named by the coach. When given, our
    # XI is chosen to counter exactly these players (real player-vs-player
    # matchup data) and auto_opponent_xi is ignored -- there is nothing left
    # to predict. player_ids, never names: a display name can be ambiguous.
    opponent_player_ids: list[str] | None = None


@router.post("/recommendations")
def recommendations(body: RecommendationBody):
    if body.opponent_player_ids is not None:
        ids = [pid for pid in body.opponent_player_ids if pid]
        if len(ids) != SETTINGS_XI_SIZE:
            raise HTTPException(
                400, f"opponent_player_ids must name exactly {SETTINGS_XI_SIZE} players "
                     f"(got {len(ids)}) — an XI is picked against a full opposition XI")
        if len(set(ids)) != len(ids):
            raise HTTPException(400, "opponent_player_ids lists the same player twice")
        # ai_stub.get_recommendations trusts these ids verbatim otherwise.
        _reject_retired(ids, model_bridge.normalize_format(body.format))

    result = ai_stub.get_recommendations(body.model_dump())
    return {"data": {"match_context": body.model_dump(),
                     "recommendations": result["recommendations"],
                     "opponent_xi": result.get("opponent_xi"),
                     "head_to_head": result.get("head_to_head"),
                     "countered_opponent_xi": result.get("countered_opponent_xi", False)},
            "error": None}


# --------------------------------------------------------------------------
# 17. GET /winprob — win probability for a game state
# --------------------------------------------------------------------------
@router.get("/winprob")
def winprob(innings: int = 1, balls_remaining: int = 120, wickets: int = 0,
            runs_required: int | None = None, gender: str = "female", format: str = "T20"):
    if not 1 <= innings <= 2:
        raise HTTPException(400, "innings must be 1 or 2")
    if not 0 <= wickets <= 10:
        raise HTTPException(400, "wickets must be 0–10")
    result = ai_stub.get_win_probability({
        "innings": innings, "balls_remaining": balls_remaining, "wickets": wickets,
        "runs_required": runs_required, "gender": gender, "format": format,
    })
    return {"data": result, "error": None}

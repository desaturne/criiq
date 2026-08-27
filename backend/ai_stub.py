"""ai_stub.py — calls the real model via model_bridge, falls back to stub data if unreachable."""

import logging

import model_bridge

log = logging.getLogger("ai_stub")


def _fallback_recommendations(match_context: dict) -> list[dict]:
    opponent = match_context.get("opponent", "the opposition")
    venue = match_context.get("venue") or "this venue"
    return [
        {"rank": 1, "player_id": "stub-1", "player_name": "S Mandhana", "role": "batter", "in_xi": True,
         "score": 92.4, "reasons": [f"Averages 45+ vs {opponent} and strong record at {venue}."]},
        {"rank": 2, "player_id": "stub-2", "player_name": "H Kaur", "role": "batter", "in_xi": True,
         "score": 88.1, "reasons": ["In-form captain; high impact score in last 10 matches."]},
        {"rank": 3, "player_id": "stub-3", "player_name": "DB Sharma", "role": "all-rounder", "in_xi": True,
         "score": 86.7, "reasons": [f"Economy under 6.5 and takes powerplay wickets vs {opponent}."]},
        {"rank": 4, "player_id": "stub-4", "player_name": "SR Verma", "role": "batter", "in_xi": True,
         "score": 84.9, "reasons": ["Best strike rate in the squad during the powerplay."]},
        {"rank": 5, "player_id": "stub-5", "player_name": "RS Gayakwad", "role": "bowler", "in_xi": True,
         "score": 82.3, "reasons": [f"Left-arm spin matches up well against {opponent}'s top order."]},
        {"rank": 6, "player_id": "stub-6", "player_name": "R Ghosh", "role": "wicketkeeper", "in_xi": True,
         "score": 80.5, "reasons": ["Finisher profile: 140+ strike rate at the death."]},
    ]


def get_recommendations(match_context: dict) -> dict:
    """Returns the model's full ranked pool (~20 players), each tagged in_xi.

    The opposition XI our side is picked against comes from one of two places:
      * `opponent_player_ids` -- the coach named the opposition XI themselves.
        Used verbatim, and no auto-pick model run is spent.
      * `auto_opponent_xi` -- no named XI, so predict the opponent's probable
        XI first and counter that instead.
    Either way the ids activate real player-vs-player head-to-head matchup
    data in the scorer rather than only team-level aggregates, which is what
    makes "our XI, chosen against *this* XI" different from a generic pick.
    """
    team = match_context.get("team") or "India"
    opponent = match_context.get("opponent", "the opposition")
    gender = match_context.get("gender") or "female"
    # Honour the caller's format instead of pinning it to the default -- this
    # used to ignore match_context["format"] outright, so the API's format
    # field was accepted and silently discarded. model_bridge normalizes the
    # "T20I" spelling the UI sends to the "T20" the model scopes are keyed by.
    fmt = match_context.get("format") or model_bridge.DEFAULT_FORMAT
    venue = match_context.get("venue")
    auto_opponent_xi = bool(match_context.get("auto_opponent_xi"))
    chosen_opponent_ids = [pid for pid in (match_context.get("opponent_player_ids") or []) if pid]

    opponent_xi_out, opponent_player_ids = None, None
    if chosen_opponent_ids:
        # The coach named the opposition XI. Take it as given -- picking a
        # different XI here would silently answer a question they didn't ask.
        opponent_player_ids = chosen_opponent_ids
    elif auto_opponent_xi:
        try:
            opp = model_bridge.recommend(team=opponent, opponent=team, venue=venue, fmt=fmt, gender=gender)
            opponent_player_ids = [p["player_id"] for p in opp["xi"]]
            opponent_xi_out = [{"player_id": p["player_id"], "player_name": p["name"],
                                 "role": p["role_bucket"], "score": p["score"]} for p in opp["xi"]]
        except model_bridge.ModelBridgeError as exc:
            log.warning("opponent auto-XI unavailable (%s) -- proceeding without named-opponent matchups", exc)

    try:
        result = model_bridge.recommend(team=team, opponent=opponent, venue=venue, fmt=fmt, gender=gender,
                                         opponent_player_ids=opponent_player_ids)
    except model_bridge.ModelBridgeError as exc:
        log.warning("recommend engine unavailable (%s) -- serving stub data", exc)
        return {"recommendations": _fallback_recommendations(match_context),
                "opponent_xi": None, "head_to_head": None, "countered_opponent_xi": False}

    def _reasons(p: dict) -> list[str]:
        reasoning = p.get("reasoning") or []
        return reasoning if isinstance(reasoning, list) else [str(reasoning)]

    xi_ids = {p["player_id"] for p in result["xi"]}

    recs = [
        {"rank": i + 1, "player_id": p["player_id"], "player_name": p["name"], "role": p["role_bucket"],
         "score": p["score"], "reasons": _reasons(p), "in_xi": p["player_id"] in xi_ids}
        for i, p in enumerate(result["pool"])
    ]
    return {"recommendations": recs, "opponent_xi": opponent_xi_out,
            # per-player batting/bowling records against the named XI. Only
            # populated when an opponent XI was supplied, so the UI can say
            # whether a pick was actually matchup-driven or just form-driven.
            "head_to_head": result.get("head_to_head"),
            "countered_opponent_xi": bool(opponent_player_ids)}


def _fallback_win_probability(state: dict) -> dict:
    innings = int(state.get("innings", 1))
    balls_remaining = int(state.get("balls_remaining", 120))
    wickets = int(state.get("wickets", 0))
    runs_required = state.get("runs_required")

    prob = 0.5
    if innings == 2 and runs_required is not None and balls_remaining > 0:
        required_rate = (float(runs_required) / balls_remaining) * 6
        prob = 0.5 + (7.5 - required_rate) * 0.08   # rate 7.5 ≈ even game
    prob -= wickets * 0.03                           # each wicket hurts
    prob = max(0.02, min(0.98, prob))                # clamp to 2–98%

    over = (120 - balls_remaining) // 6
    phase = "powerplay" if over < 6 else ("middle" if over < 16 else "death")

    return {
        "win_probability_batting": round(prob, 3),
        "win_probability_bowling": round(1 - prob, 3),
        "phase": phase,
        "model": "stub",
    }


def get_win_probability(state: dict) -> dict:
    """Returns win probability for the batting side (0..1)."""
    try:
        return model_bridge.winprob(
            innings=int(state.get("innings", 1)),
            wickets=int(state.get("wickets", 0)),
            balls_remaining=state.get("balls_remaining"),
            runs_required=state.get("runs_required"),
            fmt=state.get("format") or model_bridge.DEFAULT_FORMAT,
            gender=state.get("gender") or "female",
        )
    except model_bridge.ModelBridgeError as exc:
        log.warning("winprob engine unavailable (%s) -- serving stub data", exc)
        return _fallback_win_probability(state)

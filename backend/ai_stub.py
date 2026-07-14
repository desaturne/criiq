"""
ai_stub.py — PLACEHOLDER for the teammate's real AI model.

The backend imports these two functions. When the real model is ready, the
teammate replaces this file (or we change the import) — the function names,
arguments and return shapes must stay IDENTICAL so nothing else changes.

Everything returned here is fake but realistically shaped.
"""


def get_recommendations(match_context: dict) -> list[dict]:
    """
    match_context = {"opponent": "Australia", "venue": "Wankhede", "format": "T20I"}
    Returns a ranked list of players with a one-line reason each.
    """
    opponent = match_context.get("opponent", "the opposition")
    venue = match_context.get("venue") or "this venue"
    return [
        {"rank": 1, "player_name": "S Mandhana", "role": "batter",
         "score": 92.4, "reason": f"Averages 45+ vs {opponent} and strong record at {venue}."},
        {"rank": 2, "player_name": "H Kaur", "role": "batter",
         "score": 88.1, "reason": "In-form captain; high impact score in last 10 matches."},
        {"rank": 3, "player_name": "DB Sharma", "role": "all-rounder",
         "score": 86.7, "reason": f"Economy under 6.5 and takes powerplay wickets vs {opponent}."},
        {"rank": 4, "player_name": "SR Verma", "role": "batter",
         "score": 84.9, "reason": "Best strike rate in the squad during the powerplay."},
        {"rank": 5, "player_name": "RS Gayakwad", "role": "bowler",
         "score": 82.3, "reason": f"Left-arm spin matches up well against {opponent}'s top order."},
        {"rank": 6, "player_name": "R Ghosh", "role": "wicketkeeper",
         "score": 80.5, "reason": "Finisher profile: 140+ strike rate at the death."},
    ]


def get_win_probability(state: dict) -> dict:
    """
    state = {"innings": 2, "balls_remaining": 30, "wickets": 4, "runs_required": 40}
    Returns win probability for the batting side (0..1).

    The fake formula: start at 50%, get worse as the required run rate climbs
    and as wickets fall. Roughly believable, good enough for the frontend.
    """
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
        "model": "stub",   # the real model will report its own name here
    }

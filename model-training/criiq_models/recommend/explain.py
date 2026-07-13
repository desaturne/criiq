"""Turn a `score()` result into a plain-language explanation payload.

Mirrors the "strengths" plain-language summary style already used in
`data-collection/criiq_data/advanced.py` — a list of short, coach-facing
sentences generated directly from the `components` breakdown, so nothing
said here is invented independently of the numbers that produced the score.
"""
from __future__ import annotations


def explain(scored: dict, alternative: dict | None = None, slot: str | None = None) -> dict:
    """`alternative`/`slot`: the best-scoring player NOT selected for the
    same team-sheet slot (opener / core batting / bowling tail — see
    `selection/optimize.slot_category`), if any — lets the explanation say
    *why this player over the next-best option*, not just describe her own
    numbers in isolation.
    """
    c = scored["components"]
    inp = c["inputs"]
    lines: list[str] = []

    name = scored.get("name") or scored["player_id"]
    role_note = " — a wicket-keeper option" if inp.get("is_keeper") else ""
    lines.append(f"{name} rates {scored['score']}/100 for this matchup against {scored['opponent']}{role_note}.")

    slot_label = {"opener": "the opening slot", "core_batting": "the middle/top order",
                  "bowler_tail": "the bowling attack"}.get(slot, "the team")
    if alternative is not None:
        alt_name = alternative.get("name") or alternative["player_id"]
        lines.append(
            f"Picked for {slot_label} ahead of {alt_name} "
            f"(score {alternative['score']}) — the next-best available option there.")
    elif slot is not None:
        lines.append(f"No close alternative in the pool for {slot_label} — an uncontested pick.")

    def _pct(wpa):
        return f"{wpa * 100:+.1f}%" if wpa is not None else "n/a"

    if c["model_applied"]:
        lines.append(
            f"Based on {inp['career_matches']} career matches, she's expected to shift her team's "
            f"win probability by {_pct(inp['predicted_batting_wpa'])} per match with the bat and "
            f"{_pct(inp['predicted_bowling_wpa'])} with the ball ({c['model_part']:+} pts).")
    else:
        lines.append(
            f"Too little history to trust the model ({c['cold_start_reason']}), so this falls back "
            f"to her career baseline: {_pct(inp['predicted_batting_wpa'])} batting / "
            f"{_pct(inp['predicted_bowling_wpa'])} bowling win-probability impact per match "
            f"({c['model_part']:+} pts).")

    dot_pct, boundary_pct = inp.get("bowl_dot_pct"), inp.get("bowl_boundary_pct")
    if dot_pct is not None and boundary_pct is not None:
        style = "control-focused, building pressure with dot balls" if dot_pct >= boundary_pct * 3 \
            else "attacking, prone to conceding boundaries" if boundary_pct >= 15 else "a balanced containment profile"
        lines.append(
            f"Her bowling has {style}: {dot_pct:.0f}% dot balls, {boundary_pct:.0f}% boundary balls conceded.")

    if inp["matchup_balls_vs_opponent_bowlers"] > 0:
        rate = inp["matchup_dismissal_rate"]
        direction = "a favourable" if inp["aggregate_matchup_part"] >= 0 else "a tough"
        lines.append(
            f"Has faced {inp['matchup_balls_vs_opponent_bowlers']} balls against "
            f"{scored['opponent']}'s bowlers (dismissal rate {round(rate, 3) if rate is not None else 'n/a'}) "
            f"— {direction} matchup ({inp['aggregate_matchup_part']:+} pts).")
    else:
        lines.append(f"No recorded history against {scored['opponent']}'s specific bowlers.")

    if inp["style_matchup_available"]:
        mix = inp["opponent_bowling_mix"]
        mix_desc = " / ".join(f"{style} {round(share * 100)}%" for style, share in mix.items() if share > 0)
        direction = "an edge" if inp["style_matchup_part"] >= 0 else "a weakness"
        lines.append(
            f"{scored['opponent']}'s attack leans {mix_desc} — {direction} against this player's "
            f"vs-pace/vs-spin record ({inp['style_matchup_part']:+} pts).")

    if inp["bowl_matchup_balls_vs_opponent_batters"] > 0:
        rate = inp["bowl_matchup_wicket_rate"]
        direction = "a favourable" if inp["bowl_matchup_part"] >= 0 else "a tough"
        lines.append(
            f"Has bowled {inp['bowl_matchup_balls_vs_opponent_batters']} balls at "
            f"{scored['opponent']}'s specific batters (wicket rate {round(rate, 3) if rate is not None else 'n/a'}) "
            f"— {direction} matchup for her with the ball ({inp['bowl_matchup_part']:+} pts).")

    if c["phase_fit_part"] > 0:
        lines.append(f"Stands out among teammates in her strongest phase of the innings "
                     f"({c['phase_fit_part']:+} pts).")

    if c.get("team_need_part"):
        phase = c["team_need_phase"]
        lines.append(f"This pool is currently thin at the {phase}, and she's a genuine strength "
                     f"there — a bonus for filling that specific gap ({c['team_need_part']:+} pts).")

    if inp["importance_score"] is not None:
        rank_note = " and ICC-ranked" if inp["icc_rank"] is not None else ""
        lines.append(
            f"A proven track record backs this up: importance score {inp['importance_score']}/100, "
            f"{inp['win_pct']}% win rate{rank_note} ({c['standing_part']:+} pts).")

    if c["risk_part"] < 0:
        flags = []
        if inp["age_advisory"]:
            flags.append("age advisory")
        if inp["retirement_status"] == "INCONSISTENT":
            flags.append("inconsistent selection history")
        if inp["retirement_status"] == "INACTIVE" and inp["recall_flag"]:
            flags.append("recalled after an inactive spell")
        lines.append(f"Worth flagging: {', '.join(flags)} ({c['risk_part']} pts).")

    return {
        "player_id": scored["player_id"], "name": scored.get("name"),
        "score": scored["score"], "summary": lines, "components": c,
    }


def explain_many(scored_players: list[dict]) -> list[dict]:
    return [explain(s) for s in scored_players]

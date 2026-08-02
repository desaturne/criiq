"""turns a score() result into a plain-language explanation payload.

mirrors the "strengths" summary style in data-collection/criiq_data/advanced.py,
generating coach-facing sentences straight from the components breakdown.
no em-dashes in the generated prose; ordinary hyphens like "all-rounder" are fine.
"""
from __future__ import annotations

from ..config import SETTINGS

_PHASE_LABEL = {
    "powerplay": "powerplay (overs 1-6)",
    "middle": "middle overs (7-15)",
    "death": "death overs (16-20)",
}


def explain(scored: dict, alternative: dict | None = None, slot: str | None = None,
            h2h_batting: dict | None = None, h2h_bowling: dict | None = None) -> dict:
    """`alternative`/`slot` is the best-scoring player not picked for the same
    slot (see `selection/optimize.slot_category`), if any, so the explanation
    can say why this player over the next-best option, not just describe
    their own numbers.
    """
    c = scored["components"]
    inp = c["inputs"]
    lines: list[str] = []

    name = scored.get("name") or scored["player_id"]
    role_note = " (wicket-keeper option)" if inp.get("is_keeper") else ""
    lines.append(f"{name} rates {scored['score']}/100 for this matchup against {scored['opponent']}{role_note}.")

    slot_label = {"opener": "the opening slot", "core_batting": "the middle/top order",
                  "bowler_tail": "the bowling attack"}.get(slot, "the team")
    if alternative is not None:
        alt_name = alternative.get("name") or alternative["player_id"]
        lines.append(
            f"Picked for {slot_label} ahead of {alt_name} "
            f"(score {alternative['score']}), the next-best available option there.")
    elif slot is not None:
        lines.append(f"No close alternative in the pool for {slot_label}: an uncontested pick.")

    hand = (inp.get("batting_hand") or "").strip().lower().replace(" ", "-")
    archetype = inp.get("archetype")
    age = inp.get("age_years")
    age_suffix = f", {age:.0f} years old" if age is not None else ""
    if hand or archetype:
        descriptor = f"{hand + ' ' if hand else ''}{archetype or 'batter'}"
        lines.append(f"{descriptor[0].upper()}{descriptor[1:]}{age_suffix}.")
    elif age is not None:
        lines.append(f"{age:.0f} years old.")
    if inp.get("bowling_style"):
        lines.append(f"Bowls {inp['bowling_style'].strip().lower()}.")

    _append_batting_profile(lines, inp, archetype)

    def _pct(wpa):
        return f"{wpa * 100:+.1f}%" if wpa is not None else "n/a"

    if c["model_applied"]:
        lines.append(
            f"Based on {inp['career_matches']} career matches, they're expected to shift their team's "
            f"win probability by {_pct(inp['predicted_batting_wpa'])} per match with the bat and "
            f"{_pct(inp['predicted_bowling_wpa'])} with the ball ({c['model_part']:+} pts).")
    else:
        lines.append(
            f"Too little history to trust the model ({c['cold_start_reason']}), so this falls back "
            f"to their career baseline: {_pct(inp['predicted_batting_wpa'])} batting / "
            f"{_pct(inp['predicted_bowling_wpa'])} bowling win-probability impact per match "
            f"({c['model_part']:+} pts).")

    # score is win-probability-added, not raw strike rate, so a genuine
    # finisher with low recent win-impact can still rate low here despite a strong profile
    if archetype in ("finisher", "power hitter") and c["model_part"] <= SETTINGS.finisher_low_impact_threshold:
        lines.append(
            f"The batting profile above is strong, but this rating is driven by win-probability-added "
            f"(impact on results), not raw hitting, so a {archetype} with modest recent win-impact "
            f"still rates low here. Worth a manual look for that specific role.")

    sr_part = c.get("strike_rate_part", 0.0)
    career_sr, sr_bench = inp.get("career_bat_sr"), inp.get("sr_benchmark")
    if sr_part < 0 and career_sr is not None and sr_bench:
        aw = inp.get("game_awareness_factor") or 0.0
        aw_signals = inp.get("game_awareness_signals") or {}
        if aw > 0 and aw_signals:
            offset = (f"partly offset by game awareness ({', '.join(sorted(aw_signals))}, "
                      f"awareness {aw:.0%})")
        else:
            offset = "with little experience or game awareness to offset it"
        lines.append(
            f"Career strike rate {career_sr:.0f} is below the {sr_bench:.0f} par for this format, "
            f"{offset} ({sr_part} pts). Modern T20I prizes a higher strike rate.")

    dot_pct, boundary_pct = inp.get("bowl_dot_pct"), inp.get("bowl_boundary_pct")
    if dot_pct is not None and boundary_pct is not None:
        style = "control-focused, building pressure with dot balls" if dot_pct >= boundary_pct * 3 \
            else "attacking, prone to conceding boundaries" if boundary_pct >= 15 else "a balanced containment profile"
        lines.append(
            f"Their bowling has {style}: {dot_pct:.0f}% dot balls, {boundary_pct:.0f}% boundary balls conceded.")

    if inp["matchup_balls_vs_opponent_bowlers"] > 0:
        rate = inp["matchup_dismissal_rate"]
        direction = "a favourable" if inp["aggregate_matchup_part"] >= 0 else "a tough"
        lines.append(
            f"Has faced {inp['matchup_balls_vs_opponent_bowlers']} balls against "
            f"{scored['opponent']}'s bowlers (dismissal rate {round(rate, 3) if rate is not None else 'n/a'}): "
            f"{direction} matchup ({inp['aggregate_matchup_part']:+} pts).")
    else:
        lines.append(f"No recorded history against {scored['opponent']}'s specific bowlers.")

    if inp["style_matchup_available"]:
        mix = inp["opponent_bowling_mix"]
        mix_desc = " / ".join(f"{style} {round(share * 100)}%" for style, share in mix.items() if share > 0)
        direction = "an edge" if inp["style_matchup_part"] >= 0 else "a weakness"
        lines.append(
            f"{scored['opponent']}'s attack leans {mix_desc}: {direction} against this player's "
            f"vs-pace/vs-spin record ({inp['style_matchup_part']:+} pts).")

    if inp["bowl_matchup_balls_vs_opponent_batters"] > 0:
        rate = inp["bowl_matchup_wicket_rate"]
        direction = "a favourable" if inp["bowl_matchup_part"] >= 0 else "a tough"
        lines.append(
            f"Has bowled {inp['bowl_matchup_balls_vs_opponent_batters']} balls at "
            f"{scored['opponent']}'s specific batters (wicket rate {round(rate, 3) if rate is not None else 'n/a'}): "
            f"{direction} matchup for them with the ball ({inp['bowl_matchup_part']:+} pts).")

    if h2h_batting and (h2h_batting.get("best") or h2h_batting.get("bogey")):
        bits = []
        best = h2h_batting.get("best")
        if best:
            bits.append(f"best to target is {best['opponent']} (SR {best['strike_rate']} in {best['balls']} balls)")
        bogey = h2h_batting.get("bogey")
        if bogey:
            bits.append(f"bogey bowler is {bogey['opponent']} ({bogey['dismissals']} dismissals in {bogey['balls']} balls)")
        lines.append(f"Specific matchups vs {scored['opponent']}'s named XI: {'; '.join(bits)}.")

    if h2h_bowling and (h2h_bowling.get("best") or h2h_bowling.get("most_expensive")):
        bits = []
        best = h2h_bowling.get("best")
        if best:
            bits.append(f"has {best['opponent']}'s number ({best['dismissals']} in {best['balls']} balls)")
        expensive = h2h_bowling.get("most_expensive")
        if expensive:
            bits.append(f"{expensive['opponent']} counters well (economy {expensive['economy']} in {expensive['balls']} balls)")
        lines.append(f"Specific matchups vs {scored['opponent']}'s named XI: {'; '.join(bits)}.")

    if c["phase_fit_part"] > 0:
        lines.append(f"Stands out among teammates in their strongest phase of the innings "
                     f"({c['phase_fit_part']:+} pts).")

    if c.get("team_need_part"):
        phase = c["team_need_phase"]
        lines.append(f"This pool is currently thin at the {phase}, and they're a genuine strength "
                     f"there, earning a bonus for filling that specific gap ({c['team_need_part']:+} pts).")

    if inp["importance_score"] is not None:
        rank_note = " and ICC-ranked" if inp["icc_rank"] is not None else ""
        lines.append(
            f"A proven track record backs this up: importance score {inp['importance_score']}/100, "
            f"{inp['win_pct']}% win rate{rank_note} ({c['standing_part']:+} pts).")

    if (inp.get("venue_matches") or 0) > 0:
        bat_pct, bowl_pct = inp.get("venue_bat_contribution_pct"), inp.get("venue_bowl_contribution_pct")
        parts = []
        if bat_pct is not None:
            parts.append(f"{bat_pct:.0f}% of the team's runs")
        if bowl_pct is not None:
            parts.append(f"{bowl_pct:.0f}% of the team's wickets")
        detail = " and ".join(parts) if parts else "a recorded track record"
        plural = "es" if inp["venue_matches"] != 1 else ""
        ground = f" ({inp['venue_name']})" if inp.get("venue_name") else ""
        lines.append(
            f"At this ground specifically{ground}: {inp['venue_matches']} match{plural} of history, "
            f"averaging {detail}.")

        set_avg, set_sr = inp.get("venue_setting_average"), inp.get("venue_setting_strike_rate")
        chase_avg, chase_sr = inp.get("venue_chasing_average"), inp.get("venue_chasing_strike_rate")
        if set_avg is not None or chase_avg is not None:
            set_desc = f"avg {set_avg}, SR {set_sr}" if set_avg is not None else "no record batting first here"
            chase_desc = f"avg {chase_avg}, SR {chase_sr}" if chase_avg is not None else "no record chasing here"
            lines.append(f"Batting first at this ground: {set_desc}. Chasing: {chase_desc}.")

        bogey = inp.get("venue_bogey_bowler")
        if bogey:
            lines.append(
                f"At this ground against {scored['opponent']} specifically, {bogey['bowler_name']} "
                f"has been their toughest opponent: {bogey['dismissals']} dismissal(s) in "
                f"{bogey['balls']} balls.")

    dom_matches = inp.get("domestic_form_matches") or 0
    if dom_matches > 0:
        plural = "es" if dom_matches != 1 else ""
        lines.append(
            f"Recent domestic form ({dom_matches} match{plural}): shifting win probability by "
            f"{_pct(inp.get('domestic_form_batting_wpa'))} per match with the bat and "
            f"{_pct(inp.get('domestic_form_bowling_wpa'))} with the ball, factored into the "
            f"model above, alongside {inp['career_matches']} international career matches.")

    if inp.get("retirement_status"):
        reason = inp.get("status_reason")
        # comma not parens: the reason often already ends in a parenthetical,
        # and nesting parens reads badly
        reason_note = f", {reason}" if reason else ""
        lines.append(f"Current status: {inp['retirement_status']}{reason_note}.")

    if c["risk_part"] < 0:
        flags = []
        if inp["age_advisory"]:
            flags.append("age advisory")
        if inp["retirement_status"] == "INCONSISTENT":
            flags.append("inconsistent selection history")
        if inp["retirement_status"] == "INACTIVE" and inp["recall_flag"]:
            flags.append("recalled after an inactive spell")
        if inp["retirement_status"] == "INACTIVE" and inp.get("recent_domestic_activity") and not inp["recall_flag"]:
            flags.append("internationally inactive, included on recent domestic activity rather than an international recall")
        lines.append(f"Worth flagging: {', '.join(flags)} ({c['risk_part']} pts).")

    return {
        "player_id": scored["player_id"], "name": scored.get("name"),
        "score": scored["score"], "summary": lines, "components": c,
    }


def _append_batting_profile(lines: list[str], inp: dict, archetype: str | None) -> None:
    """the "what to expect / best overs" batting profile block, from
    data-collection's `player_advanced` (surfaced via score.py's inputs, never
    scored). gated on >= 30 balls faced so a tailender's tiny sample doesn't
    get narrated as a real profile.
    """
    bat_sr = inp.get("bat_strike_rate")
    if bat_sr is None or (inp.get("bat_balls") or 0) < 30:
        return

    profile_bits = [f"strike rate {bat_sr:.0f}"]
    if inp.get("bat_boundary_pct") is not None:
        profile_bits.append(f"{inp['bat_boundary_pct']:.0f}% boundary balls")
    if inp.get("bat_dot_pct") is not None:
        profile_bits.append(f"{inp['bat_dot_pct']:.0f}% dot balls")
    sixes, six_rate = inp.get("bat_sixes"), inp.get("bat_six_rate")
    if sixes is not None and six_rate is not None:
        profile_bits.append(f"{sixes} career sixes ({six_rate} per 100 balls)")
    lines.append(f"With the bat, expect {', '.join(profile_bits)}.")

    best_phase = inp.get("bat_best_phase")
    bp_sr = inp.get("bat_best_phase_sr")
    if best_phase and bp_sr is not None:
        label = _PHASE_LABEL.get(best_phase, best_phase)
        bp_bdry = inp.get("bat_best_phase_boundary_pct")
        bdry_note = f", {bp_bdry:.0f}% boundaries" if bp_bdry is not None else ""
        lines.append(f"Highest impact in the {label}: strike rate {bp_sr:.0f}{bdry_note} there.")


def explain_many(scored_players: list[dict]) -> list[dict]:
    return [explain(s) for s in scored_players]

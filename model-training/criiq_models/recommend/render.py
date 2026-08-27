"""renders a team sheet as plain text from the same select_xi/explain data
cli.cmd_recommend --explain outputs as JSON. purely formatting, no new
computation.
"""
from __future__ import annotations

import textwrap

_WIDTH = 78
_INDENT = "      "


def _wrap(text: str) -> str:
    return "\n".join(textwrap.wrap(
        text, width=_WIDTH - len(_INDENT), initial_indent=_INDENT,
        subsequent_indent=_INDENT + "  "))


_POOL_SECTIONS = [
    ("batter", "BATTING POOL"),
    ("all-rounder", "ALL-ROUNDER POOL"),
    ("bowler", "BOWLING POOL"),
]


def _shap_one_liner(shap_result: dict) -> str:
    if set(shap_result) == {"error"}:
        return f"[SHAP] {shap_result['error']}"
    bits = []
    for target, result in shap_result.items():
        if "error" in result:
            bits.append(f"{target}: {result['error']}")
            continue
        top = result["top_contributions"][0] if result["top_contributions"] else None
        if top:
            bits.append(f"{target} top driver: {top['feature']} ({top['value']:+.4f})")
    return "[SHAP] " + "; ".join(bits) if bits else ""


def render_team_sheet(team: str, opponent: str, venue_id: str | None,
                       xi_explained: list[dict], pool_explained: list[dict],
                       model_metadata: dict | None, constraints: dict | None,
                       role_options: list[dict] | None = None,
                       head_to_head: dict | None = None,
                       strength_context: dict | None = None,
                       rotation_xi: dict | None = None) -> str:
    """xi_explained/pool_explained come from cmd_recommend --explain: each
    entry has name/role_bucket/is_keeper/batting_position_median/score plus a
    reasoning list. pool_explained is the wider shortlist ranked by score;
    xi_explained is the final constrained XI, not just the top 11, since the
    MILP can trade a top specialist for a required keeper/opener.

    the shortlist splits into batting/all-rounder/bowling pools since that's
    how a coach thinks about a squad. unrecognized-role players get their own
    trailing section instead of being dropped.
    """
    lines: list[str] = []
    bar = "=" * _WIDTH
    venue_note = f" at venue {venue_id}" if venue_id else ""
    lines.append(bar)
    lines.append(f"  CRIIQ RECOMMENDATION: {team.upper()} vs {opponent.upper()}{venue_note}")
    lines.append(bar)
    lines.append("")

    if model_metadata:
        trained = model_metadata.get("trained_at", "unknown")
        n_rows = model_metadata.get("n_rows_total")
        lines.append(f"  Model trained {trained} on {n_rows} leakage-safe rows "
                      f"({model_metadata.get('format')}, {model_metadata.get('gender')})")
        lines.append("")

    if strength_context and strength_context.get("lopsided") and strength_context.get("stronger_side") == team:
        me, opp = strength_context["team"], strength_context["opponent"]
        lines.append(f"  MATCHUP CONTEXT: {team} is the substantially stronger side here "
                      f"({me['icc_ranked']} ICC-ranked players vs {opponent}'s {opp['icc_ranked']}).")
        lines.append(f"  You can rest frontline players; see the ROTATION XI below the first-choice side.")
        lines.append("")

    xi_ids = {p["player_id"] for p in xi_explained}

    def _render_player(i, p):
        role = p["role_bucket"]
        tags = "".join([" (wk)" if p.get("is_keeper") else "",
                         " [XI]" if p["player_id"] in xi_ids else ""])
        lines.append(f"  {i:2d}. {p['name']:<22s} {role:<12s}{tags:<10s} {p['score']:>5.1f}/100")
        for sentence in p.get("reasoning", []):
            lines.append(_wrap(f"- {sentence}"))
        if p.get("shap"):
            lines.append(_wrap(_shap_one_liner(p["shap"])))
        lines.append("")

    lines.append(f"  ROSTER: {len(pool_explained)} PLAYERS ACROSS 3 ROLE POOLS (ranked by score)")
    for bucket, heading in _POOL_SECTIONS:
        members = sorted((p for p in pool_explained if p["role_bucket"] == bucket),
                          key=lambda p: -p["score"])
        if not members:
            continue
        lines.append("  " + "-" * (_WIDTH - 2))
        lines.append(f"  {heading} ({len(members)})")
        lines.append("  " + "-" * (_WIDTH - 2))
        for i, p in enumerate(members, start=1):
            _render_player(i, p)
    unrecognized = sorted((p for p in pool_explained if p["role_bucket"] not in dict(_POOL_SECTIONS)),
                          key=lambda p: -p["score"])
    if unrecognized:
        lines.append("  " + "-" * (_WIDTH - 2))
        lines.append(f"  UNRECOGNIZED ROLE ({len(unrecognized)})")
        lines.append("  " + "-" * (_WIDTH - 2))
        for i, p in enumerate(unrecognized, start=1):
            _render_player(i, p)

    if role_options:
        lines.append("  " + "-" * (_WIDTH - 2))
        lines.append("  SPECIALIST ROLE OPTIONS (best available per role, regardless of overall rank)")
        lines.append("  " + "-" * (_WIDTH - 2))
        for opt in role_options:
            in_xi = " [XI]" if opt["player_id"] in xi_ids else ""
            phase_note = f", {opt['detail']}" if opt.get("detail") else ""
            lines.append(f"  {opt['archetype'].upper():<13s} {opt['name']:<22s} "
                          f"{opt['score']:>5.1f}/100{in_xi}{phase_note}")
        lines.append("")

    lines.append(bar)
    lines.append("  PLAYING XI (batting order)")
    lines.append("  " + "-" * (_WIDTH - 2))
    for i, p in enumerate(xi_explained, start=1):
        role = p["role_bucket"]
        tag = " (wk)" if p.get("is_keeper") else ""
        lines.append(f"  {i:2d}. {p['name']:<22s} {role:<12s}{tag:<5s} {p['score']:>5.1f}/100")
        for sentence in p.get("reasoning", []):
            lines.append(_wrap(f"- {sentence}"))
        if p.get("shap"):
            lines.append(_wrap(_shap_one_liner(p["shap"])))
        lines.append("")

    if constraints:
        lines.append("  " + "-" * (_WIDTH - 2))
        lines.append(
            f"  Selection: MILP-optimal XI (>= {constraints.get('min_batting_capable')} "
            f"batting-capable, >= {constraints.get('min_bowling_capable')} bowling-capable, "
            f">= {constraints.get('min_keepers')} keeper(s), "
            f">= {constraints.get('min_openers')} opener(s))")

    if head_to_head and (head_to_head.get("batting") or head_to_head.get("bowling")):
        lines.append(bar)
        lines.append(f"  HEAD-TO-HEAD vs {opponent.upper()}'S NAMED XI (recorded matchups, >= 6 balls)")
        lines.append("  " + "-" * (_WIDTH - 2))
        bat = head_to_head.get("batting") or {}
        if bat:
            lines.append("  Your batters vs their bowlers:")
            for name in sorted(bat):
                s = bat[name]
                bits = []
                if s.get("bogey"):
                    b = s["bogey"]
                    bits.append(f"troubled by {b['opponent']} ({b['dismissals']} in {b['balls']} balls)")
                if s.get("best"):
                    d = s["best"]
                    bits.append(f"scores off {d['opponent']} (SR {d['strike_rate']} in {d['balls']})")
                if bits:
                    lines.append(_wrap(f"- {name}: {'; '.join(bits)}."))
        bowl = head_to_head.get("bowling") or {}
        if bowl:
            lines.append("  Your bowlers vs their batters:")
            for name in sorted(bowl):
                s = bowl[name]
                bits = []
                if s.get("best"):
                    b = s["best"]
                    bits.append(f"has {b['opponent']}'s number ({b['dismissals']} in {b['balls']} balls)")
                if s.get("most_expensive"):
                    e = s["most_expensive"]
                    bits.append(f"leaks to {e['opponent']} (econ {e['economy']} in {e['balls']})")
                if bits:
                    lines.append(_wrap(f"- {name}: {'; '.join(bits)}."))

    if rotation_xi and rotation_xi.get("xi"):
        lines.append(bar)
        rested = ", ".join(p["name"] for p in rotation_xi.get("rested", []))
        lines.append("  ROTATION XI (frontline rested, you are the stronger side)")
        lines.append(f"  Resting: {rested}")
        lines.append("  " + "-" * (_WIDTH - 2))
        for i, p in enumerate(rotation_xi["xi"], start=1):
            tag = " (wk)" if p.get("is_keeper") else ""
            lines.append(f"  {i:2d}. {p['name']:<22s} {p['role_bucket']:<12s}{tag:<5s} {p['score']:>5.1f}/100")

    lines.append(bar)
    return "\n".join(lines)


def _render_shap_target(lines: list[str], target: str, result: dict) -> None:
    lines.append("  " + "-" * (_WIDTH - 2))
    lines.append(f"  SHAP BREAKDOWN -- {target}")
    lines.append("  " + "-" * (_WIDTH - 2))
    if "error" in result:
        lines.append(_wrap(result["error"]))
        return

    lines.append(f"  base value:      {result['base_value']:>10.6f}")
    lines.append(f"  predicted value: {result['predicted_value']:>10.6f}")
    lines.append("")
    top = result["top_contributions"]
    shown = {c["feature"] for c in top}
    rest_sum = sum(v for f, v in result["contributions"].items() if f not in shown)
    n_rest = len(result["contributions"]) - len(shown)
    for c in top:
        lines.append(f"    {c['feature']:<32s} {c['value']:>+10.6f}")
    if n_rest > 0:
        lines.append(f"    {'(+ ' + str(n_rest) + ' more features, combined)':<32s} {rest_sum:>+10.6f}")


def render_player_explanation(name: str, opponent: str, venue_id: str | None, score: float,
                               summary: list[str], shap_result: dict | None = None) -> str:
    lines: list[str] = []
    bar = "=" * _WIDTH
    venue_note = f" at venue {venue_id}" if venue_id else ""
    lines.append(bar)
    lines.append(f"  PLAYER EXPLANATION: {name} vs {opponent.upper()}{venue_note}")
    lines.append(f"  Score: {score}/100")
    lines.append(bar)
    lines.append("")
    for sentence in summary:
        lines.append(_wrap(f"- {sentence}"))
    lines.append("")

    if shap_result is not None:
        if set(shap_result) == {"error"}:
            lines.append("  " + "-" * (_WIDTH - 2))
            lines.append("  SHAP BREAKDOWN")
            lines.append("  " + "-" * (_WIDTH - 2))
            lines.append(_wrap(shap_result["error"]))
        else:
            for target, result in shap_result.items():
                _render_shap_target(lines, target, result)
        lines.append("")

    lines.append(bar)
    return "\n".join(lines)


def render_xi_analysis(team: str, opponent: str, venue_id: str | None,
                        xi_explained: list[dict], analysis: dict) -> str:
    """scores a coach's own hand-picked XI against the same constraints
    select_xi enforces, and compares it to the optimal pick from
    selection/optimize.analyze_xi.
    """
    lines: list[str] = []
    bar = "=" * _WIDTH
    venue_note = f" at venue {venue_id}" if venue_id else ""
    lines.append(bar)
    lines.append(f"  CUSTOM XI ANALYSIS: {team.upper()} vs {opponent.upper()}{venue_note}")
    lines.append(bar)
    lines.append("")

    if analysis.get("missing_player_ids"):
        lines.append(f"  WARNING: {len(analysis['missing_player_ids'])} player id(s) not found "
                      f"in this team's eligible pool, ignored: {', '.join(analysis['missing_player_ids'])}")
        lines.append("")

    for i, p in enumerate(xi_explained, start=1):
        role = p["role_bucket"]
        tag = " (wk)" if p.get("is_keeper") else ""
        lines.append(f"  {i:2d}. {p['name']:<22s} {role:<12s}{tag:<5s} {p['score']:>5.1f}/100")
        for sentence in p.get("reasoning", []):
            lines.append(_wrap(f"- {sentence}"))
        lines.append("")

    lines.append("  " + "-" * (_WIDTH - 2))
    c = analysis["counts"]
    r = analysis["requirements"]
    lines.append(f"  Total score: {analysis['total_score']}   Average: {analysis['average_score']}/100")
    lines.append(f"  Composition: {c['size']}/{r['xi_size']} players, "
                 f"{c['batting_capable']} batting-capable (need {r['min_batting_capable']}), "
                 f"{c['bowling_capable']} bowling-capable (need {r['min_bowling_capable']}), "
                 f"{c['keepers']} keeper(s) (need {r['min_keepers']}), "
                 f"{c['openers']} opener(s) (need {r['min_openers']})")
    if analysis["violations"]:
        lines.append("  Violations:")
        for v in analysis["violations"]:
            lines.append(f"    - {v}")
    else:
        lines.append("  Meets every selection constraint the AI's own XI is held to.")

    lines.append("  " + "-" * (_WIDTH - 2))
    comp = analysis["comparison_to_optimal"]
    gap = comp["score_gap"]
    if gap <= 0:
        lines.append(f"  Matches or beats the AI's own optimal XI (optimal total: {comp['optimal_total_score']}).")
    else:
        lines.append(f"  {gap:.1f} points below the AI's own optimal XI "
                      f"(this XI: {analysis['total_score']}, optimal: {comp['optimal_total_score']}).")
    if comp["in_optimal_not_chosen"]:
        lines.append("  In the AI's optimal XI but not this one:")
        for p in comp["in_optimal_not_chosen"]:
            lines.append(f"    - {p['name']} ({p['score']}/100)")
    if comp["in_chosen_not_optimal"]:
        lines.append("  In this XI but not the AI's optimal pick:")
        for p in comp["in_chosen_not_optimal"]:
            lines.append(f"    - {p['name']} ({p['score']}/100)")

    lines.append(bar)
    return "\n".join(lines)

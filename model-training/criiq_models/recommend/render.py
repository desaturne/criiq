"""Human-readable team-sheet rendering — the same `select_xi`/`explain` data
`cli.cmd_recommend`'s `--explain` JSON already carries, laid out like an
actual team sheet instead of a JSON blob. Nothing here computes anything new;
it only formats numbers and sentences that already exist elsewhere.
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


def render_team_sheet(team: str, opponent: str, venue_id: str | None,
                       xi_explained: list[dict], pool_explained: list[dict],
                       model_metadata: dict | None, constraints: dict | None,
                       role_options: list[dict] | None = None) -> str:
    """`xi_explained`/`pool_explained`: the same lists `cmd_recommend
    --explain` builds -- each entry is a brief dict (`name`, `role_bucket`,
    `is_keeper`, `batting_position_median`, `score`) plus a `reasoning` list
    of sentences. `pool_explained` is the wider shortlist (ranked by raw
    score, `SETTINGS.pool_size` players); `xi_explained` is the final
    constrained-and-ordered XI -- not simply its top 11, since the MILP can
    trade a top-ranked specialist for a lower-scoring keeper/opener the
    constraints require, so the two lists are shown separately rather than
    one being a strict prefix of the other.

    The shortlist is split into three role-based pools (batting/all-rounder/
    bowling, each independently ranked by score) rather than one flat list --
    this is how a coach actually thinks about a squad, and it's what the XI's
    own batting/bowling-capable constraints (see `selection/optimize.py`)
    are already implicitly drawing from; showing the pools this way makes
    that visible instead of implicit. A player with an unrecognized role
    (`role_bucket == "unknown"`, no reliable ball-count signal) appears in
    its own small trailing section rather than being silently dropped.
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

    xi_ids = {p["player_id"] for p in xi_explained}

    def _render_player(i, p):
        role = p["role_bucket"]
        tags = "".join([" (wk)" if p.get("is_keeper") else "",
                         " [XI]" if p["player_id"] in xi_ids else ""])
        lines.append(f"  {i:2d}. {p['name']:<22s} {role:<12s}{tags:<10s} {p['score']:>5.1f}/100")
        for sentence in p.get("reasoning", []):
            lines.append(_wrap(f"- {sentence}"))
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
        lines.append("")

    if constraints:
        lines.append("  " + "-" * (_WIDTH - 2))
        lines.append(
            f"  Selection: MILP-optimal XI (>= {constraints.get('min_batting_capable')} "
            f"batting-capable, >= {constraints.get('min_bowling_capable')} bowling-capable, "
            f">= {constraints.get('min_keepers')} keeper(s), "
            f">= {constraints.get('min_openers')} opener(s))")
    lines.append(bar)
    return "\n".join(lines)


def render_xi_analysis(team: str, opponent: str, venue_id: str | None,
                        xi_explained: list[dict], analysis: dict) -> str:
    """A coach's own hand-picked XI, scored and checked against the same
    constraints `select_xi` enforces, plus a direct comparison to the
    provably-optimal pick (`selection/optimize.analyze_xi`) -- "how good is
    THIS specific XI", not "what's the best XI". Every real selector
    sometimes overrides the algorithm; this is the honest scorecard for that
    call, not a second opinion pretending to replace it.
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

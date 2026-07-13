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


def render_team_sheet(team: str, opponent: str, venue_id: str | None,
                       xi_explained: list[dict], pool_explained: list[dict],
                       model_metadata: dict | None, constraints: dict | None) -> str:
    """`xi_explained`/`pool_explained`: the same lists `cmd_recommend
    --explain` builds -- each entry is a brief dict (`name`, `role_bucket`,
    `is_keeper`, `batting_position_median`, `score`) plus a `reasoning` list
    of sentences. `pool_explained` is the wider shortlist (ranked by raw
    score, `SETTINGS.pool_size` players); `xi_explained` is the final
    constrained-and-ordered XI -- not simply its top 11, since the MILP can
    trade a top-ranked specialist for a lower-scoring keeper/opener the
    constraints require, so the two lists are shown separately rather than
    one being a strict prefix of the other.
    """
    lines: list[str] = []
    bar = "=" * _WIDTH
    venue_note = f" at venue {venue_id}" if venue_id else ""
    lines.append(bar)
    lines.append(f"  CRIIQ RECOMMENDATION — {team.upper()} vs {opponent.upper()}{venue_note}")
    lines.append(bar)
    lines.append("")

    if model_metadata:
        trained = model_metadata.get("trained_at", "unknown")
        n_rows = model_metadata.get("n_rows_total")
        lines.append(f"  Model trained {trained} on {n_rows} leakage-safe rows "
                      f"({model_metadata.get('format')}, {model_metadata.get('gender')})")
        lines.append("")

    xi_ids = {p["player_id"] for p in xi_explained}

    lines.append(f"  TOP {len(pool_explained)} RECOMMENDED PLAYERS (ranked by score)")
    lines.append("  " + "-" * (_WIDTH - 2))
    for i, p in enumerate(pool_explained, start=1):
        role = p["role_bucket"]
        tags = "".join([" (wk)" if p.get("is_keeper") else "",
                         " [XI]" if p["player_id"] in xi_ids else ""])
        lines.append(f"  {i:2d}. {p['name']:<22s} {role:<12s}{tags:<10s} {p['score']:>5.1f}/100")
        for sentence in p.get("reasoning", []):
            lines.append(_wrap(f"- {sentence}"))
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

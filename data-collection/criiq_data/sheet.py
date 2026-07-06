from __future__ import annotations

from . import advanced, impact, matchups, opponents, phases, player_card, venue_stats
from .logging_utils import get_logger

log = get_logger("sheet")


def find_player(conn, like: str):
    return conn.execute(
        "SELECT p.player_id, p.canonical_name, COUNT(DISTINCT mp.match_id) AS m "
        "FROM players p JOIN identifier_map im ON im.identifier=p.cricsheet_identifier "
        "JOIN match_players mp ON mp.player_name=im.player_name "
        "WHERE p.canonical_name LIKE ? GROUP BY p.player_id ORDER BY m DESC LIMIT 1",
        (like,)).fetchone()


def _best_phase(phase_rows):
    ranked = [p for p in phase_rows if p.get("bat_team_rank")]
    if not ranked:
        return None
    best = min(ranked, key=lambda p: p["bat_team_rank"])
    return {"phase": best["phase"], "strike_rate": best["bat_strike_rate"],
            "team_rank": best["bat_team_rank"], "team_size": best["bat_team_size"],
            "team_percentile": best["bat_team_percentile"]}


def _summary(card, career, imp, vs_opp, best_phase, bogey) -> list[str]:
    out = []
    idn = card["identity"] if card else {}
    bits = [b for b in [idn.get("nationality"), idn.get("role"),
                        f"age {idn.get('age')}" if idn.get("age") else None] if b]
    if bits:
        out.append(" | ".join(str(b) for b in bits))
    st = card.get("status") if card else None
    if st:
        sbits = [f"Status: {st.get('retirement_status', 'UNKNOWN')}"]
        if st.get("retirement_date"):
            sbits.append(f"since {st['retirement_date']}")
        if st.get("icc_rank"):
            sbits.append(f"ICC rank #{st['icc_rank']}")
        if st.get("career_phase"):
            sbits.append(st["career_phase"])
        out.append(" | ".join(sbits))
    if imp:
        out.append(f"Importance {imp['importance_score']}/100 - "
                   f"wins {imp['win_pct']}% of matches featured, {imp['player_of_match']} PotM")
    if career:
        b = career.get("batting", {})
        if b.get("runs"):
            out.append(f"Batting: {b['runs']} runs @ avg {b['average']}, SR {b['strike_rate']} "
                       f"(HS {b['high_score']}, {b['fifties']}x50, {b['hundreds']}x100)")
        bw = career.get("bowling")
        if bw:
            out.append(f"Bowling: {bw['wickets']} wkts @ econ {bw['economy']}, "
                       f"avg {bw['average']}, best {bw['best_bowling']}")
    if imp and imp.get("top_order_scalps"):
        out.append(f"Wicket impact: {imp['top_order_scalps']} top-order scalps, "
                   f"avg stand broken {imp['avg_partnership_broken']}")
    if imp and (imp.get("setting_strike_rate") or imp.get("chasing_strike_rate")):
        out.append(f"Setting SR {imp.get('setting_strike_rate')} vs chasing SR "
                   f"{imp.get('chasing_strike_rate')}")
    if best_phase:
        out.append(f"Best batting phase: {best_phase['phase']} (SR {best_phase['strike_rate']}, "
                   f"ranks #{best_phase['team_rank']} of {best_phase['team_size']} in own team)")
    if vs_opp:
        best = max(vs_opp, key=lambda r: (r.get("runs") or 0) + (r.get("wickets") or 0) * 20)
        out.append(f"Standout opponent: {best['opponent']} "
                   f"({best.get('runs',0)} runs, {best.get('wickets',0)} wkts in {best['matches']} matches)")
    if bogey and bogey.get("overall"):
        b = bogey["overall"][0]
        out.append(f"Bogey bowler: {b['bowler_name']} ({b['bowler_team']}) - "
                   f"out {b['dismissals']}x in {b['balls']} balls")
    return out


def get_sheet(conn, player_id: str, fmt: str, top_opponents: int = 8) -> dict:
    card = player_card.get_card(conn, player_id, fmt)
    career = card.get("career") if card else None
    imp = impact.get_impact(conn, player_id, fmt)
    adv = advanced.get_advanced(conn, player_id, fmt)
    vs_opp = opponents.get_vs_opponent(conn, player_id, fmt)
    phase_rows = phases.get_phases(conn, player_id, fmt)
    best_phase = _best_phase(phase_rows)
    bogey = matchups.top_dismissers(conn, player_id, fmt)
    venues = venue_stats.get_by_venue(conn, player_id, fmt)

    return {
        "identity": card.get("identity") if card else None,
        "status": card.get("status") if card else None,
        "selector_summary": _summary(card, career, imp, vs_opp, best_phase, bogey),
        "career": career,
        "impact": imp,
        "strengths": adv.get("strengths") if adv else [],
        "phase_breakdown": phase_rows,
        "best_batting_phase_in_team": best_phase,
        "phase_vs_opponent": phases.phase_vs_opponent(conn, player_id, fmt),
        "record_vs_opponent": vs_opp[:top_opponents],
        "bogey_bowlers": bogey,
        "by_venue": venues,
        "last_match": card.get("latest_match") if card else None,
        "format": fmt,
    }

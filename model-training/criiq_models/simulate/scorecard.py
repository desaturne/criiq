"""post-match scorecards (batting + bowling) and a coach's-eye narrative,
derived from a simulated ball log and a name lookup. no team-specific
logic, so this works for any two sides/genders/formats.
"""
from __future__ import annotations

import pandas as pd


def batting_scorecard(ball_log_df: pd.DataFrame, name_map: dict | None = None) -> list:
    """one row per batter who came to the crease, in batting order.
    strike rate is `runs / balls_faced * 100`, balls faced excludes wides.
    `highlight`, when present, flags a standout performance.
    """
    name_map = name_map or {}
    order: list = []
    runs: dict = {}
    balls: dict = {}
    dismissed: dict = {}
    for _, row in ball_log_df.iterrows():
        striker = row["striker"]
        if striker not in runs:
            runs[striker], balls[striker] = 0, 0
            order.append(striker)
        if row["runs_off_bat"]:
            runs[striker] += int(row["runs_off_bat"])
        if row["outcome"] != "wide":
            balls[striker] += 1
        if row["is_wicket"] and row["dismissed"] == striker:
            dismissed[striker] = True

    rows = []
    for pid in order:
        b, r = balls[pid], runs[pid]
        rows.append({
            "player_id": pid, "name": name_map.get(pid, pid), "runs": r, "balls": b,
            "strike_rate": round(100 * r / b, 1) if b else None,
            "status": "out" if pid in dismissed else "not out", "highlight": None,
        })

    if rows:
        top = max(rows, key=lambda r: r["runs"])
        for r in rows:
            if r["runs"] >= 100:
                r["highlight"] = f"Century! ({r['runs']} off {r['balls']})"
            elif r["runs"] >= 50:
                r["highlight"] = f"Half-century ({r['runs']} off {r['balls']})"
        if top["highlight"] is None and top["runs"] > 0:
            top["highlight"] = f"Top scorer ({top['runs']} off {top['balls']})"
        settled = [r for r in rows if r["balls"] >= 10]
        if settled:
            fastest = max(settled, key=lambda r: r["strike_rate"] or 0)
            if fastest["highlight"] is None:
                fastest["highlight"] = f"Fastest scoring innings (SR {fastest['strike_rate']})"
    return rows


def bowling_scorecard(ball_log_df: pd.DataFrame, name_map: dict | None = None) -> list:
    """one row per bowler used, in order of first over bowled. overs are
    `b//6.b%6` notation, economy is `6 * runs_conceded / legal_balls`.
    byes/leg-byes are excluded from runs conceded.
    """
    name_map = name_map or {}
    order: list = []
    balls: dict = {}
    conceded: dict = {}
    wkts: dict = {}
    for _, row in ball_log_df.iterrows():
        bowler = row["bowler"]
        if bowler not in balls:
            balls[bowler], conceded[bowler], wkts[bowler] = 0, 0, 0
            order.append(bowler)
        if row["is_legal"]:
            balls[bowler] += 1
        if row["outcome"] != "bye":
            conceded[bowler] += int(row["runs_total"])
        if row["is_wicket"]:
            wkts[bowler] += 1

    rows = []
    for pid in order:
        b = balls[pid]
        rows.append({
            "player_id": pid, "name": name_map.get(pid, pid), "overs": f"{b // 6}.{b % 6}",
            "runs_conceded": conceded[pid], "wickets": wkts[pid],
            "economy": round(6 * conceded[pid] / b, 2) if b else None, "highlight": None,
        })

    if rows:
        best = max(rows, key=lambda r: (r["wickets"], -(r["economy"] if r["economy"] is not None else 999)))
        if best["wickets"] > 0:
            best["highlight"] = f"Pick of the bowlers ({best['wickets']}-for-{best['runs_conceded']})"
        qualified = [r for r in rows if int(r["overs"].split(".")[0]) >= 2]
        if qualified:
            tightest = min(qualified, key=lambda r: r["economy"] if r["economy"] is not None else 999)
            if tightest["highlight"] is None:
                tightest["highlight"] = f"Most economical (ER {tightest['economy']})"
    return rows


def render_scorecard_text(team_name: str, batting_rows: list, bowling_rows: list, opponent_name: str) -> str:
    lines = [f"{team_name} batting:"]
    lines.append(f"  {'batter':<22}{'runs':>6}{'balls':>7}{'SR':>8}  ")
    for r in batting_rows:
        note = f"  -- {r['highlight']}" if r["highlight"] else ""
        sr = f"{r['strike_rate']:.1f}" if r["strike_rate"] is not None else "-"
        lines.append(f"  {r['name']:<22}{r['runs']:>6}{r['balls']:>7}{sr:>8}  ({r['status']}){note}")

    lines.append(f"\n{opponent_name} bowling:")
    lines.append(f"  {'bowler':<22}{'overs':>7}{'runs':>6}{'wkts':>6}{'econ':>7}")
    for r in bowling_rows:
        note = f"  -- {r['highlight']}" if r["highlight"] else ""
        econ = f"{r['economy']:.2f}" if r["economy"] is not None else "-"
        lines.append(f"  {r['name']:<22}{r['overs']:>7}{r['runs_conceded']:>6}{r['wickets']:>6}{econ:>7}{note}")
    return "\n".join(lines)


def bowling_rotation(ball_log_df: pd.DataFrame, name_map: dict | None = None) -> list:
    """over-by-over breakdown: which bowler bowled each over, its phase,
    and that over's runs conceded/wickets. one row per over.
    """
    name_map = name_map or {}
    rows = []
    for over, g in ball_log_df.sort_values(["over", "ball_in_over"]).groupby("over", sort=True):
        bowler = g["bowler"].iloc[0]
        rows.append({
            "over": int(over) + 1, "phase": g["phase"].iloc[0] if "phase" in g.columns else None,
            "bowler_id": bowler, "bowler": name_map.get(bowler, bowler),
            "balls": int(g["is_legal"].sum()),
            "runs_conceded": int(g.loc[g["outcome"] != "bye", "runs_total"].sum()),
            "wickets": int(g["is_wicket"].sum()),
        })
    return rows


_PHASE_ORDER = ("powerplay", "middle", "death")


def bowling_phase_summary(rotation_rows: list) -> dict:
    """`{phase: {bowler_name: {"balls","runs","wickets","overs","economy"}}}`,
    aggregating `bowling_rotation`'s per-over rows by bowler and phase.
    """
    summary: dict = {}
    for row in rotation_rows:
        phase = row["phase"] or "unknown"
        entry = summary.setdefault(phase, {}).setdefault(
            row["bowler"], {"balls": 0, "runs": 0, "wickets": 0})
        entry["balls"] += row["balls"]
        entry["runs"] += row["runs_conceded"]
        entry["wickets"] += row["wickets"]
    for bowlers in summary.values():
        for e in bowlers.values():
            e["overs"] = f"{e['balls'] // 6}.{e['balls'] % 6}"
            e["economy"] = round(6 * e["runs"] / e["balls"], 2) if e["balls"] else None
    return summary


def render_bowling_rotation_text(team_name: str, rotation_rows: list, phase_summary: dict) -> str:
    lines = [f"{team_name} bowling rotation (over by over):"]
    for row in rotation_rows:
        phase = row["phase"] or "?"
        lines.append(f"  over {row['over']:2d} ({phase:9s}): {row['bowler']:<22s}"
                      f"{row['balls']}b  {row['runs_conceded']}r  {row['wickets']}w")

    lines.append(f"\n{team_name} bowling by phase:")
    for phase in _PHASE_ORDER:
        bowlers = phase_summary.get(phase)
        if not bowlers:
            continue
        lines.append(f"  {phase}:")
        for name, e in sorted(bowlers.items(), key=lambda kv: -kv[1]["balls"]):
            econ = f"{e['economy']:.2f}" if e["economy"] is not None else "-"
            lines.append(f"    {name:<22s}{e['overs']:>6} overs  {e['runs']:>3d} runs  "
                          f"{e['wickets']} wkts  econ {econ}")
    return "\n".join(lines)


def coach_perspective(rep: dict, key_moments: list, coach_team: str, name_map: dict | None = None) -> str:
    """a short, coach's-eye read of one simulated rep from `coach_team`'s
    side. works for either side, no hardcoded team names.
    """
    lines = []
    coach_bats_first = rep["batting_first_team"] == coach_team
    opponent = rep["bowling_first_team"] if coach_bats_first else rep["batting_first_team"]
    coach_innings = 1 if coach_bats_first else 2

    if coach_bats_first:
        lines.append(f"{coach_team} set the total: {rep['first_innings_score']}/{rep['first_innings_wickets']} "
                      f"off 20 overs, leaving {opponent} to chase {rep['target']}.")
    else:
        lines.append(f"Chasing {rep['target']} against {opponent}, {coach_team} finished "
                      f"{rep['second_innings_score']}/{rep['second_innings_wickets']}.")

    bat_highlights = [m["description"] for m in key_moments
                       if m["type"] == "batting_milestone" and m["innings"] == coach_innings]
    if bat_highlights:
        lines.append("With the bat: " + "; ".join(bat_highlights) + ".")

    bowl_innings = 2 if coach_bats_first else 1
    bowl_highlights = [m["description"] for m in key_moments
                        if m["type"] in ("bowling_milestone", "hat_trick") and m["innings"] == bowl_innings]
    if bowl_highlights:
        lines.append("With the ball: " + "; ".join(bowl_highlights) + ".")

    swings = [m for m in key_moments if m["type"] == "turning_point"]
    if swings:
        biggest = max(swings, key=lambda m: abs((m.get("win_prob_after") or 0.5) - (m.get("win_prob_before") or 0.5)))
        lines.append(f"The moment that decided it: {biggest['description']} "
                      f"(innings {biggest['innings']}, over {biggest['over']}.{biggest['ball']}).")

    if rep["winner"] == "Tie":
        lines.append("Result: Tied, resolved by Super Over.")
    else:
        lines.append(f"Result: {'A win' if rep['winner'] == coach_team else 'A loss'} for {coach_team} "
                      f"({rep['winner']} won the match).")
    return "\n".join(lines)

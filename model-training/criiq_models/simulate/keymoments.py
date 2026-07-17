"""Milestone / highlight detection over a simulated ball-by-ball log.

The user explicitly wants the simulation to surface key moments the way real
match commentary/scorecards do, not just a final win-probability line graph.
Everything here is derived from columns `engine.py` already tracks per ball
-- no extra state, just running per-batter/per-bowler totals over the log
in order.
"""
from __future__ import annotations

import pandas as pd

_BATTING_MILESTONES = (50, 100, 150, 200)
_BOWLING_MILESTONES = (3, 4, 5)


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _name_lookup(name_map: dict | None, player_id: str) -> str:
    return (name_map or {}).get(player_id, player_id)


def _batting_milestones(df: pd.DataFrame, name_map: dict | None) -> list:
    moments = []
    running: dict = {}
    crossed: dict = {}
    for _, row in df.iterrows():
        if not row["runs_off_bat"]:
            continue
        pid = row["striker"]
        running[pid] = running.get(pid, 0) + int(row["runs_off_bat"])
        already = crossed.setdefault(pid, set())
        for m in _BATTING_MILESTONES:
            if running[pid] >= m and m not in already:
                already.add(m)
                label = "century" if m == 100 else ("half-century" if m == 50 else f"{m}")
                moments.append({
                    "over": int(row["over"]), "ball": int(row["ball_in_over"]), "innings": int(row["innings"]),
                    "type": "batting_milestone",
                    "description": f"{_name_lookup(name_map, pid)} reaches {m} ({label})",
                    "win_prob_before": None, "win_prob_after": row.get("win_prob_batting"),
                })
    return moments


def _boundaries(df: pd.DataFrame, name_map: dict | None) -> list:
    moments = []
    for _, row in df[df["outcome"].isin(("4", "6"))].iterrows():
        moments.append({
            "over": int(row["over"]), "ball": int(row["ball_in_over"]), "innings": int(row["innings"]),
            "type": "boundary",
            "description": f"{_name_lookup(name_map, row['striker'])} hits a {row['outcome']} "
                            f"(score {int(row['score'])}/{int(row['wickets'])})",
            "win_prob_before": None, "win_prob_after": row.get("win_prob_batting"),
        })
    return moments


def _bowling_milestones_and_hattricks(df: pd.DataFrame, name_map: dict | None) -> list:
    """3/4/5-fers, plus hat-trick detection: 3 wickets off 3 consecutive
    *legal* deliveries by the same bowler. A wide/no-ball is not a "ball" in
    the formal sense (it's replayed, doesn't count toward the over -- see
    rulebook-cricket.md §4.1/§4.2), so one intervening between two wickets
    does NOT break a hat-trick under real cricket scoring convention; this
    is why the sequence is checked over legal deliveries only, not the raw
    delivery stream. Only within-innings sequences count (T20 is one innings
    per side per match, so no cross-innings hat-tricks apply here).
    """
    moments = []
    for innings, inn_df in df.groupby("innings"):
        wickets_so_far: dict = {}
        crossed: dict = {}
        legal = inn_df[inn_df["is_legal"]].reset_index(drop=True)
        recent_wicket_bowlers: list = []  # sliding window of last 3 legal balls' (bowler, is_wicket)
        for _, row in legal.iterrows():
            bowler = row["bowler"]
            if row["is_wicket"]:
                wickets_so_far[bowler] = wickets_so_far.get(bowler, 0) + 1
                already = crossed.setdefault(bowler, set())
                for m in _BOWLING_MILESTONES:
                    if wickets_so_far[bowler] >= m and m not in already:
                        already.add(m)
                        moments.append({
                            "over": int(row["over"]), "ball": int(row["ball_in_over"]), "innings": int(innings),
                            "type": "bowling_milestone",
                            "description": f"{_name_lookup(name_map, bowler)} takes their "
                                            f"{_ordinal(m)} wicket ({m}-for)",
                            "win_prob_before": None, "win_prob_after": row.get("win_prob_batting"),
                        })
            recent_wicket_bowlers.append((bowler, bool(row["is_wicket"])))
            if len(recent_wicket_bowlers) > 3:
                recent_wicket_bowlers.pop(0)
            if len(recent_wicket_bowlers) == 3:
                same_bowler = len({b for b, _ in recent_wicket_bowlers}) == 1
                all_wickets = all(w for _, w in recent_wicket_bowlers)
                if same_bowler and all_wickets:
                    moments.append({
                        "over": int(row["over"]), "ball": int(row["ball_in_over"]), "innings": int(innings),
                        "type": "hat_trick",
                        "description": f"HAT-TRICK for {_name_lookup(name_map, bowler)}!",
                        "win_prob_before": None, "win_prob_after": row.get("win_prob_batting"),
                    })
    return moments


def _biggest_swings(df: pd.DataFrame, top_n: int, name_map: dict | None) -> list:
    if "win_prob_batting" not in df.columns or df.empty:
        return []
    # `win_prob_batting` is relative to whichever team is *currently*
    # batting, and that team flips at the innings break -- a plain `.diff()`
    # across the whole log would score the innings-1-to-innings-2 boundary
    # as one giant "swing", when it's really just two different reference
    # frames being subtracted. Reset the diff per innings (on a stable
    # chronological sort) so only genuine within-innings swings are ranked.
    d = df.copy().sort_values(["innings", "over", "ball_in_over"]).reset_index(drop=True)
    d["delta_wp"] = d.groupby("innings")["win_prob_batting"].diff().fillna(0.0)
    top = d.reindex(d["delta_wp"].abs().sort_values(ascending=False).index[:top_n])
    moments = []
    for _, row in top.sort_values(["innings", "over", "ball_in_over"]).iterrows():
        moments.append({
            "over": int(row["over"]), "ball": int(row["ball_in_over"]), "innings": int(row["innings"]),
            "type": "turning_point",
            "description": f"Big swing: {row['outcome']} by {_name_lookup(name_map, row['striker'])} "
                            f"off {_name_lookup(name_map, row['bowler'])} "
                            f"({row['delta_wp']*100:+.1f}pp win probability)",
            "win_prob_before": round(row["win_prob_batting"] - row["delta_wp"], 4),
            "win_prob_after": row["win_prob_batting"],
        })
    return moments


def detect_key_moments(ball_log_df: pd.DataFrame, name_map: dict | None = None,
                        top_swings: int = 5) -> list:
    """Ordered (by innings, over, ball) list of `{over, ball, innings, type,
    description, win_prob_before, win_prob_after}` dicts covering batting
    milestones (50/100/150/200), every boundary, bowling milestones
    (3/4/5-for) and hat-tricks, and the biggest single-ball win-probability
    swings in the match.
    """
    if ball_log_df is None or ball_log_df.empty:
        return []
    moments = (
        _batting_milestones(ball_log_df, name_map)
        + _boundaries(ball_log_df, name_map)
        + _bowling_milestones_and_hattricks(ball_log_df, name_map)
        + _biggest_swings(ball_log_df, top_swings, name_map)
    )
    return sorted(moments, key=lambda m: (m["innings"], m["over"], m["ball"]))

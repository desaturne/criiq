from __future__ import annotations

import io
import json
import zipfile

import pytest

from criiq_data import (career, identity, impact, ingest, matchups, ml_features,
                        opponents, phases, player_card, rankings, registry, venue_stats)
from criiq_data.config import CricsheetSource
from criiq_data.db import connect, init_schema
from criiq_data.h2h import batter_vs_bowler, names_for_player
from criiq_data.ingest import _parse_info, _shape_deliveries
from criiq_data.validate import validate_deliveries
import pandas as pd


def _add_match(conn, mid, date, t1, t2, winner, team_type="international"):
    conn.execute(
        "INSERT INTO matches(match_id, format, gender, date, team1, team2, winner, "
        "venue_raw, venue_id, team_type) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (mid, "T20", "female", date, t1, t2, winner, "Test Ground", "test-ground", team_type))


def _add_player_meta(conn, name, ident, key_cricinfo):
    conn.execute("INSERT INTO identifier_map(player_name, identifier) VALUES(?,?)",
                 (name, ident))
    conn.execute("INSERT INTO people(identifier, name, unique_name, key_cricinfo) "
                 "VALUES(?,?,?,?)", (ident, name, name, key_cricinfo))


def _add_match_player(conn, mid, team, name):
    conn.execute("INSERT INTO match_players(match_id, team, player_name) VALUES(?,?,?)",
                 (mid, team, name))


def _ball(conn, mid, inn, over, b, bat_team, bowl_team, striker, nonstr, bowler,
          runs, wkt=None, dismissed=None):
    conn.execute(
        "INSERT INTO deliveries(match_id, innings, over, ball_in_over, batting_team, "
        "bowling_team, striker, non_striker, bowler, runs_off_bat, extras, wides, "
        "noballs, runs_total, wicket_type, player_dismissed) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (mid, inn, over, b, bat_team, bowl_team, striker, nonstr, bowler,
         runs, 0, 0, 0, runs, wkt, dismissed))


def _cricsheet_zip(matches: list[dict]) -> bytes:
    """Builds a minimal real-shaped Cricsheet csv2 zip in memory -- one
    `{match_id}.csv` (deliveries) + `{match_id}_info.csv` (info) pair per
    match -- so `ingest_source` is exercised against the actual file format,
    not a shortcut fixture.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for m in matches:
            info_lines = [
                f"info,team,{m['team1']}", f"info,team,{m['team2']}",
                f"info,gender,{m['gender']}", "info,match_type,T20",
                f"info,team_type,{m['team_type']}", f"info,date,{m['date']}",
                f"info,winner,{m['team1']}",
                f"info,player,{m['team1']},{m['striker']}",
                f"info,player,{m['team2']},{m['victim']}",
                f"info,registry,people,{m['striker']},{m['striker_id']}",
                f"info,registry,people,{m['victim']},{m['victim_id']}",
            ]
            z.writestr(f"{m['match_id']}_info.csv", "\n".join(info_lines) + "\n")

            header = ("match_id,innings,ball,batting_team,bowling_team,striker,"
                      "non_striker,bowler,runs_off_bat,extras,wides,noballs,"
                      "wicket_type,player_dismissed")
            rows = [
                f"{m['match_id']},1,0.1,{m['team1']},{m['team2']},{m['striker']},"
                f"Non Striker,Some Bowler,4,0,0,0,,",
                f"{m['match_id']},2,0.1,{m['team2']},{m['team1']},{m['victim']},"
                f"Other Partner,{m['striker']},0,0,0,0,bowled,{m['victim']}",
            ]
            z.writestr(f"{m['match_id']}.csv", header + "\n" + "\n".join(rows) + "\n")
    return buf.getvalue()


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    init_schema(c)

    _add_player_meta(c, "AA Batter", "id_bat", "111")
    _add_player_meta(c, "BB Bowler", "id_bowl", "222")
    _add_player_meta(c, "DD Old", "id_old", "333")
    c.execute("INSERT INTO identifier_map(player_name, identifier) VALUES(?,?)",
              ("EE NoKey", "id_nokey"))
    c.execute("INSERT INTO people(identifier, name, unique_name, key_cricinfo) "
              "VALUES(?,?,?,?)", ("id_nokey", "EE NoKey", "EE NoKey", None))

    _add_match(c, "M1", "2024-01-01", "Team A", "Team B", "Team A")
    for t, n in [("Team A", "AA Batter"), ("Team A", "DD Old"),
                 ("Team A", "EE NoKey"), ("Team B", "BB Bowler")]:
        _add_match_player(c, "M1", t, n)
    seq = [1, 0, 4, 2, 0]
    for i, r in enumerate(seq):
        _ball(c, "M1", 1, 0, i + 1, "Team A", "Team B", "AA Batter", "DD Old", "BB Bowler", r)
    _ball(c, "M1", 1, 0, 6, "Team A", "Team B", "AA Batter", "DD Old", "BB Bowler",
          0, wkt="bowled", dismissed="AA Batter")

    _add_match(c, "M2", "2025-06-01", "Team A", "Team B", "Team A")
    for t, n in [("Team A", "AA Batter"), ("Team B", "BB Bowler")]:
        _add_match_player(c, "M2", t, n)
    for i, r in enumerate([6, 6, 0, 1]):
        _ball(c, "M2", 1, 1, i + 1, "Team A", "Team B", "AA Batter", "x", "BB Bowler", r)

    c.commit()
    identity.resolve_players(c)
    yield c
    c.close()


def test_player_id_stable():
    assert identity.player_id_for("id_bat") == identity.player_id_for("id_bat")
    assert identity.player_id_for("id_bat") != identity.player_id_for("id_bowl")


def test_identity_join_attaches_cricinfo(conn):
    row = conn.execute("SELECT key_cricinfo, needs_review, resolution_method "
                       "FROM players WHERE cricsheet_identifier='id_bat'").fetchone()
    assert row["key_cricinfo"] == "111"
    assert row["needs_review"] == 0
    assert row["resolution_method"] == "register"


def test_identity_missing_cricinfo_flagged(conn):
    row = conn.execute("SELECT key_cricinfo, needs_review FROM players "
                       "WHERE cricsheet_identifier='id_nokey'").fetchone()
    assert row["key_cricinfo"] is None
    assert row["needs_review"] == 1


def test_derived_role(conn):
    bat = conn.execute("SELECT derived_role FROM players WHERE cricsheet_identifier='id_bat'").fetchone()
    assert bat["derived_role"] == "batter"


def test_h2h_batter_vs_bowler(conn):
    bat, bat_gender = names_for_player(conn, identity.player_id_for("id_bat"))
    bowl, bowl_gender = names_for_player(conn, identity.player_id_for("id_bowl"))
    h = batter_vs_bowler(conn, "T20", bat, bowl, bat_gender, bowl_gender)
    assert h["balls"] == 10
    assert h["runs"] == 20
    assert h["dismissals"] == 1
    assert h["dismissal_rate"] == pytest.approx(0.1, abs=1e-6)


def test_registry_conservative_and_recency(conn):
    registry.build_registry_for_format(conn, "T20")
    aa = conn.execute("SELECT * FROM player_registry WHERE player_id=?",
                      (identity.player_id_for("id_bat"),)).fetchone()
    assert aa["retirement_status"] == "ACTIVE"
    assert aa["last_appearance_date"] == "2025-06-01"
    assert aa["recall_flag"] == 0

    dd = conn.execute("SELECT * FROM player_registry WHERE player_id=?",
                      (identity.player_id_for("id_old"),)).fetchone()
    assert dd["last_appearance_date"] == "2024-01-01"
    assert dd["recall_flag"] == 1


def test_recall_flag_never_overrides_a_genuinely_inactive_player(tmp_path):
    # Real bug found via a live-DB demo check: "RK Parwin" last appeared for
    # India in 2012 (>13 years before the most recent match in the data) yet
    # kept surfacing in 2026 team recommendations. Root cause: recall_flag's
    # old formula (`days_since > recall_flag_days`, 180) fires for *every*
    # unranked INACTIVE player, since inactive_window_days (1095) is larger
    # than recall_flag_days -- roster.py's INACTIVE exclusion checks
    # `recall_flag==0`, so it was silently defeated for anyone unranked.
    c = connect(tmp_path / "recall.db")
    init_schema(c)
    _add_player_meta(c, "Old Timer", "id_stale", "801")
    _add_player_meta(c, "Current Star", "id_current", "802")
    _add_match(c, "R1", "2012-10-03", "Team A", "Team B", "Team A")
    _add_match_player(c, "R1", "Team A", "Old Timer")
    _add_match(c, "R2", "2026-06-10", "Team A", "Team B", "Team A")
    _add_match_player(c, "R2", "Team A", "Current Star")
    c.commit()
    identity.resolve_players(c)

    registry.build_registry_for_format(c, "T20")
    old = c.execute("SELECT * FROM player_registry WHERE player_id=?",
                    (identity.player_id_for("id_stale"),)).fetchone()
    assert old["retirement_status"] == "INACTIVE"
    assert old["recall_flag"] == 0   # must not silently re-enable eligibility
    c.close()


def test_domestic_activity_flagged_without_faking_the_international_status(tmp_path):
    # The user's exact scenario: gone quiet internationally, but still
    # playing -- just domestically. An earlier version of this fix made the
    # *status label itself* domestic-aware, which was wrong: a genuinely
    # INACTIVE-internationally player showed as "ACTIVE", which is a lie a
    # selector could act on. The corrected design: `retirement_status` stays
    # an honest, international-only fact; `recent_domestic_activity` is a
    # separate, explicit flag consumed by model-training's roster.py for
    # eligibility -- it must never overwrite the status label.
    c = connect(tmp_path / "domform.db")
    init_schema(c)
    _add_player_meta(c, "OO OldStar", "id_oldstar", "901")
    _add_player_meta(c, "PP TrulyGone", "id_gone", "902")
    # Both players' only international appearance: the same old match.
    _add_match(c, "D1", "2022-01-01", "India", "Australia", "India",
               team_type="international")
    _add_match_player(c, "D1", "India", "OO OldStar")
    _add_match_player(c, "D1", "India", "PP TrulyGone")
    # Only OO OldStar has a recent domestic appearance; PP TrulyGone has none.
    _add_match(c, "D2", "2025-12-20", "Some Franchise", "Other Franchise",
               "Some Franchise", team_type="club")
    _add_match_player(c, "D2", "Some Franchise", "OO OldStar")
    c.commit()
    identity.resolve_players(c)

    registry.build_registry_for_format(c, "T20")
    star = c.execute("SELECT * FROM player_registry WHERE player_id=?",
                      (identity.player_id_for("id_oldstar"),)).fetchone()
    gone = c.execute("SELECT * FROM player_registry WHERE player_id=?",
                      (identity.player_id_for("id_gone"),)).fetchone()

    # `days_since_last_appearance` (informational, union-based) still
    # follows the domestic appearance...
    assert star["days_since_last_appearance"] == 0
    # ...but the STATUS is a true international fact: her only international
    # appearance was ~3 years 11 months before as-of (2025-12-20), well past
    # inactive_window_days -- she genuinely is INACTIVE internationally, and
    # the label must say so, not "ACTIVE".
    assert star["retirement_status"] == "INACTIVE"
    # The distinct, honest carve-out flag: this is what tells model-training
    # she shouldn't be silently excluded, without lying about her status.
    assert star["recent_domestic_activity"] == 1
    # The control: no domestic follow-up at all -- genuinely stale, and no
    # carve-out flag either.
    assert gone["retirement_status"] == "INACTIVE"
    assert gone["recent_domestic_activity"] == 0
    c.close()


def test_winprob_empirical_learns_and_calibrates():
    from criiq_data.winprob import EmpiricalWinProb
    # Synthetic chase: the batting team wins iff the ask is gettable
    # (runs_required <= balls_remaining), plus a losing set of hopeless states.
    rows = []
    for rem in range(6, 120, 6):
        for wk in range(0, 8):
            rows += [{"innings": 2, "balls_remaining": rem, "wickets": wk,
                      "runs_required": rem // 2, "balls_bowled": 120 - rem,
                      "score": 0, "label_batting_team_won": 1}] * 5
            rows += [{"innings": 2, "balls_remaining": rem, "wickets": wk,
                      "runs_required": rem * 2, "balls_bowled": 120 - rem,
                      "score": 0, "label_batting_team_won": 0}] * 5
    balls = pd.DataFrame(rows)
    model = EmpiricalWinProb(alpha=1.0).fit(balls)

    # query the buckets the training actually covered: gettable ask (rem//2) wins,
    # a doubled ask (rem*2) is hopeless
    easy = pd.DataFrame([{"innings": 2, "balls_remaining": 60, "wickets": 2,
                          "runs_required": 30, "balls_bowled": 60, "score": 0}])
    hard = pd.DataFrame([{"innings": 2, "balls_remaining": 12, "wickets": 6,
                          "runs_required": 24, "balls_bowled": 108, "score": 0}])
    p_easy = model.predict(easy)[0]
    p_hard = model.predict(hard)[0]
    assert 0.0 <= p_hard < 0.5 < p_easy <= 1.0     # gettable > hopeless
    # predict preserves row order / length for a batch
    batch = pd.concat([easy, hard], ignore_index=True)
    both = model.predict(batch)
    assert len(both) == 2 and both[0] == pytest.approx(p_easy) and both[1] == pytest.approx(p_hard)


def test_winprob_save_load_roundtrip(tmp_path, monkeypatch):
    from criiq_data import winprob
    monkeypatch.setattr(winprob, "MODELS_DIR", tmp_path)
    balls = pd.DataFrame([
        {"innings": 2, "balls_remaining": 30, "wickets": 3, "runs_required": 20,
         "balls_bowled": 90, "score": 0, "label_batting_team_won": 1},
        {"innings": 1, "balls_remaining": 90, "wickets": 1, "runs_required": None,
         "balls_bowled": 30, "score": 45, "label_batting_team_won": 0},
    ] * 20)
    m = winprob.EmpiricalWinProb().fit(balls)
    m.save("T20", "female")
    loaded = winprob.EmpiricalWinProb.load("T20", "female")
    q = pd.DataFrame([{"innings": 2, "balls_remaining": 30, "wickets": 3,
                       "runs_required": 20, "balls_bowled": 90, "score": 0}])
    assert loaded.predict(q)[0] == pytest.approx(m.predict(q)[0])


def test_wpa_credits_striker_and_debits_bowler(conn, tmp_path, monkeypatch):
    from criiq_data import wpa, winprob

    monkeypatch.setattr(winprob, "MODELS_DIR", tmp_path)
    model = winprob.EmpiricalWinProb()
    model.grids = {
        # M1 (innings 1), bin widths BALLS_BIN=6/SCORE_BIN=10: balls 1-5 (score
        # 1..7, balls_bowled 1..5) all land on (k_bowled=0, k_wk=0, k_score=0).
        # Ball 6 is both the over's 6th ball *and* the wicket ball, so it moves
        # to (k_bowled=1, k_wk=1, k_score=0) -- a clean, hand-verifiable single
        # win-probability swing to test attribution on.
        "set_full": pd.DataFrame([
            {"k_bowled": 0, "k_wk": 0, "k_score": 0, "wp": 0.55},
            {"k_bowled": 1, "k_wk": 1, "k_score": 0, "wp": 0.45},
        ]),
        "set_coarse": pd.DataFrame(columns=["k_bowled", "k_wk", "wp"]),
        "chase_full": pd.DataFrame(columns=["k_rem", "k_wk", "k_rr", "wp"]),
        "chase_coarse": pd.DataFrame(columns=["k_rem", "k_wk", "wp"]),
    }
    model.save("T20", "female")

    wpa.build_wpa_for_format(conn, "T20")

    bat_id = identity.player_id_for("id_bat")
    bowl_id = identity.player_id_for("id_bowl")

    m1_bat = conn.execute(
        "SELECT batting_wpa FROM player_match_wpa WHERE player_id=? AND match_id='M1'",
        (bat_id,)).fetchone()
    m1_bowl = conn.execute(
        "SELECT bowling_wpa FROM player_match_wpa WHERE player_id=? AND match_id='M1'",
        (bowl_id,)).fetchone()

    # only the wicket ball moves the bucket (0.55 -> 0.45): every prior ball
    # in the over lands on the same bucket, so their deltas are exactly zero.
    assert m1_bat["batting_wpa"] == pytest.approx(-0.10)
    # the bowling team's probability moved the opposite way, by construction.
    assert m1_bowl["bowling_wpa"] == pytest.approx(0.10)

    phase_row = conn.execute(
        "SELECT matches, batting_wpa_per_match FROM player_phase_wpa "
        "WHERE player_id=? AND format='T20' AND phase='powerplay'", (bat_id,)).fetchone()
    assert phase_row is not None and phase_row["matches"] >= 1


def test_domestic_matches_tagged_and_kept_out_of_international_phase_wpa(conn, tmp_path, monkeypatch):
    from criiq_data import wpa, winprob

    monkeypatch.setattr(winprob, "MODELS_DIR", tmp_path)
    model = winprob.EmpiricalWinProb()
    model.grids = {
        "set_full": pd.DataFrame([
            {"k_bowled": 0, "k_wk": 0, "k_score": 0, "wp": 0.55},
            {"k_bowled": 1, "k_wk": 1, "k_score": 0, "wp": 0.45},
        ]),
        "set_coarse": pd.DataFrame(columns=["k_bowled", "k_wk", "wp"]),
        "chase_full": pd.DataFrame(columns=["k_rem", "k_wk", "k_rr", "wp"]),
        "chase_coarse": pd.DataFrame(columns=["k_rem", "k_wk", "wp"]),
    }
    model.save("T20", "female")

    # AA Batter already has an international match (M1, from the shared
    # fixture); add a domestic one for her too, same shape as M1's over.
    _add_match(conn, "D1", "2025-07-01", "Some Franchise", "Other Franchise",
               "Some Franchise", team_type="club")
    _add_match_player(conn, "D1", "Some Franchise", "AA Batter")
    _add_match_player(conn, "D1", "Other Franchise", "BB Bowler")
    seq = [1, 0, 4, 2, 0]
    for i, r in enumerate(seq):
        _ball(conn, "D1", 1, 0, i + 1, "Some Franchise", "Other Franchise",
              "AA Batter", "DD Old", "BB Bowler", r)
    _ball(conn, "D1", 1, 0, 6, "Some Franchise", "Other Franchise",
          "AA Batter", "DD Old", "BB Bowler", 0, wkt="bowled", dismissed="AA Batter")
    conn.commit()

    wpa.build_wpa_for_format(conn, "T20")
    wpa.build_domestic_form_for_format(conn, "T20")
    bat_id = identity.player_id_for("id_bat")

    d1_row = conn.execute(
        "SELECT team_type, batting_wpa FROM player_match_wpa WHERE player_id=? AND match_id='D1'",
        (bat_id,)).fetchone()
    assert d1_row["team_type"] == "club"
    assert d1_row["batting_wpa"] == pytest.approx(-0.10)

    m1_row = conn.execute(
        "SELECT team_type FROM player_match_wpa WHERE player_id=? AND match_id='M1'",
        (bat_id,)).fetchone()
    assert m1_row["team_type"] == "international"

    # player_phase_wpa (the international career aggregate) must not blend in
    # D1 -- still just the 2 international matches from the shared fixture
    # (M1 and M2, both int'l), not 3.
    phase_row = conn.execute(
        "SELECT matches FROM player_phase_wpa WHERE player_id=? AND format='T20' "
        "AND phase='powerplay'", (bat_id,)).fetchone()
    assert phase_row["matches"] == 2

    dom_row = conn.execute(
        "SELECT matches, batting_wpa_per_match FROM player_domestic_form "
        "WHERE player_id=? AND format='T20'", (bat_id,)).fetchone()
    assert dom_row["matches"] == 1
    assert dom_row["batting_wpa_per_match"] == pytest.approx(-0.10)


def test_registry_flags_inconsistent_selection(tmp_path):
    # Team A plays 10 matches in one recent season. A regular is picked for all
    # of them (ACTIVE); an in-and-out player is picked for only 2 (INCONSISTENT).
    c = connect(tmp_path / "sel.db")
    init_schema(c)
    _add_player_meta(c, "Reg Regular", "id_reg", "901")
    _add_player_meta(c, "Ino Inout", "id_ino", "902")
    for i in range(10):
        mid = f"S{i}"
        date = f"2025-{(i // 4) + 1:02d}-{(i % 4) * 7 + 1:02d}"
        _add_match(c, mid, date, "Team A", "Team B", "Team A")
        _add_match_player(c, mid, "Team A", "Reg Regular")
        if i < 2:                      # Ino appears in only 2 of the 10 matches
            _add_match_player(c, mid, "Team A", "Ino Inout")
    c.commit()
    identity.resolve_players(c)

    registry.build_registry_for_format(c, "T20")
    reg = c.execute("SELECT * FROM player_registry WHERE player_id=?",
                    (identity.player_id_for("id_reg"),)).fetchone()
    assert reg["retirement_status"] == "ACTIVE"
    assert reg["activity_signal"] == "regular_selection"
    assert reg["selection_rate"] == 1.0
    assert reg["window_team_matches"] == 10

    ino = c.execute("SELECT * FROM player_registry WHERE player_id=?",
                    (identity.player_id_for("id_ino"),)).fetchone()
    assert ino["retirement_status"] == "INCONSISTENT"
    assert ino["activity_signal"] == "in_and_out"
    assert ino["selection_rate"] == 0.2
    c.close()


def test_player_card_contents(conn):
    registry.build_registry_for_format(conn, "T20")
    player_card.build_cards_for_format(conn, "T20")
    card = player_card.get_card(conn, identity.player_id_for("id_bat"), "T20")
    assert card is not None
    assert card["latest_match"]["date"] == "2025-06-01"
    assert card["latest_match"]["batting"]["runs"] == 13
    assert card["latest_match"]["batting"]["not_out"] is True
    assert card["form"]["last_innings"] == [7, 13]
    assert card["form"]["rfi"] == pytest.approx((13 + 0.85 * 7) / 1.85, abs=0.1)
    assert 0 < card["impact"]["runs_share"] <= 1
    assert card["impact"]["win_contribution"] == 1.0
    assert card["matches_played"] == 2
    assert card["career"]["batting"]["runs"] == 20
    assert "bowling" not in card["career"]
    ms = card["latest_match"]["match_summary"]
    assert ms["teams"] == ["Team A", "Team B"]
    assert ms["totals"]["Team A"] == 13
    assert ms["winner"] == "Team A"


def test_vs_opponent_record(conn):
    opponents.build_vs_opponent_for_format(conn, "T20")
    aa = conn.execute(
        "SELECT * FROM player_vs_opponent WHERE player_id=? AND opponent='Team B'",
        (identity.player_id_for("id_bat"),)).fetchone()
    assert aa["matches"] == 2 and aa["won"] == 2 and aa["win_pct"] == 100.0
    assert aa["runs"] == 20 and aa["bat_average"] == 20.0
    assert aa["bat_strike_rate"] == 200.0 and aa["high_score"] == 13
    assert aa["dismissals"] == 1


def test_impact_metrics(conn):
    impact.build_impact_for_format(conn, "T20")
    aa = conn.execute("SELECT * FROM player_impact WHERE player_id=?",
                      (identity.player_id_for("id_bat"),)).fetchone()
    assert aa["win_pct"] == 100.0
    assert aa["bat_contribution_pct"] == 100.0
    assert aa["setting_strike_rate"] == 200.0
    assert aa["importance_score"] == 60.0

    bb = conn.execute("SELECT * FROM player_impact WHERE player_id=?",
                      (identity.player_id_for("id_bowl"),)).fetchone()
    assert bb["top_order_scalps"] == 1
    assert bb["avg_partnership_broken"] == 7.0


def test_importance_score_batting_bonus_symmetric_with_bowling(tmp_path):
    c = connect(tmp_path / "sym.db")
    init_schema(c)
    _add_player_meta(c, "CC AllRounder", "id_ar", "901")
    for mid, date in [("S1", "2025-01-01"), ("S2", "2025-01-08")]:
        _add_match(c, mid, date, "Team A", "Team B", "Team A")
        c.execute("UPDATE matches SET player_of_match=? WHERE match_id=?", ("CC AllRounder", mid))
        _add_match_player(c, mid, "Team A", "CC AllRounder")
        # Innings 1: Team A bats, CC alone scores 30 -- her whole team's total,
        # so bat_contribution_pct comes out at exactly 100%.
        for b, runs in enumerate([4, 4, 4, 4, 4, 10], start=1):
            _ball(c, mid, 1, 0, b, "Team A", "Team B", "CC AllRounder", "ZZ Partner", "YY Bowler", runs)
        # Innings 2: Team B bats, CC bowls a full 2-over spell (12 legal
        # balls, 0 runs conceded off any of them -- economy 0.0, well under
        # the economical-spell threshold) and removes the opening (top-order)
        # batter on the first ball -- the team's only wicket, so
        # bowl_contribution_pct is 100% too. A full spell (not just one ball)
        # is needed so this fixture qualifies for *both* new bowling-bonus
        # sub-parts (wicket-rate and economy), not just the wicket one.
        _ball(c, mid, 2, 0, 1, "Team B", "Team A", "XX Victim", "WW Partner", "CC AllRounder",
              0, wkt="bowled", dismissed="XX Victim")
        for over in range(2):
            for b in range(1, 7):
                if over == 0 and b == 1:
                    continue  # the wicket ball, already added above
                _ball(c, mid, 2, over, b, "Team B", "Team A", "WW Partner", "VV Partner",
                      "CC AllRounder", 0)
    c.commit()
    identity.resolve_players(c)
    impact.build_impact_for_format(c, "T20")

    row = c.execute("SELECT * FROM player_impact WHERE player_id=?",
                     (identity.player_id_for("id_ar"),)).fetchone()
    comps = json.loads(row["importance_components"])
    # A 30+ run innings every match (rate 1.0), a top-order wicket every
    # match (rate 1.0), and an economical (0.0/over) spell every match
    # (rate 1.0) all hit their respective caps -- wicket-rate and economy
    # split the bowling bonus 7.5/7.5 (see impact.py), matching batting's
    # 15.0 combined: before the batting bonus fix, batting_impact_part
    # didn't exist at all; before the economy split, economy counted for
    # nothing and bowling_impact_part was 100% wicket-driven.
    assert comps["wicket_rate_part"] == 7.5
    assert comps["economy_part"] == 7.5
    assert comps["bowling_impact_part"] == 15.0
    assert comps["batting_impact_part"] == 15.0
    # 35 (contribution, capped) + 25 (100% win rate) + 25 (100% PotM rate,
    # capped) + 15 + 15 = 115, clamped to the intended 0-100 scale.
    assert row["importance_score"] == 100.0
    c.close()


def test_ingest_tags_team_type_and_keeps_within_cutoff_data_in_production(tmp_path, monkeypatch):
    c = connect(tmp_path / "ing.db")
    init_schema(c)
    monkeypatch.setattr(ingest, "RAW_DIR", tmp_path)
    payload = _cricsheet_zip([{
        "match_id": "9001", "team1": "Some Club", "team2": "Other Club",
        "gender": "female", "team_type": "club", "date": "2025-03-01",
        "striker": "Domestic Player", "victim": "Domestic Victim",
        "striker_id": "id_domestic", "victim_id": "id_domvictim",
    }])
    src = CricsheetSource("T20", "female", "domestic_test.zip")
    (tmp_path / src.filename).write_bytes(payload)

    result = ingest.ingest_source(c, src)
    assert result["new_matches"] == 1
    assert result["holdout_matches"] == 0

    row = c.execute("SELECT * FROM matches WHERE match_id='9001'").fetchone()
    assert row is not None
    assert row["team_type"] == "club"
    assert c.execute("SELECT COUNT(*) FROM matches_holdout").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM deliveries WHERE match_id='9001'").fetchone()[0] == 2
    c.close()


def test_ingest_routes_matches_after_data_cutoff_to_holdout_tables(tmp_path, monkeypatch):
    c = connect(tmp_path / "ing2.db")
    init_schema(c)
    monkeypatch.setattr(ingest, "RAW_DIR", tmp_path)
    from criiq_data.config import SETTINGS
    after_cutoff = "2026-06-16"
    assert after_cutoff > SETTINGS.data_cutoff_date
    payload = _cricsheet_zip([{
        "match_id": "9002", "team1": "India", "team2": "Australia",
        "gender": "female", "team_type": "international", "date": after_cutoff,
        "striker": "Future Player", "victim": "Future Victim",
        "striker_id": "id_future", "victim_id": "id_futurevictim",
    }])
    src = CricsheetSource("T20", "female", "future_test.zip")
    (tmp_path / src.filename).write_bytes(payload)

    result = ingest.ingest_source(c, src)
    assert result["new_matches"] == 1
    assert result["holdout_matches"] == 1

    assert c.execute("SELECT COUNT(*) FROM matches WHERE match_id='9002'").fetchone()[0] == 0
    hrow = c.execute("SELECT * FROM matches_holdout WHERE match_id='9002'").fetchone()
    assert hrow is not None
    assert hrow["team_type"] == "international"
    assert c.execute("SELECT COUNT(*) FROM deliveries WHERE match_id='9002'").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM deliveries_holdout WHERE match_id='9002'").fetchone()[0] == 2
    assert c.execute("SELECT COUNT(*) FROM match_players_holdout WHERE match_id='9002'").fetchone()[0] == 2

    # Re-running ingest against the same zip must not duplicate the holdout
    # rows -- `_existing_match_ids` has to see holdout matches too.
    ingest.ingest_source(c, src)
    assert c.execute("SELECT COUNT(*) FROM deliveries_holdout WHERE match_id='9002'").fetchone()[0] == 2
    c.close()


def test_venue_record(conn):
    venue_stats.build_for_format(conn, "T20")
    aa = conn.execute(
        "SELECT * FROM player_by_venue WHERE player_id=? AND venue_id='test-ground'",
        (identity.player_id_for("id_bat"),)).fetchone()
    assert aa["matches"] == 2 and aa["runs"] == 20
    assert aa["bat_strike_rate"] == 200.0
    # Both M1 and M2 (the shared fixture) have her batting in innings=1
    # (batting first/setting) -- no chasing innings recorded for her at all.
    assert aa["setting_runs"] == 20 and aa["setting_balls"] == 10
    assert aa["chasing_runs"] is None and aa["chasing_balls"] is None


def test_venue_setting_vs_chasing_distinguishes_innings(tmp_path):
    c = connect(tmp_path / "sitvenue.db")
    init_schema(c)
    _add_player_meta(c, "AA Batter", "id_bat", "111")
    _add_player_meta(c, "BB Bowler", "id_bowl", "222")
    _add_match(c, "S1", "2024-01-01", "Team A", "Team B", "Team A")
    _add_match_player(c, "S1", "Team A", "AA Batter")
    _add_match_player(c, "S1", "Team B", "BB Bowler")
    for i, r in enumerate([4, 4, 4]):  # batting first (innings=1): 12 off 3
        _ball(c, "S1", 1, 0, i + 1, "Team A", "Team B", "AA Batter", "x", "BB Bowler", r)

    _add_match(c, "S2", "2024-02-01", "Team B", "Team A", "Team A")
    _add_match_player(c, "S2", "Team A", "AA Batter")
    _add_match_player(c, "S2", "Team B", "BB Bowler")
    for i, r in enumerate([1, 1]):  # chasing (innings=2): 2 off 2
        _ball(c, "S2", 2, 0, i + 1, "Team A", "Team B", "AA Batter", "x", "BB Bowler", r)
    c.commit()
    identity.resolve_players(c)

    venue_stats.build_for_format(c, "T20")
    row = c.execute(
        "SELECT * FROM player_by_venue WHERE player_id=? AND venue_id='test-ground'",
        (identity.player_id_for("id_bat"),)).fetchone()
    assert row["setting_runs"] == 12 and row["setting_balls"] == 3
    assert row["chasing_runs"] == 2 and row["chasing_balls"] == 2
    c.close()


def test_dismissal_matchup(conn):
    matchups.build_for_format(conn, "T20")
    row = conn.execute(
        "SELECT * FROM dismissal_matchup WHERE batter_id=? AND bowler_id=?",
        (identity.player_id_for("id_bat"), identity.player_id_for("id_bowl"))).fetchone()
    assert row["dismissals"] == 1 and row["balls"] == 10
    bogey = matchups.top_dismissers(conn, identity.player_id_for("id_bat"), "T20")
    assert bogey["overall"][0]["bowler_name"] == "BB Bowler"
    assert bogey["worst_bowler_per_opponent"]["Team B"]["dismissals"] == 1


def test_venue_dismissal_matchup(conn):
    matchups.build_venue_matchups_for_format(conn, "T20")
    row = conn.execute(
        "SELECT * FROM venue_dismissal_matchup WHERE batter_id=? AND bowler_id=? AND venue_id='test-ground'",
        (identity.player_id_for("id_bat"), identity.player_id_for("id_bowl"))).fetchone()
    assert row["dismissals"] == 1 and row["balls"] == 10
    top = matchups.top_dismissers_at_venue(
        conn, identity.player_id_for("id_bat"), "T20", "test-ground")
    assert top[0]["bowler_name"] == "BB Bowler"


def test_phase_intra_team_rank(conn):
    phases.build_for_format(conn, "T20")
    rows = phases.get_phases(conn, identity.player_id_for("id_bat"), "T20")
    assert rows
    pp = [r for r in rows if r["phase"] == "powerplay"]
    assert pp and pp[0]["bat_runs"] == 20


def test_match_features_winloss(conn):
    ml_features.build_match_features_for_format(conn, "T20")
    m2 = conn.execute("SELECT * FROM match_features WHERE match_id='M2'").fetchone()
    assert m2["label_team1_won"] == 1            # Team A won M2
    assert m2["team1_form_winpct"] == 1.0        # Team A won the prior match M1
    assert m2["team1_avg_score"] == 7.0          # Team A scored 7 in M1


def test_player_match_impact(conn):
    ml_features.build_player_match_impact_for_format(conn, "T20")
    row = conn.execute("SELECT * FROM player_match_impact WHERE player_id=? AND match_id='M2'",
                       (identity.player_id_for("id_bat"),)).fetchone()
    assert row["runs"] == 13 and row["won"] == 1
    assert row["bat_contribution_pct"] == 100.0  # AA scored all of Team A's runs

    # BB Bowler M1: 6 balls [1,0,4,2,0,0(wkt)] -- 3 dots, 1 boundary, 1 wicket.
    m1 = conn.execute("SELECT * FROM player_match_impact WHERE player_id=? AND match_id='M1'",
                       (identity.player_id_for("id_bowl"),)).fetchone()
    assert m1["bowl_dot_pct"] == 50.0 and m1["bowl_boundary_pct"] == 16.7
    assert m1["bowl_strike_rate"] == 6.0

    # BB Bowler M2: 4 balls [6,6,0,1] -- 1 dot, 2 boundaries, 0 wickets ->
    # strike rate is None (undefined), not a divide-by-zero 0.
    m2 = conn.execute("SELECT * FROM player_match_impact WHERE player_id=? AND match_id='M2'",
                       (identity.player_id_for("id_bowl"),)).fetchone()
    assert m2["bowl_dot_pct"] == 25.0 and m2["bowl_boundary_pct"] == 50.0
    assert m2["bowl_strike_rate"] is None


def test_ball_state(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(ml_features, "FEATURES_DIR", tmp_path)
    n = ml_features.build_ball_state_for_format(conn, "T20")
    assert n == 10                               # 6 balls in M1 + 4 in M2
    df = pd.read_parquet(tmp_path / "ball_state_T20.parquet")
    assert "label_batting_team_won" in df.columns
    assert int(df["score"].max()) == 13
    assert int(df["label_batting_team_won"].max()) == 1


def test_status_and_age_helpers():
    from criiq_data.registry import _status, _career_phase, _age_advisory, _category
    assert _status(True, 9999) == "ACTIVE"
    assert _status(False, 100) == "ACTIVE"
    assert _status(False, 2000) == "INACTIVE"
    assert _status(False, 800) == "UNKNOWN"
    assert _career_phase(40, "batter") == "DECLINING"
    assert _career_phase(28, "batter") == "PEAK"
    assert _career_phase(20, "pace") == "EMERGING"
    assert _age_advisory(39, "pace") == 1
    assert _age_advisory(39, "batter") == 0
    assert _category("Bowler", "Right-arm fast") == "pace"
    assert _category("Wicketkeeper batter", None) == "keeper"


def test_classify_selection_consistency():
    from criiq_data.registry import _classify
    # a current ICC ranking always confirms ACTIVE, whatever the selection rate
    assert _classify(True, 100, 0.1) == ("ACTIVE", "icc_ranked",
                                         "present in current ICC rankings")
    # recent + regularly picked -> ACTIVE
    assert _classify(False, 100, 0.9)[0] == "ACTIVE"
    assert _classify(False, 100, 0.9)[1] == "regular_selection"
    # recent but rarely picked -> INCONSISTENT (in-and-out)
    status, signal, reason = _classify(False, 100, 0.2)
    assert status == "INCONSISTENT"
    assert signal == "in_and_out"
    assert "20%" in reason
    # exactly at the regular threshold counts as ACTIVE; just below is INCONSISTENT
    from criiq_data.config import SETTINGS
    thr = SETTINGS.regular_selection_rate
    assert _classify(False, 100, thr)[0] == "ACTIVE"
    assert _classify(False, 100, round(thr - 0.05, 3))[0] == "INCONSISTENT"
    # recent but sample too small to judge consistency -> stays ACTIVE
    assert _classify(False, 100, None) == ("ACTIVE", "recent_appearance",
                                           "appeared inside active window")
    # long absence -> INACTIVE regardless of a stale selection rate
    assert _classify(False, 2000, 0.9)[0] == "INACTIVE"
    # aging gap, no ranking -> UNKNOWN
    assert _classify(False, 800, None)[0] == "UNKNOWN"


def test_registry_flags(conn):
    conn.execute("UPDATE players SET date_of_birth='1985-06-01' WHERE cricsheet_identifier='id_bat'")
    conn.commit()
    registry.build_registry_for_format(conn, "T20")
    aa = conn.execute("SELECT * FROM player_registry WHERE player_id=?",
                      (identity.player_id_for("id_bat"),)).fetchone()
    assert aa["retirement_status"] == "ACTIVE"     # last appearance is recent
    assert aa["age_advisory"] == 1                  # age 40 batter (>= 40)
    assert aa["career_phase"] == "DECLINING"


def test_rankings_load_marks_active(conn, tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("format,gender,discipline,rank,rating,player_name,key_cricinfo\n"
                 "T20,female,batting,1,800,AA Batter,111\n", encoding="utf-8")
    res = rankings.load_csv(conn, p)
    assert res["loaded"] == 1
    pid = identity.player_id_for("id_bat")
    rank = rankings.current_rank(conn, pid, "T20")
    assert rank["rank"] == 1
    assert rank["source"] == "manual_csv"
    assert rank["source_url"] == str(p)
    assert pid in rankings.ranked_ids(conn, "T20")

    registry.build_registry_for_format(conn, "T20")
    aa = conn.execute("SELECT * FROM player_registry WHERE player_id=?", (pid,)).fetchone()
    assert aa["retirement_status"] == "ACTIVE"
    assert aa["activity_signal"] == "icc_ranked"
    assert aa["status_reason"] == "present in current ICC rankings"
    assert aa["recall_flag"] == 0
    assert aa["icc_discipline"] == "batting"

    player_card.build_cards_for_format(conn, "T20")
    card = player_card.get_card(conn, pid, "T20")
    assert card["icc_ranking"]["ranked"] is True
    assert card["icc_ranking"]["best"]["discipline"] == "batting"
    assert card["status"]["activity_signal"] == "icc_ranked"



def test_rankings_parse_public_payload():
    payload = {"data": {"bat-rank": {"rank": [
        {"no": "1", "Player-name": "AA Batter", "Points": "800"},
        {"no": "2", "Player-name": "Someone Else", "Rating": "750"},
    ], "rank_date": "01 July 2026"}}}
    rows = rankings._response_rows(payload, fmt="T20", gender="female", discipline="batting")
    assert rows[0] == {
        "format": "T20",
        "gender": "female",
        "discipline": "batting",
        "rank": "1",
        "rating": "800",
        "player_name": "AA Batter",
        "key_cricinfo": "",
        "source": "icc_public_endpoint",
        "source_url": "",
        "rank_date": "01 July 2026",
        "extracted_at": "",
    }
    assert rows[1]["rating"] == "750"


def test_rankings_live_fetch_loads_mocked_public_feed(conn, tmp_path, monkeypatch):
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"bat-rank": {"rank": [
                {"no": "1", "Player-name": "AA Batter", "Points": "800"},
            ]}}}

    class FakeSession:
        def __init__(self):
            self.calls = []

        def get(self, url, params=None, headers=None, timeout=None):
            self.calls.append((url, params, headers, timeout))
            return FakeResponse()

    monkeypatch.setattr(rankings, "write_csv", lambda rows, path=None: str(tmp_path / "ignored.csv"))
    session = FakeSession()
    res = rankings.load_live(
        conn,
        client_id="public-test-client",
        source_url="https://example.test/cricket/v1/ranking",
        session=session,
    )
    assert res["fetched"] == 15
    assert res["loaded"] == 15
    assert res["source"] == "https://example.test/cricket/v1/ranking"
    assert session.calls[0][1]["client_id"] == "public-test-client"
    pid = identity.player_id_for("id_bat")
    assert rankings.current_rank(conn, pid, "T20")["rank"] == 1

def test_status_override(conn, tmp_path):
    from criiq_data import overrides
    p = tmp_path / "ov.csv"
    p.write_text("player_name,key_cricinfo,format,retirement_status,retirement_date,note\n"
                 "AA Batter,111,T20,RETIRED_FORMAT,2025-01-01,test\n", encoding="utf-8")
    overrides.load_csv(conn, p)
    registry.build_registry_for_format(conn, "T20")
    aa = conn.execute("SELECT * FROM player_registry WHERE player_id=?",
                      (identity.player_id_for("id_bat"),)).fetchone()
    assert aa["retirement_status"] == "RETIRED_FORMAT"   # override beats inference
    assert aa["retired_formats"] == "T20"
    assert aa["retirement_date"] == "2025-01-01"


def test_card_age_from_dob(conn):
    conn.execute("UPDATE players SET date_of_birth='2000-06-01' "
                 "WHERE cricsheet_identifier='id_bat'")
    conn.commit()
    registry.build_registry_for_format(conn, "T20")
    player_card.build_cards_for_format(conn, "T20")
    card = player_card.get_card(conn, identity.player_id_for("id_bat"), "T20")
    assert card["identity"]["age"] == 25.0


def test_career_table(conn):
    career.build_career_for_format(conn, "T20")
    aa = conn.execute("SELECT * FROM player_career WHERE player_id=?",
                      (identity.player_id_for("id_bat"),)).fetchone()
    assert aa["runs"] == 20 and aa["bat_innings"] == 2
    assert aa["bat_average"] == 20.0
    assert aa["bat_strike_rate"] == 200.0
    assert aa["high_score"] == 13
    assert aa["wickets"] is None

    bb = conn.execute("SELECT * FROM player_career WHERE player_id=?",
                      (identity.player_id_for("id_bowl"),)).fetchone()
    assert bb["balls_bowled"] == 10 and bb["wickets"] == 1
    assert bb["economy"] == 12.0
    assert bb["bowl_strike_rate"] == 10.0
    assert bb["best_bowling"] == "1/7"


SAMPLE_INFO = """version,2.3.0
info,team,Australia
info,team,New Zealand
info,gender,female
info,date,2017/02/17
info,match_type,T20
info,venue,Some Ground, Sometown
info,winner,Australia
info,winner_runs,40
info,player,Australia,MM Lanning
info,registry,people,MM Lanning,27e003ce
"""


def test_parse_info_handles_commas_in_venue():
    info = _parse_info(SAMPLE_INFO)
    assert info["teams"] == ["Australia", "New Zealand"]
    assert info["extra"]["venue"] == "Some Ground"
    assert info["extra"]["winner_runs"] == "40"
    assert ("MM Lanning", "27e003ce") in info["registry"]
    assert ("Australia", "MM Lanning") in info["players"]


def test_styles_classifiers():
    from criiq_data.styles import classify_bowling, classify_hand
    assert classify_bowling("Right-arm fast-medium") == "pace"
    assert classify_bowling("Legbreak googly") == "spin"
    assert classify_bowling("Slow left-arm orthodox") == "spin"
    assert classify_bowling(None) is None
    assert classify_hand("Right-hand bat") == "RHB"
    assert classify_hand("Left-hand bat") == "LHB"


def test_styles_bowling_detail():
    from criiq_data.styles import classify_bowling_detail as cbd
    assert cbd("Right-arm fast-medium") == "pace"
    assert cbd("Right-arm offbreak") == "off-spin"
    assert cbd("Legbreak googly") == "leg-spin"
    assert cbd("Slow left-arm orthodox") == "slow-left-arm"
    assert cbd("Left-arm wrist spin") == "leg-spin"      # chinaman-style -> wrist bucket
    assert cbd(None) is None


def test_wikipedia_infobox_parse():
    from criiq_data.styles import _infobox_field, classify_hand, classify_bowling_detail
    wikitext = (
        "{{Infobox cricketer\n"
        "| name = Some Player\n"
        "| batting = [[Right-handed batsman|Right-handed]]\n"
        "| bowling = Right-arm [[off break|offbreak]]<ref name=x/>\n"
        "| role = [[All-rounder]]\n"
        "}}\n")
    assert _infobox_field(wikitext, "batting") == "Right-handed"
    assert _infobox_field(wikitext, "bowling") == "Right-arm offbreak"
    assert classify_hand(_infobox_field(wikitext, "batting")) == "RHB"
    assert classify_bowling_detail(_infobox_field(wikitext, "bowling")) == "off-spin"


def test_advanced_profile_and_style_splits(conn):
    from criiq_data import advanced
    conn.execute("UPDATE players SET bowling_style='Right-arm fast' "
                 "WHERE cricsheet_identifier='id_bowl'")
    conn.execute("UPDATE players SET batting_hand='Right-hand bat' "
                 "WHERE cricsheet_identifier='id_bat'")
    conn.commit()
    advanced.build_for_format(conn, "T20")

    pa = advanced.get_advanced(conn, identity.player_id_for("id_bat"), "T20")
    assert pa["batting"]["runs"] == 20
    assert pa["batting"]["fours"] == 1
    assert pa["batting"]["sixes"] == 2
    assert "pace" in pa["batting"]["vs_bowling_type"]
    assert pa["batting"]["vs_bowling_type"]["pace"]["runs"] == 20
    # finer bowling-type split + surfaced batting hand
    assert pa["batting"]["vs_bowling_type_detail"]["pace"]["runs"] == 20
    assert pa["style"]["batting_hand"] == "RHB"
    assert isinstance(pa["strengths"], list) and pa["strengths"]

    pb = advanced.get_advanced(conn, identity.player_id_for("id_bowl"), "T20")
    assert "RHB" in pb["bowling"]["vs_batting_hand"]
    assert pb["bowling"]["wickets"] == 1
    assert pb["bowling"]["vs_batting_hand"]["RHB"]["strike_rate"] == 10.0
    assert pb["style"]["bowling_type"] == "pace"


def test_map_bowling_style_from_squad_page_role_text():
    from criiq_data.role_finalize import _map_bowling_style
    assert _map_bowling_style("Spin Bowler") == "spin"
    assert _map_bowling_style("Pace Bowler") == "pace"
    assert _map_bowling_style("Seam Bowler") == "pace"
    assert _map_bowling_style("Batter") is None
    assert _map_bowling_style("All-rounder") is None


def test_merge_external_roles_backfills_bowling_style_without_overwriting(conn):
    from criiq_data import role_finalize as rf

    pid = identity.player_id_for("id_bowl")
    key_cricinfo = "222"

    records = [{"key_cricinfo": key_cricinfo, "name": "BB Bowler", "is_keeper": False,
                "primary_role_override": "bowler", "bowling_style": "spin",
                "confidence": 95.0, "source_url": "https://en.wikipedia.org/wiki/Test"}]
    result = rf.merge_external_roles(conn, records, "T20")
    assert result["bowling_styles"] == 1

    row = conn.execute("SELECT bowling_style FROM player_styles WHERE player_id=?", (pid,)).fetchone()
    assert row["bowling_style"] == "spin"

    # a second merge with a *different* style must not clobber the existing value
    rf.merge_external_roles(conn, [{**records[0], "bowling_style": "pace"}], "T20")
    row = conn.execute("SELECT bowling_style FROM player_styles WHERE player_id=?", (pid,)).fetchone()
    assert row["bowling_style"] == "spin"


def test_colliding_identifier_splits_by_gender():
    """A single Cricsheet registry identifier reused across two genuinely
    different real people (one male, one female match) -- a confirmed,
    real quirk in this data, not a bug in this codebase's own matching (see
    identity.py's docstrings) -- must resolve to two distinct, stable
    player_ids, and their career stats must never blend.
    """
    c = connect(":memory:")
    init_schema(c)

    # Both "AS Female" and "AS Male" share the SAME underlying identifier
    # ("shared_id"), exactly like the real confirmed cases.
    c.execute("INSERT INTO identifier_map(player_name, identifier) VALUES(?,?)",
              ("AS Female", "shared_id"))
    c.execute("INSERT INTO identifier_map(player_name, identifier) VALUES(?,?)",
              ("AS Male", "shared_id"))
    c.execute("INSERT INTO people(identifier, name, unique_name, key_cricinfo) "
              "VALUES(?,?,?,?)", ("shared_id", "AS Female", "AS Female", "999"))

    c.execute(
        "INSERT INTO matches(match_id, format, gender, date, team1, team2, winner) "
        "VALUES('MF','T20','female','2024-01-01','Team A','Team B','Team A')")
    c.execute("INSERT INTO match_players(match_id, team, player_name) VALUES('MF','Team A','AS Female')")
    c.execute(
        "INSERT INTO deliveries(match_id, innings, over, ball_in_over, batting_team, "
        "bowling_team, striker, non_striker, bowler, runs_off_bat, extras, wides, "
        "noballs, runs_total) VALUES('MF',1,0,1,'Team A','Team B','AS Female','X','Y',4,0,0,0,4)")

    c.execute(
        "INSERT INTO matches(match_id, format, gender, date, team1, team2, winner) "
        "VALUES('MM','T20','male','2024-02-01','Team C','Team D','Team C')")
    c.execute("INSERT INTO match_players(match_id, team, player_name) VALUES('MM','Team C','AS Male')")
    c.execute(
        "INSERT INTO deliveries(match_id, innings, over, ball_in_over, batting_team, "
        "bowling_team, striker, non_striker, bowler, runs_off_bat, extras, wides, "
        "noballs, runs_total) VALUES('MM',1,0,1,'Team C','Team D','AS Male','X','Y',0,0,0,0,0)")
    c.commit()

    result = identity.resolve_players(c)
    assert result["split_identifiers"] == 1

    rows = c.execute(
        "SELECT player_id, gender, canonical_name FROM players WHERE cricsheet_identifier='shared_id'"
    ).fetchall()
    assert len(rows) == 2
    genders = {r["gender"] for r in rows}
    assert genders == {"female", "male"}
    assert len({r["player_id"] for r in rows}) == 2  # distinct, stable ids

    career.build_career_for_format(c, "T20")
    female_pid = next(r["player_id"] for r in rows if r["gender"] == "female")
    male_pid = next(r["player_id"] for r in rows if r["gender"] == "male")
    female_career = c.execute(
        "SELECT runs FROM player_career WHERE player_id=?", (female_pid,)).fetchone()
    male_career = c.execute(
        "SELECT runs FROM player_career WHERE player_id=?", (male_pid,)).fetchone()
    assert female_career["runs"] == 4    # only her own boundary, not blended with his 0
    assert male_career["runs"] == 0      # only his own dot ball, not blended with her 4
    c.close()


def test_batter_and_bowler_vs_team_breakdowns_include_safe_matchups(tmp_path):
    # A bowler who's contained a batter for 12 balls without ever dismissing
    # her used to be entirely invisible in dismissal_matchup (the old
    # `dismissals >= 1` filter) -- "never been dismissed by X" is exactly as
    # real a matchup fact as "X has dismissed her 3 times", and a batter
    # clicking into a matchup view should see both, not just the bogeymen.
    c = connect(tmp_path / "vs.db")
    init_schema(c)
    _add_player_meta(c, "AA Batter", "id_bat2", "701")
    _add_player_meta(c, "BB Dangerous", "id_bowl_d", "702")
    _add_player_meta(c, "CC Safe", "id_bowl_s", "703")

    _add_match(c, "V1", "2024-01-01", "Team A", "Team B", "Team A")
    for t, n in [("Team A", "AA Batter"), ("Team B", "BB Dangerous"), ("Team B", "CC Safe")]:
        _add_match_player(c, "V1", t, n)
    ball_no = 0
    for _ in range(7):
        ball_no += 1
        _ball(c, "V1", 1, 0, ball_no, "Team A", "Team B", "AA Batter", "x", "BB Dangerous", 1)
    ball_no += 1
    _ball(c, "V1", 1, 0, ball_no, "Team A", "Team B", "AA Batter", "x", "BB Dangerous",
          0, wkt="bowled", dismissed="AA Batter")
    for _ in range(12):
        ball_no += 1
        _ball(c, "V1", 1, 1, ball_no, "Team A", "Team B", "AA Batter", "x", "CC Safe", 4)
    c.commit()
    identity.resolve_players(c)
    matchups.build_for_format(c, "T20")

    bat_id = identity.player_id_for("id_bat2")
    dangerous_id = identity.player_id_for("id_bowl_d")
    safe_id = identity.player_id_for("id_bowl_s")

    result = matchups.batter_vs_team_bowlers(c, bat_id, "T20", "Team B")
    names = {b["bowler_name"] for b in result["bowlers"]}
    assert names == {"BB Dangerous", "CC Safe"}  # the safe bowler is no longer hidden
    assert result["bogey_bowler"]["bowler_name"] == "BB Dangerous"  # a real dismissal, not raw rate/volume, wins
    safe_entry = next(b for b in result["bowlers"] if b["bowler_name"] == "CC Safe")
    assert safe_entry["dismissals"] == 0
    assert safe_entry["balls"] == 12
    assert safe_entry["strike_rate"] == 400.0

    dangerous_view = matchups.bowler_vs_team_batters(c, dangerous_id, "T20", "Team A")
    assert dangerous_view["best_matchup"]["batter_name"] == "AA Batter"
    assert dangerous_view["best_matchup"]["wickets"] == 1

    safe_view = matchups.bowler_vs_team_batters(c, safe_id, "T20", "Team A")
    assert safe_view["most_expensive"]["batter_name"] == "AA Batter"
    assert safe_view["most_expensive"]["runs"] == 48
    assert safe_view["best_matchup"] is None  # never took a wicket -- no real "best matchup" to claim
    c.close()


def test_validate_deliveries_rejects_bad_rows():
    df = pd.DataFrame({
        "match_id": ["1", "1"], "innings": ["1", "1"], "ball": ["0.1", "0.2"],
        "batting_team": ["A", "A"], "bowling_team": ["B", "B"],
        "striker": ["X", ""], "non_striker": ["Y", "Y"], "bowler": ["Z", "Z"],
        "runs_off_bat": ["1", "x"], "extras": ["0", "0"],
    })
    clean, rejected = validate_deliveries(df, "1")
    assert len(clean) == 1
    assert len(rejected) == 1

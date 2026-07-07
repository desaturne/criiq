from __future__ import annotations

import pytest

from criiq_data import (career, identity, impact, matchups, ml_features, opponents,
                        phases, player_card, rankings, registry, venue_stats)
from criiq_data.db import connect, init_schema
from criiq_data.h2h import batter_vs_bowler, names_for_player
from criiq_data.ingest import _parse_info, _shape_deliveries
from criiq_data.validate import validate_deliveries
import pandas as pd


def _add_match(conn, mid, date, t1, t2, winner):
    conn.execute(
        "INSERT INTO matches(match_id, format, gender, date, team1, team2, winner, "
        "venue_raw, venue_id) VALUES(?,?,?,?,?,?,?,?,?)",
        (mid, "T20", "female", date, t1, t2, winner, "Test Ground", "test-ground"))


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
    bat = names_for_player(conn, identity.player_id_for("id_bat"))
    bowl = names_for_player(conn, identity.player_id_for("id_bowl"))
    h = batter_vs_bowler(conn, "T20", bat, bowl)
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


def test_venue_record(conn):
    venue_stats.build_for_format(conn, "T20")
    aa = conn.execute(
        "SELECT * FROM player_by_venue WHERE player_id=? AND venue_id='test-ground'",
        (identity.player_id_for("id_bat"),)).fetchone()
    assert aa["matches"] == 2 and aa["runs"] == 20
    assert aa["bat_strike_rate"] == 200.0


def test_dismissal_matchup(conn):
    matchups.build_for_format(conn, "T20")
    row = conn.execute(
        "SELECT * FROM dismissal_matchup WHERE batter_id=? AND bowler_id=?",
        (identity.player_id_for("id_bat"), identity.player_id_for("id_bowl"))).fetchone()
    assert row["dismissals"] == 1 and row["balls"] == 10
    bogey = matchups.top_dismissers(conn, identity.player_id_for("id_bat"), "T20")
    assert bogey["overall"][0]["bowler_name"] == "BB Bowler"
    assert bogey["worst_bowler_per_opponent"]["Team B"]["dismissals"] == 1


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
    assert isinstance(pa["strengths"], list) and pa["strengths"]

    pb = advanced.get_advanced(conn, identity.player_id_for("id_bowl"), "T20")
    assert "RHB" in pb["bowling"]["vs_batting_hand"]
    assert pb["bowling"]["wickets"] == 1


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

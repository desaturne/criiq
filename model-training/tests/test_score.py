from __future__ import annotations

from criiq_models.recommend.explain import explain
from criiq_models.recommend.score import RecommendationScorer
from tests.conftest import (add_appearance, add_bowler_matchup, add_match, add_match_impact,
                             add_match_wpa, register_player, set_career_bowling, set_date_of_birth,
                             set_player_profile)


def _seed_cold_start_player(conn):
    register_player(conn, "p1", "A Player", role="batter")
    for i, d in enumerate(["2024-01-01", "2024-02-01", "2024-03-01"]):
        mid = f"m{i}"
        add_match(conn, mid, d, "India", "Australia")
        add_match_impact(conn, "p1", mid, d, "India", "Australia", won=1,
                          bat_sr=110.0, bat_contrib=12.0)
    conn.execute("INSERT INTO player_impact(player_id, format, importance_score, win_pct, "
                 "potm_rate) VALUES('p1','T20',55.0,60.0,0.1)")
    conn.execute("INSERT INTO player_career(player_id, format, bat_average, bat_strike_rate) "
                 "VALUES('p1','T20',25.0,105.0)")
    conn.execute("INSERT INTO dismissal_matchup(format, batter_id, bowler_id, bowler_team, "
                 "balls, runs, dismissals) VALUES('T20','p1','bowler_x','Australia',30,20,1)")
    conn.commit()


def test_cold_start_skips_model_and_score_is_bounded(conn):
    _seed_cold_start_player(conn)
    scorer = RecommendationScorer(conn, "T20", "female", models={})
    scored = scorer.score("p1", "Australia")

    c = scored["components"]
    assert c["model_applied"] is False
    assert c["cold_start_reason"] is not None
    assert 0.0 <= scored["score"] <= 100.0

    parts_sum = (c["model_part"] + c["matchup_part"] + c["phase_fit_part"]
                 + c["standing_part"] + c["risk_part"] + c["strike_rate_part"]
                 + c["opponent_strength_part"])
    assert scored["score"] == round(max(0.0, min(100.0, parts_sum)), 1)


def test_cold_start_model_part_discounted_by_sample_size(conn):
    # model_part for a cold-start player is scaled by how much history backs
    # it, so a 3-match player can't post a near-full model_part. fixes the
    # real Aakash Chand over-rating (3 matches -> +12.5).
    register_player(conn, "p1", "Tiny Sample", role="bowler")
    for i, d in enumerate(["2024-01-01", "2024-02-01", "2024-03-01"]):
        mid = f"m{i}"
        add_match(conn, mid, d, "India", "Australia")
        add_match_impact(conn, "p1", mid, d, "India", "Australia", won=1,
                          economy=5.0, bowl_contrib=30.0, wickets=3, balls_bowled=24)
        add_match_wpa(conn, "p1", mid, bowling_wpa=0.10, date=d)  # strong small-sample WPA
    conn.commit()

    scorer = RecommendationScorer(conn, "T20", "female", models={})
    scored = scorer.score("p1", "Australia")
    c = scored["components"]
    assert c["model_applied"] is False               # 3 < min_matches_for_model (10)
    # 3 matches -> confidence 0.3, so model_part is at most 30% of the
    # undiscounted value, comfortably below a full-history player's ceiling.
    from criiq_models.config import SETTINGS
    assert c["model_part"] <= 45.0 * (3 / SETTINGS.min_matches_for_model) + 0.05


def test_strike_rate_penalty_scaled_down_by_game_awareness(conn):
    # modern T20I prizes strike rate: a player below the gender par is
    # penalized, but experience and game awareness scale that penalty down,
    # so an experienced anchor is largely forgiven while a raw low-SR player isn't.
    from criiq_models.features.current import ExtraContext
    scorer = RecommendationScorer(conn, "T20", "female", models={})
    scorer._priors["batter_sr_benchmark"] = 120.0

    aware_ctx = ExtraContext(importance_score=70.0, chasing_strike_rate=118.0, bat_consistency=0.8)
    pen_aware, aw = scorer._strike_rate_penalty({"career_bat_sr": 90.0, "career_matches": 80},
                                                 aware_ctx, "batter")
    raw_ctx = ExtraContext(importance_score=None, chasing_strike_rate=None, bat_consistency=None)
    pen_raw, aw_raw = scorer._strike_rate_penalty({"career_bat_sr": 90.0, "career_matches": 2},
                                                   raw_ctx, "batter")

    assert pen_aware < 0 and pen_raw < 0
    assert pen_raw < pen_aware                      # the raw player is penalized more
    assert aw["factor"] > aw_raw["factor"]

    # at/above par -> no penalty; pure bowler never penalized for batting SR
    assert scorer._strike_rate_penalty({"career_bat_sr": 130.0, "career_matches": 80}, aware_ctx, "batter")[0] == 0.0
    assert scorer._strike_rate_penalty({"career_bat_sr": 90.0, "career_matches": 2}, raw_ctx, "bowler")[0] == 0.0


def test_explain_mentions_player_and_opponent(conn):
    _seed_cold_start_player(conn)
    scorer = RecommendationScorer(conn, "T20", "female", models={})
    scored = scorer.score("p1", "Australia")
    payload = explain(scored)

    assert payload["player_id"] == "p1"
    assert any("A Player" in line for line in payload["summary"])
    assert any("Australia" in line for line in payload["summary"])


def test_explain_surfaces_archetype_batting_hand_and_bowling_style(conn):
    _seed_cold_start_player(conn)
    set_player_profile(conn, "p1", bowling_style="Right-arm off break",
                        batting_hand="Right handed", archetype="power hitter")
    scorer = RecommendationScorer(conn, "T20", "female", models={})
    scored = scorer.score("p1", "Australia")
    payload = explain(scored)

    inp = scored["components"]["inputs"]
    assert inp["archetype"] == "power hitter"
    assert inp["bowling_style"] == "Right-arm off break"
    assert inp["batting_hand"] == "Right handed"
    # messy real-world casing/spacing ("Right handed" vs "right-handed") is
    # normalized in the sentence itself, not just passed through raw.
    assert any("Right-handed power hitter." in line for line in payload["summary"])
    assert any("Bowls right-arm off break." in line for line in payload["summary"])


def test_explain_surfaces_batting_profile_best_phase_and_finisher_note(conn):
    # covers the "what to expect / best phase" enrichment, plus the note that
    # a strong finisher can still rate low since the score is win-probability
    # added, not raw hitting (the real "RM Ghosh" case).
    _seed_cold_start_player(conn)  # cold-start -> low model_part, like a real low WPA
    set_player_profile(conn, "p1", batting_hand="Right handed", archetype="finisher",
                        batting={"balls": 876, "strike_rate": 145.4, "boundary_pct": 21.8,
                                 "dot_pct": 36.6, "sixes": 45, "six_rate": 5.06,
                                 "by_phase": {"powerplay": {"balls": 100, "strike_rate": 90.0, "boundary_pct": 8.0},
                                              "death": {"balls": 510, "strike_rate": 165.9, "boundary_pct": 25.7}}})
    scorer = RecommendationScorer(conn, "T20", "female", models={})
    scored = scorer.score("p1", "Australia")
    payload = explain(scored)
    inp = scored["components"]["inputs"]
    summary = " ".join(payload["summary"])

    # raw batting profile numbers the coach asked to see
    assert inp["bat_strike_rate"] == 145.4 and inp["bat_sixes"] == 45
    assert "strike rate 145" in summary
    assert "45 career sixes" in summary
    assert "37% dot balls" in summary  # 36.6 rounds to 37
    # best phase / highest impact = the death overs (highest SR among phases)
    assert inp["bat_best_phase"] == "death"
    assert "Highest impact in the death overs" in summary
    assert "strike rate 166" in summary
    # a genuine finisher with low win-impact is flagged for a manual look,
    # not silently buried by a low rating.
    assert "manual look" in summary


def test_explain_tiny_batting_sample_does_not_get_a_profile_sentence(conn):
    # a tailender who faced a handful of balls must not get "expect strike
    # rate X" narrated from a 12-ball cameo, gated at 30 balls.
    _seed_cold_start_player(conn)
    set_player_profile(conn, "p1", archetype="balanced",
                        batting={"balls": 12, "strike_rate": 40.0, "boundary_pct": 0.0,
                                 "dot_pct": 75.0, "sixes": 0, "six_rate": 0.0, "by_phase": {}})
    scorer = RecommendationScorer(conn, "T20", "female", models={})
    payload = explain(scorer.score("p1", "Australia"))
    assert not any("With the bat, expect" in line for line in payload["summary"])


def test_explain_reasoning_has_no_dash_connectors(conn):
    # house style: no em-dash / en-dash connectors in coach-facing prose
    # (ordinary hyphens inside words like "Right-handed" are fine).
    _seed_cold_start_player(conn)
    set_player_profile(conn, "p1", bowling_style="Right-arm off break",
                        batting_hand="Right handed", archetype="finisher",
                        batting={"balls": 400, "strike_rate": 150.0, "boundary_pct": 22.0,
                                 "dot_pct": 35.0, "sixes": 30, "six_rate": 4.5,
                                 "by_phase": {"death": {"balls": 300, "strike_rate": 160.0, "boundary_pct": 24.0}}})
    scorer = RecommendationScorer(conn, "T20", "female", models={})
    alt = {"player_id": "p2", "name": "B Bench", "score": 4.2}
    payload = explain(scorer.score("p1", "Australia"), alternative=alt, slot="opener")
    for line in payload["summary"]:
        assert "—" not in line and "–" not in line, f"dash connector in: {line!r}"


def test_explain_surfaces_age_as_descriptive_context_not_a_model_feature(conn):
    # age_years was tried as a model feature and rejected (see
    # features/historical.py, no measurable improvement and a slight
    # regression in 3 of 4 cases), so it must stay narrative color only,
    # like bowl_dot_pct/bowl_boundary_pct.
    from criiq_models.features.schema import MODEL_FEATURES
    assert "age_years" not in MODEL_FEATURES

    _seed_cold_start_player(conn)
    set_date_of_birth(conn, "p1", "2000-01-01")
    scorer = RecommendationScorer(conn, "T20", "female", models={})
    scored = scorer.score("p1", "Australia")
    payload = explain(scored)

    inp = scored["components"]["inputs"]
    assert inp["age_years"] is not None
    assert any("years old" in line for line in payload["summary"])


def test_explain_omits_profile_sentences_when_data_is_missing(conn):
    # no set_player_profile call, so archetype/bowling_style/batting_hand stay
    # unset, same as most of the ~7000-player pool without Wikipedia enrichment.
    _seed_cold_start_player(conn)
    scorer = RecommendationScorer(conn, "T20", "female", models={})
    scored = scorer.score("p1", "Australia")
    payload = explain(scored)

    assert not any("Bowls " in line for line in payload["summary"])
    assert not any(line.endswith("power hitter.") or line.endswith("anchor.")
                   or line.endswith("finisher.") or line.endswith("balanced.")
                   for line in payload["summary"])
    assert not any("years old" in line for line in payload["summary"])


def test_explain_uses_no_gendered_pronouns(conn):
    # explain() used to hardcode "she"/"her", fine while the pool was
    # women's-only but a real bug once men's players flow through the same
    # path. no per-player pronoun is stored, so the fix is neutral phrasing
    # for everyone, not a second he/him branch.
    _seed_cold_start_player(conn)
    scorer = RecommendationScorer(conn, "T20", "male", models={})
    scored = scorer.score("p1", "Australia")
    payload = explain(scored, alternative={"player_id": "p2", "name": "B Bench", "score": 4.2},
                      slot="opener")

    lowered = " ".join(payload["summary"]).lower()
    for pronoun in (" she ", " she's ", " her ", " hers ", " he ", " he's ", " him ", " his "):
        assert pronoun not in f" {lowered} "


def test_explain_reports_comparison_against_next_best_alternative(conn):
    _seed_cold_start_player(conn)
    scorer = RecommendationScorer(conn, "T20", "female", models={})
    scored = scorer.score("p1", "Australia")

    alternative = {"player_id": "p2", "name": "B Bench", "score": 4.2}
    payload = explain(scored, alternative=alternative, slot="opener")

    assert any("B Bench" in line and "4.2" in line for line in payload["summary"])


def test_explain_reports_uncontested_pick_when_no_alternative_exists(conn):
    _seed_cold_start_player(conn)
    scorer = RecommendationScorer(conn, "T20", "female", models={})
    scored = scorer.score("p1", "Australia")

    payload = explain(scored, alternative=None, slot="bowler_tail")
    assert any("uncontested" in line.lower() for line in payload["summary"])


def test_bowler_side_matchup_rewards_wicket_rate_above_career_baseline(conn):
    register_player(conn, "p1", "C Bowler", role="bowler")
    set_career_bowling(conn, "p1", wickets=20, balls_bowled=400)  # career rate = 0.05

    register_player(conn, "opp1", "O Batter", role="batter")
    add_match(conn, "m_opp", "2024-06-01", "India", "Australia")
    add_appearance(conn, "m_opp", "Australia", "O Batter")

    # p1's wicket rate here (5/40=0.125) is well above her career rate
    # (0.05). previously impossible to credit, since the aggregate matchup
    # signal only looked at her batting history vs opponent bowlers, never
    # her bowling history vs opponent batters.
    add_bowler_matchup(conn, bowler_id="p1", batter_id="opp1", balls=40, runs=30, dismissals=5)

    scorer = RecommendationScorer(conn, "T20", "female", models={})
    scored = scorer.score("p1", "Australia")
    inp = scored["components"]["inputs"]

    assert inp["bowl_matchup_balls_vs_opponent_batters"] == 40
    assert inp["bowl_matchup_wicket_rate"] == 0.125
    assert inp["bowl_matchup_part"] > 0

    payload = explain(scored)
    assert any("bowled 40 balls" in line.lower() for line in payload["summary"])


def test_bowling_dot_and_boundary_pct_surface_as_descriptive_narrative(conn):
    register_player(conn, "p1", "C Bowler", role="bowler")
    for i, d in enumerate(["2024-01-01", "2024-02-01", "2024-03-01"]):
        mid = f"m{i}"
        add_match(conn, mid, d, "India", "Australia")
        add_match_impact(conn, "p1", mid, d, "India", "Australia", won=1,
                          economy=6.0, bowl_contrib=20.0, wickets=1, balls_bowled=24,
                          bowl_dot_pct=50.0, bowl_boundary_pct=8.0)
    conn.commit()

    scorer = RecommendationScorer(conn, "T20", "female", models={})
    scored = scorer.score("p1", "Australia")

    inp = scored["components"]["inputs"]
    assert inp["bowl_dot_pct"] == 50.0 and inp["bowl_boundary_pct"] == 8.0
    # descriptive only, must never affect the actual score/component points.
    assert "bowl_dot_pct" not in scored["components"]

    payload = explain(scored)
    assert any("dot ball" in line.lower() for line in payload["summary"])


def test_model_part_driven_by_wpa_not_contribution_share(conn):
    # the point of the WPA switch: a proven match-winner (high WPA, modest
    # contribution-share) must score above a fringe player with a flashier
    # share but near-zero WPA, the exact failure mode found here (a part-time
    # all-rounder outranking a proven opener).
    register_player(conn, "star", "Star Opener", role="batter")
    register_player(conn, "fringe", "Fringe Allrounder", role="all-rounder")

    for i, d in enumerate(["2021-01-01", "2021-06-01", "2022-01-01", "2022-06-01", "2023-01-01",
                           "2023-06-01", "2024-01-01", "2024-06-01", "2025-01-01", "2025-06-01"]):
        mid = f"star_m{i}"
        add_match(conn, mid, d, "India", "England")
        add_match_impact(conn, "star", mid, d, "India", "England", won=1, bat_contrib=15.0)
        add_match_wpa(conn, "star", mid, batting_wpa=0.08)  # consistently a genuine match-winner

    for i, d in enumerate(["2024-02-01", "2024-03-01", "2024-04-01"]):
        mid = f"fringe_m{i}"
        add_match(conn, mid, d, "India", "England")
        add_match_impact(conn, "fringe", mid, d, "India", "England", won=1, bat_contrib=20.0)
        add_match_wpa(conn, "fringe", mid, batting_wpa=-0.01)  # flashy share, near-zero real impact
    conn.commit()

    scorer = RecommendationScorer(conn, "T20", "female", models={})
    star = scorer.score("star", "England")
    fringe = scorer.score("fringe", "England")

    assert star["components"]["inputs"]["predicted_batting_wpa"] > 0
    assert fringe["components"]["inputs"]["predicted_batting_wpa"] < star["components"]["inputs"]["predicted_batting_wpa"]
    assert star["score"] > fringe["score"]


def test_score_many_applies_team_need_bonus_across_the_pool(conn):
    register_player(conn, "p1", "Player One", role="batter")
    register_player(conn, "p2", "Player Two", role="batter")
    conn.execute("INSERT INTO player_phase_wpa(player_id, format, phase, matches, "
                 "batting_wpa_per_match, bowling_wpa_per_match) VALUES "
                 "('benchmark','T20','death',10,0.0,0.0), "
                 "('p1','T20','death',10,-0.10,0.0), "  # pool average (-0.10+0.02)/2 = -0.04,
                 "('p2','T20','death',10,0.02,0.0)")     # still below benchmark despite p2's edge
    # the format-wide benchmark is scoped to the pool's own gender via real
    # match participation (see team_need.py), so "benchmark" needs a
    # matching gender-tagged match/WPA row to be included at all.
    add_match(conn, "m_benchmark", "2024-01-01", "Team A", "Team B", gender="female")
    add_match_wpa(conn, "benchmark", "m_benchmark", batting_wpa=0.0)
    conn.commit()

    scorer = RecommendationScorer(conn, "T20", "female", models={})
    scored = {s["player_id"]: s for s in scorer.score_many(["p1", "p2"], "England")}

    assert scored["p2"]["components"]["team_need_part"] > 0
    assert scored["p2"]["components"]["team_need_phase"] == "death"
    assert scored["p1"]["components"]["team_need_part"] == 0.0
    # score() alone (no pool context) must never apply a team-need bonus
    solo = scorer.score("p2", "England")
    assert solo["components"]["team_need_part"] == 0.0

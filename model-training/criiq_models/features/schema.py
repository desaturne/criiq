"""Canonical feature/target column names shared by historical (training) and
current (live scoring) feature builders — the trained model's input columns
must line up exactly between the two.
"""
from __future__ import annotations

NUMERIC_FEATURES = [
    "career_matches",
    "career_bat_contribution_pct",
    "career_bowl_contribution_pct",
    "career_bat_sr",
    "career_bowl_economy",
    "career_batting_wpa",
    "career_bowling_wpa",
    "career_bowl_wickets_per_match",
    "form_bat_contribution_pct",
    "form_bowl_contribution_pct",
    "form_bat_sr",
    "form_bowl_economy",
    "form_batting_wpa",
    "form_bowling_wpa",
    "form_bowl_wickets_per_match",
    "vs_opp_matches",
    "vs_opp_bat_contribution_pct",
    "vs_opp_bowl_contribution_pct",
    "vs_opp_win_pct",
    "venue_matches",
    "venue_bat_contribution_pct",
    "venue_bowl_contribution_pct",
    "domestic_form_matches",
    "domestic_form_batting_wpa",
    "domestic_form_bowling_wpa",
]

CATEGORICAL_FEATURES = ["role_bucket"]

MODEL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Win-Probability-Added (see data-collection's criiq_data/wpa.py) — how much a
# player's batting/bowling actually swung their team's win probability, not
# just how big their raw numbers were. Replaces contribution-share as the
# regression target: contribution-share couldn't tell a proven match-winner
# from a fringe player with a good-looking stat line in low-stakes matches
# (a real case found this session — it ranked D Hemalatha above Smriti
# Mandhana). bat_contribution_pct/bowl_contribution_pct remain as features
# (still informative), just not what's being predicted.
TARGETS = ["batting_wpa", "bowling_wpa"]

ID_COLUMNS = ["player_id", "match_id", "date", "opponent", "venue_id"]

from __future__ import annotations

import pandas as pd

from criiq_models.features.common import (
    batting_capable, bowling_capable, recency_weighted_mean, role_bucket, shrink, shrink_series)


def test_shrink_moves_toward_prior_for_small_samples():
    small = shrink(observed=50.0, n=1, prior=10.0, prior_strength=8)
    large = shrink(observed=50.0, n=1000, prior=10.0, prior_strength=8)
    assert 10.0 < small < 50.0
    assert abs(large - 50.0) < 0.5


def test_shrink_handles_missing_observed():
    assert shrink(None, None, prior=42.0) == 42.0


def test_shrink_series_matches_scalar_shrink_elementwise():
    observed = pd.Series([50.0, None, 50.0])
    n = pd.Series([1, 0, 1000])
    prior = pd.Series([10.0, 10.0, 10.0])
    result = shrink_series(observed, n, prior, prior_strength=8)

    assert result[0] == shrink(50.0, 1, 10.0, prior_strength=8)
    # n=0 with no observed value: the exact "no venue specified" case that
    # caused live-scoring predictions to go out-of-distribution — must
    # degrade cleanly to the prior, not stay missing.
    assert result[1] == 10.0
    assert abs(result[2] - 50.0) < 0.5


def test_recency_weighted_mean_favours_recent_values():
    values = pd.Series([0.0, 0.0, 100.0])
    order = pd.Series([1, 2, 3])
    weighted = recency_weighted_mean(values, order, decay=0.5)
    plain_mean = values.mean()
    assert weighted > plain_mean


def test_role_bucket_collapses_noise():
    assert role_bucket("batter") == "batter"
    assert role_bucket("all-rounder") == "all-rounder"
    assert role_bucket("goalkeeper") == "unknown"
    assert role_bucket(None) == "unknown"


def test_capability_helpers():
    assert batting_capable("batter") and batting_capable("all-rounder")
    assert not batting_capable("bowler")
    assert bowling_capable("bowler") and bowling_capable("all-rounder")
    assert not bowling_capable("batter")

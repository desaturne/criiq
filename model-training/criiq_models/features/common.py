"""Shared feature-building math: shrinkage + recency weighting.

Mirrors the shrinkage-toward-a-prior and recency-decay ideas already used in
data-collection (`min_innings_bayesian`, `rfi_lambda`) so small samples don't
produce wild, overconfident scores.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import SETTINGS


def shrink(observed: float | None, n: int | None, prior: float | None,
           prior_strength: int = SETTINGS.shrinkage_prior_matches) -> float | None:
    """Shrink an `observed` rate/average (from `n` samples) toward `prior`.

    shrunk = (n * observed + k * prior) / (n + k)   [k = prior_strength]

    Falls back to whichever of observed/prior is available if the other is
    missing, and returns None only when both are missing.

    `observed` is frequently a pandas aggregate (e.g. `Series.mean()` over an
    empty/all-missing slice), which yields `float('nan')`, not `None` — both
    are treated as "missing" here, since `nan is None` is False and would
    otherwise silently propagate NaN through the arithmetic below.
    """
    if observed is None or n is None or n <= 0 or pd.isna(observed):
        return prior
    if prior is None or pd.isna(prior):
        return observed
    n = float(n)
    k = float(prior_strength)
    return (n * observed + k * prior) / (n + k)


def shrink_series(observed: pd.Series, n: pd.Series, prior: pd.Series,
                   prior_strength: int = SETTINGS.shrinkage_prior_matches) -> pd.Series:
    """Vectorized `shrink()` — same semantics, for a whole column at once
    (training-table construction; `shrink()` itself stays the scalar version
    used at live-scoring time, one player at a time).

    Sparse per-venue/per-opponent raw means are the reason a live-scoring
    query with `venue_matches=0` (no venue specified) turned out to be
    wildly out-of-distribution relative to training: every *training* row
    has a real venue, so an unshrunk mean swings between "missing" (n=0) and
    a noisy single-match value (n=1) with nothing continuous in between.
    Shrinking toward the career prior in both places makes the feature
    behave continuously as n -> 0, removing that cliff entirely.
    """
    n = n.astype(float)
    obs = pd.to_numeric(observed, errors="coerce")
    pri = pd.to_numeric(prior, errors="coerce")
    k = float(prior_strength)
    denom = n + k
    shrunk = (n * obs + k * pri) / denom.where(denom != 0, np.nan)
    return shrunk.where(obs.notna(), pri)


def recency_weighted_mean(values: pd.Series, order: pd.Series,
                           decay: float = SETTINGS.form_recency_lambda) -> float | None:
    """Weighted mean of `values` ordered by `order` (ascending = oldest first),
    with the most recent value weighted 1.0 and older values decaying
    geometrically by `decay` per step back.
    """
    values = pd.Series(values).reset_index(drop=True)
    order = pd.Series(order).reset_index(drop=True)
    if values.empty:
        return None
    idx = order.rank(method="first").astype(int) - 1
    steps_back = idx.max() - idx
    weights = decay ** steps_back
    mask = values.notna()
    if not mask.any():
        return None
    w = weights[mask].astype(float)
    v = values[mask].astype(float)
    total_w = w.sum()
    if total_w <= 0:
        return None
    return float((w * v).sum() / total_w)


def safe_div(numer, denom):
    if denom in (None, 0) or (isinstance(denom, float) and np.isnan(denom)):
        return None
    return numer / denom


_KNOWN_ROLES = {"batter", "bowler", "all-rounder"}


def role_bucket(role: str | None) -> str:
    """Normalize the free-text `role` field to one of the four dense buckets.

    `player_registry.role` is Wikidata-derived and has a long tail of noisy,
    wrong-sport values (e.g. "goalkeeper", "winger") that occur only a
    handful of times out of ~7000 players — anything outside the three dense
    cricket roles collapses to "unknown" rather than propagating noise into
    the role-balance constraints.
    """
    if role in _KNOWN_ROLES:
        return role
    return "unknown"


def batting_capable(bucket: str) -> bool:
    return bucket in ("batter", "all-rounder")


def bowling_capable(bucket: str) -> bool:
    return bucket in ("bowler", "all-rounder")

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGE_DIR.parent

# Same database data-collection builds and maintains; read-only from here.
DEFAULT_DB = ROOT_DIR.parent / "data-collection" / "data" / "criiq.db"
DB_PATH = Path(os.environ.get("CRIIQ_DB", DEFAULT_DB))

ARTIFACTS_DIR = Path(os.environ.get("CRIIQ_MODEL_ARTIFACTS", ROOT_DIR / "artifacts"))
RECOMMENDATION_ARTIFACTS_DIR = ARTIFACTS_DIR / "player_recommendation"

# Format/gender are settings (not hardcoded through the codebase), so both
# men's and women's T20I are first-class scopes -- model artifacts, registry
# status, and every CLI command are parametrized by (format, gender) rather
# than assuming one. Women's T20I is only the *default* scope.
DEFAULT_FORMAT = "T20"
DEFAULT_GENDER = "female"


@dataclass(frozen=True)
class Settings:
    format: str = DEFAULT_FORMAT
    gender: str = DEFAULT_GENDER

    # Cold-start gate: below this many career matches, skip the learned model
    # entirely and score from the rule-based component layer only (mirrors
    # data-collection's min_innings_bayesian philosophy for small samples).
    min_matches_for_model: int = 10

    # Recent-form rolling window + recency decay (mirrors data-collection's
    # rfi_lambda: geometric down-weighting of older matches).
    form_window_matches: int = 15
    form_recency_lambda: float = 0.9

    # Shrinkage: how many matches of "prior strength" a small-sample matchup/
    # venue record is shrunk toward the player's career baseline with.
    shrinkage_prior_matches: int = 8

    # model_part credits a player's best ("primary") discipline at full
    # weight; a second active discipline (an all-rounder's weaker skill)
    # adds a bonus at this discount rather than being summed at full
    # weight — otherwise a merely-decent all-rounder structurally
    # outscores every pure specialist, who only ever has one discipline
    # to count no matter how outstanding it is.
    secondary_discipline_weight: float = 0.4

    # WPA values are naturally tiny (checked against the real per-match WPA
    # distribution across players with 10+ matches: median ~0, 95th
    # percentile ~+0.046, 99th ~+0.086, max ~+0.13), so they're rescaled into
    # the same points range the rest of the composite score uses. Calibrated
    # so a genuinely elite average (~0.09, near the 99th percentile) lands
    # close to the model_part cap (45) without maxing out below it — not a
    # tuned hyperparameter, a plausible mapping checked against real data.
    wpa_scale: float = 450.0

    # Strike-rate soft penalty (score.py's `strike_rate_part`). Modern T20I is
    # strike-rate-driven, so a batting-capable player whose career strike rate
    # is below the gender-relative par gets a *penalty* (never a reward -- WPA
    # already rewards fast scoring that changes games; this only docks the
    # genuinely slow). The penalty is scaled DOWN by a "game awareness" factor
    # in [0,1] (experience + big-moment impact + chasing composure +
    # consistency), so an experienced, situationally-aware anchor keeps most of
    # their rating while a slow player with none of that offset takes the full
    # hit. `sr_penalty_cap` is the most it can ever subtract; `sr_penalty_scale`
    # maps the fractional shortfall below par to points (a ~30% shortfall with
    # zero offset hits the cap). `experience_full_matches` is the career-match
    # count at which the experience sub-signal saturates to 1.0.
    sr_penalty_cap: float = 6.0
    sr_penalty_scale: float = 20.0
    experience_full_matches: int = 50

    # Openers (positions 1-2) are handled as a locked, score-ranked slot
    # separate from the rest of the batting order: a player's historical
    # batting_position_median at or below this counts as opener-capable.
    opener_position_threshold: float = 2.5
    min_openers: int = 2

    # Eligibility: which registry statuses are selectable at all.
    excluded_statuses: tuple[str, ...] = ("RETIRED_ALL", "RETIRED_FORMAT")
    inactive_status: str = "INACTIVE"

    # Playing-XI constraints.
    xi_size: int = 11
    min_batting_capable: int = 5
    min_bowling_capable: int = 5
    min_keepers: int = 1
    pool_size: int = 20

    # Lopsided-matchup detection (recommend/strength.py). When this team has at
    # least this many more currently-ICC-ranked (world-top-10) players than the
    # opponent -- and the opponent has almost none -- the matchup is flagged
    # lopsided: the stronger side is told it can rest frontline players, and a
    # rotation XI (top `rotation_rest_count` performers rested) is offered
    # alongside the first-choice one. ICC-ranked count is the strength signal
    # because mean importance_score doesn't separate a top side from a minnow
    # (associates pad it beating each other).
    lopsided_icc_gap: int = 3
    rotation_rest_count: int = 4

    # Temporal holdout fraction for backtesting (by match date, never by row).
    backtest_test_fraction: float = 0.2

    random_state: int = 42

    # Domestic form (data-collection's player_domestic_form -- see wpa.py):
    # shrunk toward the player's international career WPA the same way
    # vs-opponent/venue records are (features/common.py's shrink_series), but
    # with the *sample size fed to the shrink capped* at this value -- so no
    # amount of domestic match volume can ever fully outweigh the
    # international prior, on top of whatever weight the trained regressor
    # itself learns for the feature. Placeholder default pending the real
    # grid-search backtest (5/10/15/20) this plan's verification step runs
    # once real domestic data exists -- see model_comparison_robust.ipynb.
    domestic_form_max_effective_matches: int = 10

    finisher_low_impact_threshold: float = 5.0


SETTINGS = Settings()


def ensure_dirs() -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    RECOMMENDATION_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

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

# format/gender are settings, not hardcoded, so both men's and women's T20I
# are first-class scopes. women's T20I is only the default.
DEFAULT_FORMAT = "T20"
DEFAULT_GENDER = "female"


@dataclass(frozen=True)
class Settings:
    format: str = DEFAULT_FORMAT
    gender: str = DEFAULT_GENDER

    # cold-start gate: below this many career matches, skip the learned model
    # and score from the rule-based component layer only.
    min_matches_for_model: int = 10

    # recent-form rolling window + recency decay
    form_window_matches: int = 15
    form_recency_lambda: float = 0.9

    # matches of "prior strength" a small-sample matchup/venue record is
    # shrunk toward the player's career baseline with.
    shrinkage_prior_matches: int = 8

    # model_part credits a player's primary discipline at full weight; a
    # second active discipline adds a bonus at this discount instead of
    # being summed at full weight.
    secondary_discipline_weight: float = 0.4

    # wpa values are naturally tiny, so they're rescaled into the same points
    # range the rest of the composite score uses.
    wpa_scale: float = 450.0

    # strike-rate soft penalty (score.py's strike_rate_part). a batting-capable
    # player below the gender-relative par strike rate gets a penalty, scaled
    # down by a game-awareness factor so experienced players keep most of
    # their rating. sr_penalty_cap is the max deduction; sr_penalty_scale maps
    # the shortfall to points; experience_full_matches is where the experience
    # sub-signal saturates to 1.0.
    sr_penalty_cap: float = 6.0
    sr_penalty_scale: float = 20.0
    experience_full_matches: int = 50

    # openers (positions 1-2) are a locked, score-ranked slot separate from
    # the rest of the batting order.
    opener_position_threshold: float = 2.5
    min_openers: int = 2

    # eligibility: which registry statuses are selectable at all.
    # RETIRED_* only ever come from the manual override CSV
    # (data-collection's overrides.py / status_overrides table). The
    # pipeline's own classifier never emits them, so when that CSV is
    # unpopulated -- which is the normal case -- this tuple matches nothing
    # and is not, on its own, a working retirement filter. UNKNOWN below is
    # what actually catches retired players in that situation.
    excluded_statuses: tuple[str, ...] = ("RETIRED_ALL", "RETIRED_FORMAT")
    inactive_status: str = "INACTIVE"
    # "no international appearance in active_window..inactive_window days"
    # (540-1095). A player who has just retired from a format lands here for
    # roughly three years before ageing into INACTIVE, so treating UNKNOWN as
    # selectable is what put retired internationals into the pool.
    unknown_status: str = "UNKNOWN"

    # playing-xi constraints.
    xi_size: int = 11
    min_batting_capable: int = 5
    min_bowling_capable: int = 5
    min_keepers: int = 1
    pool_size: int = 20

    # lopsided-matchup detection (recommend/strength.py). if this team has
    # this many more icc-ranked players than the opponent, the matchup is
    # flagged lopsided and a rotation xi is offered alongside the first-choice one.
    lopsided_icc_gap: int = 3
    rotation_rest_count: int = 4

    # temporal holdout fraction for backtesting, by match date, never by row.
    backtest_test_fraction: float = 0.2

    random_state: int = 42

    # domestic form shrunk toward international career wpa, with the sample
    # size fed to the shrink capped at this value. placeholder pending a real
    # grid-search backtest once more domestic data exists.
    domestic_form_max_effective_matches: int = 10

    finisher_low_impact_threshold: float = 5.0


SETTINGS = Settings()


def ensure_dirs() -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    RECOMMENDATION_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

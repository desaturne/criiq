from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGE_DIR.parent
DATA_DIR = Path(os.environ.get("CRIIQ_DATA_DIR", ROOT_DIR / "data"))

RAW_DIR = DATA_DIR / "raw"
REGISTER_DIR = DATA_DIR / "register"
CACHE_DIR = DATA_DIR / "cache"
INTERIM_DIR = DATA_DIR / "interim"
QUARANTINE_DIR = DATA_DIR / "quarantine"
FEATURES_DIR = DATA_DIR / "features"
STYLES_DIR = DATA_DIR / "styles"
MANUAL_STYLES_CSV = STYLES_DIR / "player_styles.csv"
MODELS_DIR = DATA_DIR / "models"
RANKINGS_DIR = DATA_DIR / "rankings"
ICC_RANKINGS_CSV = RANKINGS_DIR / "icc_rankings.csv"
ICC_RANKINGS_SOURCE_URL = os.environ.get(
    "CRIIQ_ICC_RANKINGS_SOURCE_URL",
    "https://assets-icc.sportz.io/cricket/v1/ranking",
)
ICC_RANKINGS_CLIENT_ID = os.environ.get("CRIIQ_ICC_RANKINGS_CLIENT_ID")
OVERRIDES_DIR = DATA_DIR / "overrides"
PLAYER_STATUS_CSV = OVERRIDES_DIR / "player_status.csv"
DB_PATH = Path(os.environ.get("CRIIQ_DB", DATA_DIR / "criiq.db"))

ALL_DIRS = [DATA_DIR, RAW_DIR, REGISTER_DIR, CACHE_DIR, INTERIM_DIR,
            QUARANTINE_DIR, FEATURES_DIR, STYLES_DIR, RANKINGS_DIR, OVERRIDES_DIR,
            MODELS_DIR, CACHE_DIR / "cricinfo"]

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"


CRICSHEET_BASE = "https://cricsheet.org/downloads"
REGISTER_URL = "https://cricsheet.org/register/people.csv"


@dataclass(frozen=True)
class CricsheetSource:
    fmt: str
    gender: str
    filename: str
    enabled: bool = True

    @property
    def url(self) -> str:
        return f"{CRICSHEET_BASE}/{self.filename}"

    @property
    def label(self) -> str:
        # Derived from the filename, not gender+fmt: several domestic
        # competitions now share the same (gender, fmt) pair (e.g. every
        # women's T20 source below), and `label` is used as a meta-key/status
        # key elsewhere (ingest.py's `ingested_at::{label}`) -- it must stay
        # one-to-one with a real source, not collide across competitions.
        return self.filename.removesuffix(".zip")


CRICSHEET_SOURCES: list[CricsheetSource] = [
    CricsheetSource("T20", "female", "t20s_female_csv2.zip", enabled=True),
    CricsheetSource("T20", "male", "t20s_male_csv2.zip", enabled=True),
    CricsheetSource("ODI", "female", "odis_female_csv2.zip", enabled=False),
    CricsheetSource("ODI", "male", "odis_male_csv2.zip", enabled=False),
    # Domestic T20 leagues -- same Cricsheet site, same license/access basis as
    # the internationals above, just `team_type='club'` (see ingest.py). Real
    # download URLs verified (HEAD 200) before adding, not guessed. Women's
    # leagues enabled per this project's current scope (women's primary);
    # men's scaffolded the same way ODI already is above -- present, disabled,
    # trivial to flip on later.
    CricsheetSource("T20", "female", "wbb_female_csv2.zip", enabled=True),   # Women's Big Bash League
    CricsheetSource("T20", "female", "wpl_female_csv2.zip", enabled=True),   # Women's Premier League
    CricsheetSource("T20", "female", "hnd_female_csv2.zip", enabled=True),   # The Hundred (Women)
    CricsheetSource("T20", "female", "wtb_female_csv2.zip", enabled=True),   # Women's T20 Blast
    CricsheetSource("T20", "female", "wtc_female_csv2.zip", enabled=True),   # Women's T20 Challenge
    CricsheetSource("T20", "female", "wsl_female_csv2.zip", enabled=True),   # Women's Cricket Super League
    CricsheetSource("T20", "female", "blz_female_csv2.zip", enabled=True),   # T20 Blaze
    CricsheetSource("T20", "male", "ipl_male_csv2.zip", enabled=False),     # Indian Premier League
    CricsheetSource("T20", "male", "bbl_male_csv2.zip", enabled=False),     # Big Bash League
    CricsheetSource("T20", "male", "psl_male_csv2.zip", enabled=False),     # Pakistan Super League
    CricsheetSource("T20", "male", "cpl_male_csv2.zip", enabled=False),     # Caribbean Premier League
    CricsheetSource("T20", "male", "ntb_male_csv2.zip", enabled=False),     # (NatWest) T20 Blast
]


def enabled_sources() -> list[CricsheetSource]:
    return [s for s in CRICSHEET_SOURCES if s.enabled]


RSS_FEEDS: list[str] = [
    "https://www.icc-cricket.com/rss/news",
    "https://www.espncricinfo.com/rss/content/story/feeds/0.xml",
]
RETIREMENT_KEYWORDS = [
    "retires", "retirement", "retired", "steps down", "step down",
    "no longer available", "calls time", "announces retirement",
    "hangs up", "bids farewell",
]


@dataclass(frozen=True)
class Settings:
    user_agent: str = (
        "criiq-data-collector/0.1 (academic project; +https://cricsheet.org) "
        "python-requests"
    )
    cricsheet_delay_s: float = 1.0
    cricinfo_delay_s: float = 2.0
    http_timeout_s: int = 120
    http_retries: int = 3
    http_backoff_s: float = 2.0

    fuzzy_threshold: int = 88

    recall_flag_days: int = 180
    active_window_days: int = 540
    inactive_window_days: int = 1095
    # Selection-consistency window: how often was the player picked, relative to
    # the matches their team actually played, over a rolling recent window. Used
    # to separate regularly-selected ACTIVE players from in-and-out (INCONSISTENT)
    # ones. selection_rate is only trusted once the team has played at least
    # min_window_team_matches in the window; below that the sample is too small.
    selection_window_days: int = 730
    min_window_team_matches: int = 8
    # Share of their team's matches (since first appearing in the window) a player
    # must feature in to count as a regular ACTIVE selection rather than in-and-out
    # INCONSISTENT. Kept modest because packed international calendars rotate even
    # frontline players heavily; tune per competition if needed.
    regular_selection_rate: float = 0.35
    age_advisory_pace: int = 38
    age_advisory_default: int = 40
    registry_refresh_days: int = 7
    staleness_warn_days: int = 14

    form_window_innings: int = 20
    rfi_lambda: float = 0.85
    form_sparkline_len: int = 10
    impact_recent_matches: int = 10

    min_innings_bayesian: int = 20

    # Win-probability (empirical model): additive shrinkage toward the innings
    # prior for sparse state buckets, and the fraction of matches held out
    # (by match, never by ball) to report honest calibration.
    winprob_shrinkage: float = 12.0
    winprob_test_fraction: float = 0.2

    # Hard wall between "the data the pipeline trains/scores on" and "whatever
    # shows up in a later refresh" -- anything with date > this goes to the
    # `*_holdout` tables (see db.py) instead of the production ones, so it's
    # available for genuine forward-testing but can never silently leak into
    # training or live scoring. Not a present-day trim (the live DB currently
    # ends exactly here already) -- a forward safeguard for future refreshes.
    data_cutoff_date: str = "2026-06-15"


SETTINGS = Settings()


def ensure_dirs() -> None:
    for d in ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)

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
            CACHE_DIR / "cricinfo"]

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
        return f"{self.gender}_{self.fmt}"


CRICSHEET_SOURCES: list[CricsheetSource] = [
    CricsheetSource("T20", "female", "t20s_female_csv2.zip", enabled=True),
    CricsheetSource("T20", "male", "t20s_male_csv2.zip", enabled=True),
    CricsheetSource("ODI", "female", "odis_female_csv2.zip", enabled=False),
    CricsheetSource("ODI", "male", "odis_male_csv2.zip", enabled=False),
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


SETTINGS = Settings()


def ensure_dirs() -> None:
    for d in ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)

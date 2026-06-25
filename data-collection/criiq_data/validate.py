from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from .config import QUARANTINE_DIR
from .logging_utils import get_logger

log = get_logger("validate")

DELIVERY_REQUIRED = [
    "match_id", "innings", "ball", "batting_team", "bowling_team",
    "striker", "non_striker", "bowler", "runs_off_bat", "extras",
]


def validate_deliveries(df: pd.DataFrame, match_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing = [c for c in DELIVERY_REQUIRED if c not in df.columns]
    if missing:
        df = df.copy()
        df["_reject_reason"] = f"missing columns: {missing}"
        return df.iloc[0:0], df

    df = df.copy()
    reasons = pd.Series([""] * len(df), index=df.index)

    for col in ("runs_off_bat", "extras", "innings"):
        coerced = pd.to_numeric(df[col], errors="coerce")
        bad = coerced.isna()
        reasons[bad & (reasons == "")] = f"non-numeric {col}"
        df[col] = coerced

    for col in ("striker", "bowler", "batting_team", "bowling_team"):
        bad = df[col].isna() | (df[col].astype(str).str.strip() == "")
        reasons[bad & (reasons == "")] = f"null {col}"

    reject_mask = reasons != ""
    clean = df.loc[~reject_mask].copy()
    rejected = df.loc[reject_mask].copy()
    if len(rejected):
        rejected["_reject_reason"] = reasons[reject_mask]
        rejected["_match_id"] = match_id
    return clean, rejected


def quarantine(rejected: pd.DataFrame, tag: str) -> Path | None:
    if rejected is None or rejected.empty:
        return None
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = QUARANTINE_DIR / f"{tag}_{stamp}.csv"
    rejected.to_csv(path, index=False)
    log.warning("quarantined %d rows -> %s", len(rejected), path.name)
    return path

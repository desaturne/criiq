from __future__ import annotations

import csv
import datetime as dt
import io
import re
import zipfile

import pandas as pd

from .config import RAW_DIR, CricsheetSource, enabled_sources
from .db import set_meta
from .logging_utils import get_logger
from .validate import quarantine, validate_deliveries

log = get_logger("ingest")

_MATCH_RE = re.compile(r"^(\d+)\.csv$")

_DELIV_COLS = [
    "match_id", "innings", "over", "ball_in_over", "batting_team", "bowling_team",
    "striker", "non_striker", "bowler", "runs_off_bat", "extras", "wides",
    "noballs", "runs_total", "wicket_type", "player_dismissed",
]


def _parse_info(text: str) -> dict:
    info = {"teams": [], "dates": [], "players": [], "registry": [], "extra": {}}
    for row in csv.reader(io.StringIO(text)):
        if not row or row[0] != "info":
            continue
        if len(row) < 3:
            continue
        key = row[1]
        if key == "team":
            info["teams"].append(row[2])
        elif key == "date":
            info["dates"].append(row[2])
        elif key == "player" and len(row) >= 4:
            info["players"].append((row[2], row[3]))
        elif key == "registry" and len(row) >= 5 and row[2] == "people":
            info["registry"].append((row[3], row[4]))
        elif key in ("winner_runs", "winner_wickets", "winner_innings"):
            info["extra"][key] = row[2]
        else:
            info["extra"].setdefault(key, row[2])
    return info


def _norm_date(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip().replace("/", "-")
    try:
        return dt.date.fromisoformat(raw).isoformat()
    except ValueError:
        return raw


def _win_margin(info: dict) -> str | None:
    e = info["extra"]
    if "winner_runs" in e:
        return f"{e['winner_runs']} runs"
    if "winner_wickets" in e:
        return f"{e['winner_wickets']} wickets"
    if e.get("method"):
        return e["method"]
    if e.get("result"):
        return e["result"]
    return None


def _existing_match_ids(conn) -> set[str]:
    return {r["match_id"] for r in conn.execute("SELECT match_id FROM matches")}


def ingest_source(conn, src: CricsheetSource) -> dict:
    path = RAW_DIR / src.filename
    if not path.exists():
        log.warning("zip not found, skipping: %s", path.name)
        return {"source": src.label, "status": "missing"}

    existing = _existing_match_ids(conn)
    new_matches = skipped = deliveries_in = rejected_total = 0
    non_t20_skipped = 0

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        match_files = [n for n in names if _MATCH_RE.match(n)]
        log.info("%s: %d match files in zip", src.filename, len(match_files))

        for name in match_files:
            match_id = _MATCH_RE.match(name).group(1)
            if match_id in existing:
                skipped += 1
                continue
            info_name = f"{match_id}_info.csv"
            if info_name not in names:
                log.warning("no info for match %s, skipping", match_id)
                continue

            info = _parse_info(z.read(info_name).decode("utf-8", errors="replace"))

            mtype = info["extra"].get("match_type", "")
            ttype = info["extra"].get("team_type", "international")
            if src.fmt == "T20" and mtype and mtype.upper() not in ("T20", "IT20"):
                non_t20_skipped += 1
                continue
            if ttype and ttype != "international":
                non_t20_skipped += 1
                continue

            teams = info["teams"]
            date = _norm_date(info["dates"][0] if info["dates"] else None)

            try:
                ddf = pd.read_csv(io.BytesIO(z.read(name)), dtype=str,
                                  keep_default_na=False, na_values=[""])
            except Exception as exc:
                log.error("failed to read deliveries for %s: %s", match_id, exc)
                continue

            clean, rejected = validate_deliveries(ddf, match_id)
            if rejected is not None and not rejected.empty:
                quarantine(rejected, f"{src.label}_{match_id}")
                rejected_total += len(rejected)
            if clean.empty:
                continue

            clean = _shape_deliveries(clean, match_id)

            conn.execute(
                "INSERT OR IGNORE INTO matches("
                "match_id, format, gender, match_type, season, date, event, "
                "venue_raw, city, team1, team2, toss_winner, toss_decision, "
                "winner, win_margin, player_of_match, ingested_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    match_id, src.fmt, info["extra"].get("gender", src.gender),
                    mtype or src.fmt, info["extra"].get("season"), date,
                    info["extra"].get("event"), info["extra"].get("venue"),
                    info["extra"].get("city") or None,
                    teams[0] if len(teams) > 0 else None,
                    teams[1] if len(teams) > 1 else None,
                    info["extra"].get("toss_winner"),
                    info["extra"].get("toss_decision"),
                    info["extra"].get("winner"), _win_margin(info),
                    info["extra"].get("player_of_match"),
                    dt.datetime.now().isoformat(timespec="seconds"),
                ),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO match_players(match_id, team, player_name) "
                "VALUES(?,?,?)",
                [(match_id, t, n) for (t, n) in info["players"]],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO identifier_map(player_name, identifier) "
                "VALUES(?,?)",
                info["registry"],
            )
            conn.executemany(
                f"INSERT INTO deliveries({','.join(_DELIV_COLS)}) "
                f"VALUES({','.join('?' for _ in _DELIV_COLS)})",
                list(clean[_DELIV_COLS].itertuples(index=False, name=None)),
            )
            conn.commit()
            new_matches += 1
            deliveries_in += len(clean)

    set_meta(conn, f"ingested_at::{src.label}",
             dt.datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    log.info("%s: +%d matches, %d deliveries (skipped %d existing, %d off-scope, "
             "%d rejected rows)", src.label, new_matches, deliveries_in, skipped,
             non_t20_skipped, rejected_total)
    return {"source": src.label, "new_matches": new_matches,
            "deliveries": deliveries_in, "skipped_existing": skipped,
            "rejected": rejected_total}


def _shape_deliveries(df: pd.DataFrame, match_id: str) -> pd.DataFrame:
    out = pd.DataFrame()
    out["match_id"] = [match_id] * len(df)
    out["innings"] = pd.to_numeric(df["innings"], errors="coerce").astype("Int64")

    ball = df["ball"].astype(str)
    out["over"] = pd.to_numeric(ball.str.split(".").str[0], errors="coerce").astype("Int64")
    out["ball_in_over"] = pd.to_numeric(ball.str.split(".").str[1], errors="coerce").astype("Int64")

    out["batting_team"] = df["batting_team"]
    out["bowling_team"] = df["bowling_team"]
    out["striker"] = df["striker"]
    out["non_striker"] = df["non_striker"]
    out["bowler"] = df["bowler"]

    rob = pd.to_numeric(df["runs_off_bat"], errors="coerce").fillna(0).astype(int)
    extras = pd.to_numeric(df["extras"], errors="coerce").fillna(0).astype(int)
    out["runs_off_bat"] = rob
    out["extras"] = extras
    out["wides"] = pd.to_numeric(df.get("wides", 0), errors="coerce").fillna(0).astype(int)
    out["noballs"] = pd.to_numeric(df.get("noballs", 0), errors="coerce").fillna(0).astype(int)
    out["runs_total"] = rob + extras

    out["wicket_type"] = df.get("wicket_type")
    out["player_dismissed"] = df.get("player_dismissed")
    return out.astype(object).where(pd.notna(out), None)


def ingest_all(conn) -> list[dict]:
    results = []
    for src in enabled_sources():
        try:
            results.append(ingest_source(conn, src))
        except Exception as exc:
            log.error("ingest failed for %s: %s", src.label, exc)
            results.append({"source": src.label, "status": "error", "error": str(exc)})
    return results

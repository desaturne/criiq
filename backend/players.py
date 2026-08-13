"""
players.py — everything about players (Phase 2).

Read endpoints pull from Sushma's criiq.db (read-only).
The Add Player form writes to OUR app.db instead — manually added players get
ids like "m1", "m2" so they can never clash with pipeline player ids (UUIDs).
"""

import bisect
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import model_bridge
import roster_index
from auth import require_user
from database import app_db, criiq_db

# every endpoint in this file requires a login token
router = APIRouter(tags=["players"], dependencies=[Depends(require_user)])

# The frontend uses friendly role names; the database uses lowercase ones.
ROLE_MAP = {"batsman": "batter", "bowler": "bowler", "all-rounder": "all-rounder",
            "allrounder": "all-rounder", "wicketkeeper": "wicketkeeper"}


def row_to_dict(row):
    return dict(row) if row is not None else None


OPENER_POSITION_THRESHOLD = 2.5  # mirrors model-training's SETTINGS.opener_position_threshold

# Eligibility clauses, mirroring criiq_models' roster.team_pool (see the long
# note in list_players). Kept as named constants so the two stay comparable.
_XI_SIZE = 11
_NOT_RETIRED = "r.retirement_status NOT IN ('RETIRED_ALL', 'RETIRED_FORMAT')"
_NOT_STALE = ("NOT (r.retirement_status IN ('INACTIVE', 'UNKNOWN') "
              "     AND COALESCE(r.recent_domestic_activity, 0) = 0)")
_NOT_STALE_INACTIVE_ONLY = ("NOT (r.retirement_status = 'INACTIVE' "
                            "     AND COALESCE(r.recent_domestic_activity, 0) = 0)")

_RETIRED_STATUSES = ("RETIRED_ALL", "RETIRED_FORMAT")


def retired_names(player_ids: list[str], fmt: str = "T20") -> dict[str, str]:
    """player_id -> canonical_name for any of player_ids retired as of fmt.

    For re-validating ids that bypass the /players picker: saved selections,
    a named opposition XI, direct API calls.
    """
    if not player_ids:
        return {}
    id_placeholders = ",".join("?" * len(player_ids))
    status_placeholders = ",".join("?" * len(_RETIRED_STATUSES))
    rows = criiq_db.execute(
        f"SELECT p.player_id, p.canonical_name FROM players p "
        f"JOIN player_registry r ON r.player_id = p.player_id "
        f"WHERE r.format = ? AND r.player_id IN ({id_placeholders}) "
        f"AND r.retirement_status IN ({status_placeholders})",
        [fmt, *player_ids, *_RETIRED_STATUSES],
    ).fetchall()
    retired = {row["player_id"]: row["canonical_name"] for row in rows}

    manual_ids = [pid[1:] for pid in player_ids if pid.startswith("m") and pid[1:].isdigit()]
    if manual_ids:
        manual_placeholders = ",".join("?" * len(manual_ids))
        manual_rows = app_db.execute(
            f"SELECT id, name FROM manual_players WHERE id IN ({manual_placeholders}) AND UPPER(status) = 'RETIRED'",
            manual_ids,
        ).fetchall()
        retired.update({f"m{row['id']}": row["name"] for row in manual_rows})

    return retired

def position_label(role_bucket: str | None, is_keeper: bool, batting_position_median: float | None) -> str:
    """Mirrors criiq_models/selection/optimize.py's slot_category, plus a keeper override."""
    if is_keeper:
        return "Wicketkeeper"
    if batting_position_median is not None and batting_position_median <= OPENER_POSITION_THRESHOLD:
        return "Opener"
    if role_bucket == "bowler":
        return "Tail"
    return "Middle order"


def _load_rfi_distribution() -> list[float]:
    values = []
    for row in criiq_db.execute("SELECT card_json FROM player_cards WHERE card_json IS NOT NULL"):
        rfi = json.loads(row["card_json"]).get("form", {}).get("rfi")
        if rfi is not None:
            values.append(rfi)
    values.sort()
    return values


# Raw RFI (recent-form index) only ranges ~0-47 in this DB (median ~10) -- a
# ">=70" or similar absolute threshold against it never fires. form_score is
# each player's real percentile rank within this distribution instead, so
# "70+" genuinely means "top 30% by recent form."
_RFI_DISTRIBUTION = _load_rfi_distribution()


def rfi_percentile(rfi: float | None) -> float | None:
    if rfi is None or not _RFI_DISTRIBUTION:
        return None
    idx = bisect.bisect_left(_RFI_DISTRIBUTION, rfi)
    return round(100 * idx / len(_RFI_DISTRIBUTION), 1)


def retired_override_ids() -> set[str]:
    return {row["player_id"] for row in app_db.execute("SELECT player_id FROM retired_players")}


def player_status(row_status: str, player_id: str, retired_ids: set[str]) -> str:
    return "RETIRED" if player_id in retired_ids else row_status


def phase_value(row: dict | None) -> float:
    if not row:
        return 0
    # bat_team_percentile is the preferred 0-100 phase signal.
    # Bowler-only rows may only have an economy-based estimate.
    if row.get("bat_team_percentile") is not None:
        return max(0, min(100, round(row["bat_team_percentile"])))
    if row.get("bowl_economy") is not None:
        return max(0, min(100, round(100 - row["bowl_economy"] * 10)))
    return 0


# --------------------------------------------------------------------------
# 4. GET /players — searchable, filterable, paginated list
# --------------------------------------------------------------------------
@router.get("/players")
def list_players(search: str = "", role: str = "", status: str = "", country: str = "", gender: str = "",
                 opponent: str = "", page: int = 1, limit: int = 20):
    limit = max(1, min(limit, 100))
    page = max(1, page)
    retired_ids = retired_override_ids()

    # search/role/status stay in SQL (cheap, indexed-ish columns). country/
    # gender are membership checks against roster_index's in-memory sets --
    # built once from real match appearances, not the sometimes-wrong stored
    # players.nationality/player_cards.nationality columns (see
    # roster_index.py's docstring for the real "ER Oza" case this fixes) --
    # so they're applied in Python against the *lightweight* (no card_json)
    # candidate list below, before paginating, rather than as SQL subqueries
    # re-run per request (a first version of this cost ~2s per subquery,
    # 2-3x per request).
    where, params = ["1=1"], []
    if search:
        where.append("p.canonical_name LIKE ?")
        params.append(f"%{search}%")
    if role:
        where.append("LOWER(c.role) = ?")
        params.append(ROLE_MAP.get(role.lower(), role.lower()))
    if status:
        where.append("r.retirement_status = ?")
        params.append(status.upper())

    def _candidates(eligibility: list[str]):
        sql = f"""
            FROM players p
            JOIN player_registry r ON r.player_id = p.player_id
            LEFT JOIN player_cards c ON c.player_id = p.player_id
            WHERE {' AND '.join(where + eligibility)}
        """
        rows = criiq_db.execute(
            f"SELECT p.player_id, p.cricsheet_identifier {sql} "
            f"ORDER BY c.matches_played DESC, p.canonical_name",
            params,
        ).fetchall()
        if country:
            members = roster_index.team_members(country)
            rows = [r for r in rows if r["cricsheet_identifier"] in members]
        if gender in ("male", "female"):
            members = roster_index.gender_members(gender)
            rows = [r for r in rows if r["cricsheet_identifier"] in members]
        return rows

    if status:
        # explicit status= wins outright (the Squads roster page's filter),
        # so retired/inactive players stay reachable when asked for by name.
        candidates = _candidates([])
    else:
        # Default view excludes retired/inactive players everywhere -- a
        # squad-building or simulation picker showing them mixed in with
        # real current players is misleading.
        #
        # This MUST mirror criiq_models' roster.team_pool, or the XI pickers
        # offer players the recommender would never pick. It previously only
        # dropped INACTIVE, which let every UNKNOWN through -- that is the
        # 540-1095-day no-international-appearance band a just-retired player
        # sits in, so recently-retired internationals were selectable here
        # (and in the simulator) while /recommendations behaved differently.
        # RETIRED_* only exist when the manual override CSV is populated;
        # they are listed so this stays correct once it is.
        candidates = _candidates([_NOT_RETIRED, _NOT_STALE])
        # Same dormant-side fallback team_pool applies: an associate team
        # that hasn't played in years is entirely UNKNOWN, and showing an
        # empty picker for it is worse than showing its last known squad.
        # INACTIVE always carries recall_flag=0, so dropping the flag from
        # this clause matches team_pool's INACTIVE rule exactly.
        if country and len(candidates) < _XI_SIZE:
            relaxed = _candidates([_NOT_RETIRED, _NOT_STALE_INACTIVE_ONLY])
            if len(relaxed) > len(candidates):
                candidates = relaxed

    total = len(candidates)
    page_ids = [r["player_id"] for r in candidates[(page - 1) * limit: (page - 1) * limit + limit]]

    if not page_ids:
        rows = []
        opponent_rows = []
        phase_rows = []
    else:
        placeholders = ",".join("?" * len(page_ids))
        rows = criiq_db.execute(
            f"""SELECT p.player_id, p.cricsheet_identifier, p.canonical_name, c.nationality, c.role,
                       COALESCE(s.batting_hand, p.batting_hand) AS batting_hand,
                       COALESCE(s.bowling_style, p.bowling_style) AS bowling_style,
                       r.retirement_status, c.card_json,
                       pr.primary_role, pr.is_keeper, pr.batting_position_median
                FROM players p
                JOIN player_registry r ON r.player_id = p.player_id
                LEFT JOIN player_cards c ON c.player_id = p.player_id
                LEFT JOIN player_styles s ON s.player_id = p.player_id
                LEFT JOIN player_role_final pr ON pr.player_id = p.player_id AND pr.format = 'T20'
                WHERE p.player_id IN ({placeholders})""",
            page_ids,
        ).fetchall()
        opponent_rows = []
        if opponent:
            opponent_rows = criiq_db.execute(
                f"""SELECT player_id, opponent, matches, won, win_pct, bat_average, bat_strike_rate,
                           wickets, economy, dismissals
                    FROM player_vs_opponent
                    WHERE player_id IN ({placeholders}) AND LOWER(opponent) = LOWER(?)""",
                [*page_ids, opponent],
            ).fetchall()
        phase_rows = criiq_db.execute(
            f"""SELECT player_id, phase, bat_team_percentile, bowl_economy
                    FROM player_phase
                    WHERE player_id IN ({placeholders})""",
            page_ids,
        ).fetchall()
        # player_id IN (...) doesn't preserve the ranked order from `candidates` -- restore it.
        order = {pid: i for i, pid in enumerate(page_ids)}
        rows = sorted(rows, key=lambda r: order[r["player_id"]])
        opponent_map = {row["player_id"]: row_to_dict(row) for row in opponent_rows}
        phase_map: dict[str, dict[str, dict]] = {}
        for row in phase_rows:
            phase_map.setdefault(row["player_id"], {})[row["phase"]] = row_to_dict(row)

    if not page_ids:
        opponent_map = {}
        phase_map = {}

    players = []
    for row in rows:
        card = json.loads(row["card_json"]) if row["card_json"] else {}
        form = card.get("form", {})
        phases = phase_map.get(row["player_id"], {})
        players.append({
            "id": row["player_id"],
            "name": row["canonical_name"],
            "country": roster_index.current_team(row["cricsheet_identifier"]) or row["nationality"],
            "role": row["role"],
            "batting_hand": row["batting_hand"],
            "bowling_style": row["bowling_style"],
            "status": player_status(row["retirement_status"], row["player_id"], retired_ids),
            "last5_scores": (form.get("last_innings") or [])[-5:],
            "form_score": rfi_percentile(form.get("rfi")),  # percentile rank, not raw RFI
            # Already-parsed card_json.career -- real {"batting": {...}, "bowling":
            # {...}} breakdown, same shape /players/{id} returns, so PlayerCard's
            # expandable Stats section shows real matches/runs/avg/SR (or
            # wkts/econ/best) instead of being undefined for every player.
            "career": card.get("career"),
            "phases": [phases.get(name) for name in ("powerplay", "middle", "death") if phases.get(name)],
            "is_keeper": bool(row["is_keeper"]),
            "batting_position_median": row["batting_position_median"],
            # Same real batting-position/role data the recommendation engine
            # itself uses to order a team sheet (opener/middle/tail/keeper),
            # not a guess -- see position_label()'s docstring.
            "position": position_label(row["primary_role"], bool(row["is_keeper"]), row["batting_position_median"]),
            "opponent_record": opponent_map.get(row["player_id"]),
        })

    # Manually added players (from the Add Player form) appear on page 1.
    if page == 1:
        manual_where, manual_params = ["name LIKE ?"], [f"%{search}%"]
        if country:
            manual_where.append("country = ?")
            manual_params.append(country)
        manual = app_db.execute(
            f"SELECT * FROM manual_players WHERE {' AND '.join(manual_where)}", manual_params
        ).fetchall()
        for m in manual:
            if status == "RETIRED" and m["status"].upper() != "RETIRED":
                continue
            if status != "RETIRED" and m["status"].upper() == "RETIRED":
                continue
            players.insert(0, {
                "id": f"m{m['id']}", "name": m["name"], "country": m["country"],
                "role": m["role"], "batting_hand": m["batting_hand"],
                "bowling_style": m["bowling_style"], "status": m["status"],
                "last5_scores": [], "form_score": None, "source": "manual",
            })

    return {"data": {"players": players, "page": page, "limit": limit,
                     "total": total}, "error": None}


# --------------------------------------------------------------------------
# 5. GET /players/{id} — the full player card
# --------------------------------------------------------------------------
def build_player_detail(player_id: str) -> dict | None:
    """Everything the Player Form screen needs, or None if unknown id."""
    retired_ids = retired_override_ids()
    # Manually added player? (ids look like m1, m2, ...)
    if player_id.startswith("m") and player_id[1:].isdigit():
        m = app_db.execute(
            "SELECT * FROM manual_players WHERE id = ?", (player_id[1:],)
        ).fetchone()
        if not m:
            return None
        d = row_to_dict(m)
        d["id"] = player_id
        d["source"] = "manual"
        d["status"] = "RETIRED" if m["status"].upper() == "RETIRED" else m["status"]
        return d

    card_row = criiq_db.execute(
        "SELECT card_json FROM player_cards WHERE player_id = ?", (player_id,)
    ).fetchone()
    if not card_row:
        return None
    card = json.loads(card_row["card_json"])

    # Same correction as /players' list: the stored nationality can be wrong
    # (see roster_index.py's docstring) -- real match-appearance team wins.
    ident_row = criiq_db.execute(
        "SELECT cricsheet_identifier FROM players WHERE player_id = ?", (player_id,)
    ).fetchone()
    if ident_row and ident_row["cricsheet_identifier"]:
        real_team = roster_index.current_team(ident_row["cricsheet_identifier"])
        if real_team and card.get("identity"):
            card["identity"]["nationality"] = real_team

    advanced_row = criiq_db.execute(
        "SELECT archetype, profile_json FROM player_advanced WHERE player_id = ?",
        (player_id,),
    ).fetchone()
    advanced = json.loads(advanced_row["profile_json"]) if advanced_row else {}

    impact = row_to_dict(criiq_db.execute(
        "SELECT * FROM player_impact WHERE player_id = ?", (player_id,)
    ).fetchone())

    phases = [row_to_dict(r) for r in criiq_db.execute(
        "SELECT * FROM player_phase WHERE player_id = ? ORDER BY phase", (player_id,)
    ).fetchall()]

    # Real per-opponent record (player_vs_opponent), not the frontend's old
    # fabricated "multiply the one opponent we have by 0.9/1.05/..." approach.
    # Top 6 by sample size so the widest-known matchups show first.
    opponents = [row_to_dict(r) for r in criiq_db.execute(
        "SELECT opponent, matches, won, win_pct, bat_average, bat_strike_rate, "
        "       wickets, economy, dismissals "
        "FROM player_vs_opponent WHERE player_id = ? ORDER BY matches DESC LIMIT 6",
        (player_id,),
    ).fetchall()]

    # Real per-match strike rate/economy for the same matches card["form"]["last_innings"]
    # lists runs for (both ordered oldest -> newest of the last 5) -- the raw
    # player_career row has no per-match breakdown, only career totals.
    recent_rows = criiq_db.execute(
        "SELECT date, opponent, runs, balls_faced, bat_strike_rate, "
        "       wickets, balls_bowled, economy "
        "FROM player_match_impact WHERE player_id = ? ORDER BY date DESC LIMIT 5",
        (player_id,),
    ).fetchall()
    recent_matches = [row_to_dict(r) for r in reversed(recent_rows)]

    role_row = criiq_db.execute(
        "SELECT primary_role, is_keeper, batting_position_median FROM player_role_final "
        "WHERE player_id = ? AND format = 'T20'", (player_id,),
    ).fetchone()
    is_keeper = bool(role_row["is_keeper"]) if role_row else False
    batting_position_median = role_row["batting_position_median"] if role_row else None

    return {
        "id": player_id,
        "identity": card.get("identity"),
        "status": player_status(card.get("status"), player_id, retired_ids),
        "form": card.get("form"),
        "form_percentile": rfi_percentile((card.get("form") or {}).get("rfi")),
        "latest_match": card.get("latest_match"),
        "career": card.get("career"),  # real {"batting": {...}, "bowling": {...}} breakdown
        "archetype": advanced_row["archetype"] if advanced_row else None,
        "strengths_summary": advanced.get("strengths"),  # list of plain-language lines
        "advanced": advanced,  # full profile: by-phase splits, vs-pace/vs-spin, six rate, etc.
        "phases": phases,
        "importance_score": impact.get("importance_score") if impact else None,
        "impact": impact,
        "opponents": opponents,
        "recent_matches": recent_matches,
        "is_keeper": is_keeper,
        "batting_position_median": batting_position_median,
        "position": position_label(role_row["primary_role"] if role_row else None, is_keeper, batting_position_median),
    }


@router.get("/players/compare")
def compare_players(ids: str):
    """9. GET /players/compare?ids=a,b,c — 2 or 3 full cards side by side.
    (Defined BEFORE /players/{id} so 'compare' isn't mistaken for an id.)"""
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if not 2 <= len(id_list) <= 3:
        raise HTTPException(400, "Give 2 or 3 comma-separated ids")
    cards = []
    for pid in id_list:
        detail = build_player_detail(pid)
        if not detail:
            raise HTTPException(404, f"Unknown player id: {pid}")
        cards.append(detail)
    return {"data": cards, "error": None}


@router.get("/players/{player_id}")
def player_detail(player_id: str):
    detail = build_player_detail(player_id)
    if not detail:
        raise HTTPException(404, "Unknown player id")
    return {"data": detail, "error": None}


# --------------------------------------------------------------------------
# 6. GET /players/{id}/vs/{opponent} — the "VS AUSTRALIA" widget
# --------------------------------------------------------------------------
@router.get("/players/{player_id}/vs/{opponent}")
def player_vs_opponent(player_id: str, opponent: str):
    row = criiq_db.execute(
        """SELECT * FROM player_vs_opponent
           WHERE player_id = ? AND LOWER(opponent) = LOWER(?)""",
        (player_id, opponent),
    ).fetchone()
    if not row:
        raise HTTPException(404, f"No record vs {opponent} for that player")
    return {"data": row_to_dict(row), "error": None}


# --------------------------------------------------------------------------
# 6b. GET /players/{id}/explain — per-feature SHAP breakdown for one matchup
# --------------------------------------------------------------------------
@router.get("/players/{player_id}/explain")
def player_explain(player_id: str, opponent: str, venue: str | None = None,
                   format: str = "T20", gender: str = "female"):
    try:
        result = model_bridge.explain_player(player_id, opponent, venue=venue, fmt=format, gender=gender)
    except model_bridge.ModelBridgeError as exc:
        raise HTTPException(422, str(exc))
    return {"data": result, "error": None}


# --------------------------------------------------------------------------
# 7 & 8. Add / edit / delete manually added players (app.db only)
# --------------------------------------------------------------------------
class PlayerBody(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    role: str = Field(min_length=3)          # Batsman / Bowler / All-rounder
    country: str | None = None
    batting_hand: str | None = None
    bowling_style: str | None = None
    status: str = "ACTIVE"


@router.post("/players", status_code=201)
def add_player(body: PlayerBody):
    info = app_db.execute(
        """INSERT INTO manual_players
           (name, country, role, batting_hand, bowling_style, status)
           VALUES (?,?,?,?,?,?)""",
        (body.name, body.country, ROLE_MAP.get(body.role.lower(), body.role.lower()),
         body.batting_hand, body.bowling_style, body.status.upper()),
    )
    app_db.commit()
    return {"data": {"id": f"m{info.lastrowid}", **body.model_dump()}, "error": None}


def manual_id_or_403(player_id: str) -> int:
    if not (player_id.startswith("m") and player_id[1:].isdigit()):
        raise HTTPException(403, "Only manually added players (m…) can be changed")
    return int(player_id[1:])


@router.put("/players/{player_id}")
def update_player(player_id: str, body: PlayerBody):
    mid = manual_id_or_403(player_id)
    info = app_db.execute(
        """UPDATE manual_players SET name=?, country=?, role=?, batting_hand=?,
           bowling_style=?, status=? WHERE id=?""",
        (body.name, body.country, ROLE_MAP.get(body.role.lower(), body.role.lower()),
         body.batting_hand, body.bowling_style, body.status.upper(), mid),
    )
    app_db.commit()
    if info.rowcount == 0:
        raise HTTPException(404, "Unknown player id")
    return {"data": {"id": player_id, **body.model_dump()}, "error": None}


@router.delete("/players/{player_id}")
def delete_player(player_id: str):
    mid = manual_id_or_403(player_id)
    info = app_db.execute("DELETE FROM manual_players WHERE id=?", (mid,))
    app_db.commit()
    if info.rowcount == 0:
        raise HTTPException(404, "Unknown player id")
    return {"data": {"deleted": player_id}, "error": None}


@router.post("/players/{player_id}/retire")
def retire_player(player_id: str, user: dict = Depends(require_user)):
    if player_id.startswith("m") and player_id[1:].isdigit():
        manual = app_db.execute(
            "SELECT country FROM manual_players WHERE id = ?", (int(player_id[1:]),)
        ).fetchone()
        if not manual:
            raise HTTPException(404, "Unknown player id")
        if manual["country"] != user["country"]:
            raise HTTPException(403, "You can only retire players from your own team")
        app_db.execute("UPDATE manual_players SET status = 'RETIRED' WHERE id = ?", (int(player_id[1:]),))
        app_db.commit()
        return {"data": {"id": player_id, "status": "RETIRED"}, "error": None}

    row = criiq_db.execute(
        """SELECT p.cricsheet_identifier, c.nationality
           FROM players p LEFT JOIN player_cards c ON c.player_id = p.player_id
           WHERE p.player_id = ?""",
        (player_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Unknown player id")

    player_country = roster_index.current_team(row["cricsheet_identifier"]) or row["nationality"]
    if player_country != user["country"]:
        raise HTTPException(403, "You can only retire players from your own team")

    app_db.execute(
        "INSERT INTO retired_players (player_id, retired_at) VALUES (?, datetime('now')) "
        "ON CONFLICT(player_id) DO UPDATE SET retired_at = datetime('now')",
        (player_id,),
    )
    app_db.commit()
    return {"data": {"id": player_id, "status": "RETIRED"}, "error": None}

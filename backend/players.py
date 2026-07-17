"""
players.py — everything about players (Phase 2).

Read endpoints pull from Sushma's criiq.db (read-only).
The Add Player form writes to OUR app.db instead — manually added players get
ids like "m1", "m2" so they can never clash with pipeline player ids (UUIDs).
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_user
from database import app_db, criiq_db

# every endpoint in this file requires a login token
router = APIRouter(tags=["players"], dependencies=[Depends(require_user)])

# The frontend uses friendly role names; the database uses lowercase ones.
ROLE_MAP = {"batsman": "batter", "bowler": "bowler", "all-rounder": "all-rounder",
            "allrounder": "all-rounder", "wicketkeeper": "wicketkeeper"}


def row_to_dict(row):
    return dict(row) if row is not None else None


# --------------------------------------------------------------------------
# 4. GET /players — searchable, filterable, paginated list
# --------------------------------------------------------------------------
@router.get("/players")
def list_players(search: str = "", role: str = "", status: str = "",
                 page: int = 1, limit: int = 20):
    limit = max(1, min(limit, 100))
    page = max(1, page)

    # Build the WHERE clause piece by piece depending on which filters are set.
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

    base_sql = f"""
        FROM players p
        JOIN player_registry r ON r.player_id = p.player_id
        LEFT JOIN player_cards c ON c.player_id = p.player_id
        LEFT JOIN player_styles s ON s.player_id = p.player_id
        WHERE {' AND '.join(where)}
    """
    total = criiq_db.execute(f"SELECT COUNT(*) AS n {base_sql}", params).fetchone()["n"]

    rows = criiq_db.execute(
        f"""SELECT p.player_id, p.canonical_name, c.nationality, c.role,
                   COALESCE(s.batting_hand, p.batting_hand) AS batting_hand,
                   COALESCE(s.bowling_style, p.bowling_style) AS bowling_style,
                   r.retirement_status, c.card_json
            {base_sql}
            ORDER BY c.matches_played DESC, p.canonical_name
            LIMIT ? OFFSET ?""",
        params + [limit, (page - 1) * limit],
    ).fetchall()

    players = []
    for row in rows:
        card = json.loads(row["card_json"]) if row["card_json"] else {}
        form = card.get("form", {})
        players.append({
            "id": row["player_id"],
            "name": row["canonical_name"],
            "country": row["nationality"],
            "role": row["role"],
            "batting_hand": row["batting_hand"],
            "bowling_style": row["bowling_style"],
            "status": row["retirement_status"],
            "last5_scores": (form.get("last_innings") or [])[-5:],
            "form_score": form.get("rfi"),        # Recent Form Index from the card
        })

    # Manually added players (from the Add Player form) appear on page 1.
    if page == 1:
        manual = app_db.execute(
            "SELECT * FROM manual_players WHERE name LIKE ?", (f"%{search}%",)
        ).fetchall()
        for m in manual:
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
        return d

    card_row = criiq_db.execute(
        "SELECT card_json FROM player_cards WHERE player_id = ?", (player_id,)
    ).fetchone()
    if not card_row:
        return None
    card = json.loads(card_row["card_json"])

    career = row_to_dict(criiq_db.execute(
        "SELECT * FROM player_career WHERE player_id = ?", (player_id,)
    ).fetchone())

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

    return {
        "id": player_id,
        "identity": card.get("identity"),
        "status": card.get("status"),
        "form": card.get("form"),
        "latest_match": card.get("latest_match"),
        "career": career,
        "archetype": advanced_row["archetype"] if advanced_row else None,
        "strengths_summary": advanced.get("strengths"),  # list of plain-language lines
        "phases": phases,
        "importance_score": impact.get("importance_score") if impact else None,
        "impact": impact,
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

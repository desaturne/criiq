"""
auth.py — sign up, login, and the "who is logged in?" check.

Flow: POST /auth/register (new account) or POST /auth/login (existing
account) with email+password -> we check the users table in auth.db -> if
correct, we hand back a JWT token (a signed string). The frontend then sends
that token on every request as the header:

    Authorization: Bearer <token>

require_user() below reads and verifies that header. Any endpoint that lists
it as a dependency automatically rejects requests without a valid token.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from database import auth_db

router = APIRouter(prefix="/auth", tags=["auth"])

# In development a default secret is fine; set JWT_SECRET in the environment
# for anything shared or deployed.
JWT_SECRET = os.environ.get("JWT_SECRET", "criiq-dev-secret-change-me")
TOKEN_HOURS = 12


def _issue_token(user) -> dict:
    """Create a session row + JWT for a user row, in the shape both
    /login and /register hand back to the frontend."""
    # jti (JWT ID) is stored in the sessions table so the token can be
    # revoked on logout instead of staying valid until it naturally expires.
    jti = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    auth_db.execute(
        "INSERT INTO sessions (jti, user_id, expires_at) VALUES (?, ?, ?)",
        (jti, user["id"], expires_at.isoformat()),
    )
    auth_db.commit()

    token = jwt.encode(
        {
            "id": user["id"],
            "name": user["name"],
            "role": user["role"],
            "country": user["country"],
            "status": user["status"],
            "jti": jti,
            "exp": expires_at,
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "role": user["role"],
            "country": user["country"],
            "status": user["status"],
        },
    }


class RegisterBody(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str
    password: str = Field(min_length=8)
    country: str = Field(min_length=2, max_length=40)


@router.post("/register", status_code=201)
def register(body: RegisterBody):
    exists = auth_db.execute(
        "SELECT 1 FROM users WHERE email = ?", (body.email,)
    ).fetchone()
    if exists:
        raise HTTPException(409, "An account with that email already exists")

    pw_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    info = auth_db.execute(
        "INSERT INTO users (email, password_hash, name, role, status, country) VALUES (?,?,?,?,?,?)",
        (body.email, pw_hash, body.name, "coach", "Inactive", body.country),
    )
    auth_db.commit()
    user = auth_db.execute(
        "SELECT * FROM users WHERE id = ?", (info.lastrowid,)
    ).fetchone()

    return {
        "data": {
            "message": "Registration submitted. Wait for admin approval before signing in.",
            "user": {
                "id": user["id"],
                "name": user["name"],
                "role": user["role"],
                "country": user["country"],
                "status": user["status"],
            },
        },
        "error": None,
    }


class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: LoginBody):
    user = auth_db.execute(
        "SELECT * FROM users WHERE email = ?", (body.email,)
    ).fetchone()
    ok = user and bcrypt.checkpw(
        body.password.encode(), user["password_hash"].encode()
    )
    if not ok:
        raise HTTPException(401, "Wrong email or password")
    if user["status"] != "Active":
        raise HTTPException(403, "Registration pending admin approval")

    return {"data": _issue_token(user), "error": None}


def require_user(request: Request) -> dict:
    """FastAPI dependency: returns the logged-in user, or raises 401."""
    header = request.headers.get("authorization", "")
    token = header[7:] if header.startswith("Bearer ") else None
    if not token:
        raise HTTPException(401, "Log in first (missing token)")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")

    live = auth_db.execute(
        "SELECT 1 FROM sessions WHERE jti = ? AND expires_at > ?",
        (payload.get("jti"), datetime.now(timezone.utc).isoformat()),
    ).fetchone()
    if not live:
        raise HTTPException(401, "Invalid or expired token")
    user = auth_db.execute("SELECT * FROM users WHERE id = ?", (payload.get("id"),)).fetchone()
    if not user or user["status"] != "Active":
        raise HTTPException(401, "Invalid or expired token")
    return {
        "id": user["id"],
        "name": user["name"],
        "role": user["role"],
        "country": user["country"],
        "status": user["status"],
        "jti": payload.get("jti"),
    }


@router.get("/me")
def me(user: dict = Depends(require_user)):
    return {
        "data": {
            "name": user["name"],
            "role": user["role"],
            "country": user["country"],
            "status": user["status"],
        },
        "error": None,
    }


@router.get("/admin/pending-coaches")
def pending_coaches():
    rows = auth_db.execute(
        "SELECT id, name, email, role, status, country FROM users WHERE role = ? AND status = ? ORDER BY id DESC",
        ("coach", "Inactive"),
    ).fetchall()
    return {
        "data": [
            {
                "id": row["id"],
                "name": row["name"],
                "email": row["email"],
                "role": row["role"],
                "status": row["status"],
                "country": row["country"],
            }
            for row in rows
        ],
        "error": None,
    }


class ReviewBody(BaseModel):
    status: str = Field(pattern="^(Active|Inactive|Suspended)$")


@router.post("/admin/pending-coaches/{user_id}")
def review_coach(user_id: int, body: ReviewBody):
    user = auth_db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user or user["role"] != "coach":
        raise HTTPException(404, "Coach registration not found")
    auth_db.execute("UPDATE users SET status = ? WHERE id = ?", (body.status, user_id))
    auth_db.commit()
    return {"data": {"id": user_id, "status": body.status}, "error": None}


@router.post("/logout")
def logout(user: dict = Depends(require_user)):
    auth_db.execute("DELETE FROM sessions WHERE jti = ?", (user.get("jti"),))
    auth_db.commit()
    return {"data": {"logged_out": True}, "error": None}

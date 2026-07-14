"""
auth.py — login and the "who is logged in?" check.

Flow: POST /auth/login with email+password -> we check the users table in
app.db -> if correct, we hand back a JWT token (a signed string). The frontend
then sends that token on every request as the header:

    Authorization: Bearer <token>

require_user() below reads and verifies that header. Any endpoint that lists
it as a dependency automatically rejects requests without a valid token.
"""

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from database import app_db

router = APIRouter(prefix="/auth", tags=["auth"])

# In development a default secret is fine; set JWT_SECRET in the environment
# for anything shared or deployed.
JWT_SECRET = os.environ.get("JWT_SECRET", "criiq-dev-secret-change-me")
TOKEN_HOURS = 12


class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: LoginBody):
    user = app_db.execute(
        "SELECT * FROM users WHERE email = ?", (body.email,)
    ).fetchone()
    ok = user and bcrypt.checkpw(
        body.password.encode(), user["password_hash"].encode()
    )
    if not ok:
        raise HTTPException(401, "Wrong email or password")

    token = jwt.encode(
        {
            "id": user["id"],
            "name": user["name"],
            "role": user["role"],
            "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS),
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    return {
        "data": {
            "token": token,
            "user": {"id": user["id"], "name": user["name"], "role": user["role"]},
        },
        "error": None,
    }


# HTTPBearer tells FastAPI (and its /docs page) that we use Bearer tokens —
# this is what makes the "Authorize" button appear in the docs.
bearer_scheme = HTTPBearer(auto_error=False)


def require_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """FastAPI dependency: returns the logged-in user, or raises 401."""
    if creds is None:
        raise HTTPException(401, "Log in first (missing token)")
    try:
        return jwt.decode(creds.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")


@router.get("/me")
def me(user: dict = Depends(require_user)):
    return {"data": {"name": user["name"], "role": user["role"]}, "error": None}

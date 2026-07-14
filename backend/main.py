"""
main.py — the entry point. Run with:  uvicorn main:app --reload

This file only wires things together:
  - creates the FastAPI app
  - allows the frontend (a different localhost port) to call us (CORS)
  - makes every error come back in the same JSON shape as successes:
        {"data": ..., "error": null}      on success
        {"data": null, "error": "why"}    on failure
  - plugs in the route files: auth.py, players.py, matches.py, selection.py

Interactive docs are free with FastAPI: start the server and open
http://localhost:8000/docs to click through and try every endpoint.
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import auth
import matches
import players
import selection
from database import criiq_db

app = FastAPI(title="CRIIQ API", version="0.1.0")

# CORS: the frontend runs on another port (e.g. localhost:5173), and browsers
# block cross-port requests unless the server opts in. "*" is fine for dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- consistent error shape --------------------------------------------------
@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code,
                        content={"data": None, "error": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    first = exc.errors()[0]
    field = ".".join(str(p) for p in first["loc"] if p != "body")
    return JSONResponse(status_code=422,
                        content={"data": None,
                                 "error": f"{field}: {first['msg']}"})


# --- Phase 1: health ---------------------------------------------------------
@app.get("/health")
def health():
    n = criiq_db.execute("SELECT COUNT(*) AS n FROM matches").fetchone()["n"]
    return {"status": "ok", "db_connected": n > 0}


# --- plug in the endpoint groups ----------------------------------------------
app.include_router(auth.router)        # /auth/login, /auth/me
app.include_router(players.router)     # /players...
app.include_router(matches.router)     # /matches..., /dashboard..., /ticker
app.include_router(selection.router)   # /selection..., /recommendations, /winprob

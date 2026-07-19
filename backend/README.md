# CRIIQ Backend API

The REST API between the frontend dashboard and the data/AI layers.
Built with **FastAPI** (Python). It reads the analytics database produced by
the `data-collection` pipeline and owns a small database of its own.

## Setup & run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# the analytics DB must exist first (one-time, takes ~2 min):
#   cd ../data-collection && pip install -r requirements.txt && python run.py refresh

uvicorn main:app --reload
```

Server: http://localhost:8000 — interactive docs at **http://localhost:8000/docs**
(you can try every endpoint from the browser there).

## Login / sign up

Seeded demo user (created automatically on first run):

- email: `rahul@criiq.local`
- password: `coach1234`

New accounts: `POST /auth/register` with `{"name", "email", "password"}` (password
8+ chars) creates a user — everyone who self-registers gets the `coach` role —
and, like `/auth/login`, immediately returns a JWT token. Duplicate emails get
a 409.

`POST /auth/login` returns a JWT token. Send it on every other request:
`Authorization: Bearer <token>`. In `/docs`, click **Authorize** and paste the token.
`POST /auth/logout` revokes that token server-side (its session row is deleted,
so reusing it afterward gets a 401 even though it hasn't expired yet).

## The three databases

| File | Owner | Access | Contents |
|---|---|---|---|
| `../data-collection/data/criiq.db` | pipeline | **read-only** | matches, deliveries, players, cards, careers… |
| `backend/app.db` | this API | read-write | fixtures, saved XIs, manually added players |
| `backend/auth.db` | this API | read-write | users, login sessions |

Both `app.db` and `auth.db` are created and seeded automatically the first
time the server starts. They're kept separate on purpose: deleting `app.db`
to reset fixtures/selections/manual players can never accidentally wipe out
user accounts. Delete `auth.db` to reset users/sessions.

## Endpoints

Everything returns `{"data": ..., "error": null}` (or `{"data": null, "error": "why"}`).

**Phase 1 — foundations**
- `GET /health`
- `POST /auth/register` · `POST /auth/login` · `GET /auth/me` · `POST /auth/logout`

**Phase 2 — players & squads**
- `GET /players?search=&role=&status=&page=&limit=`
- `GET /players/{id}` — full card (career, form, phases, archetype, importance)
- `GET /players/{id}/vs/{opponent}`
- `POST /players` · `PUT /players/{id}` · `DELETE /players/{id}` — manual players only (ids `m1`, `m2`…)
- `GET /players/compare?ids=a,b,c` (2–3 ids)

**Phase 3 — matches & dashboard**
- `GET /matches` — upcoming fixtures (`f1`, `f2`…) + recent completed
- `GET /matches/{id}`
- `GET /dashboard/summary` · `GET /dashboard/alerts` · `GET /ticker`

**Phase 4 — selection & AI**
- `GET /selection/{match_id}` · `PUT /selection/{match_id}` — body `{"xi": [], "extra": [], "excluded": []}`, max 11 in the XI
- `POST /recommendations` — body `{"opponent": "...", "venue": "...", "team": "India", "gender": "female"}` (only `opponent` required)
- `GET /winprob?innings=2&balls_remaining=30&wickets=4&runs_required=40`

## The AI — real model, wired in

`ai_model.py` is the live wiring. It calls the two real models as subprocesses
(each has its own folder + virtualenv + heavy deps, so we don't merge them into
the backend's env):

- **Recommendations** → `model-training/criiq_models` (trained per gender). Run
  once after any data change: `cd model-training && python -m criiq_models.cli
  train --gender female` and `--gender male`.
- **Win probability** → `data-collection`'s empirical model (`criiq_data.cli
  winprob --state ...`).

If a subprocess fails (model not trained, timeout, bad arg), `ai_model.py`
falls back to `ai_stub.py` so the API always answers. `winprob` responses now
report `"model": "empirical"` when the real model answered, `"stub"` otherwise.

**Prerequisite:** the recommendation model needs the WPA + role tables, which
`refresh` does NOT build. After `python run.py refresh`, also run:
`python run.py wpa` and `python run.py role-finalize`, then train the models.

## File map

| File | Job |
|---|---|
| `main.py` | app setup, CORS, error shape, health, mounts the routers |
| `database.py` | opens criiq.db (read-only) + app.db + auth.db (ours), creates/seeds tables |
| `auth.py` | login/logout, JWT check (`require_user`), `/auth/me` |
| `players.py` | player list/detail/vs/compare + add/edit/delete manual players |
| `matches.py` | matches, dashboard summary + alerts, ticker |
| `selection.py` | playing XI save/load, recommendations, winprob |
| `ai_model.py` | calls the REAL models (recommend + winprob) as subprocesses; falls back to `ai_stub` |
| `ai_stub.py` | fake AI kept as the graceful fallback |

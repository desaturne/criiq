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

## Login

Seeded demo user (created automatically on first run):

- email: `rahul@criiq.local`
- password: `coach1234`

`POST /auth/login` returns a JWT token. Send it on every other request:
`Authorization: Bearer <token>`. In `/docs`, click **Authorize** and paste the token.

## The two databases

| File | Owner | Access | Contents |
|---|---|---|---|
| `../data-collection/data/criiq.db` | pipeline | **read-only** | matches, deliveries, players, cards, careers… |
| `backend/app.db` | this API | read-write | users, fixtures, saved XIs, manually added players |

`app.db` is created and seeded automatically the first time the server starts.
Delete it to reset users/fixtures/selections.

## Endpoints

Everything returns `{"data": ..., "error": null}` (or `{"data": null, "error": "why"}`).

**Phase 1 — foundations**
- `GET /health`
- `POST /auth/login` · `GET /auth/me`

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
- `POST /recommendations` — body `{"opponent": "...", "venue": "..."}`
- `GET /winprob?innings=2&balls_remaining=30&wickets=4&runs_required=40`

## Swapping in the real AI model

`ai_stub.py` fakes `get_recommendations(match_context)` and
`get_win_probability(state)`. When the real model is ready, replace that module
(keeping the same function names/arguments) — no other file changes.

## File map

| File | Job |
|---|---|
| `main.py` | app setup, CORS, error shape, health, mounts the routers |
| `database.py` | opens criiq.db (read-only) + app.db (ours), creates/seeds tables |
| `auth.py` | login, JWT check (`require_user`), `/auth/me` |
| `players.py` | player list/detail/vs/compare + add/edit/delete manual players |
| `matches.py` | matches, dashboard summary + alerts, ticker |
| `selection.py` | playing XI save/load, recommendations, winprob |
| `ai_stub.py` | placeholder AI — replaced later by the real model |

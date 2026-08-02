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

New accounts: `POST /auth/register` with `{"name", "email", "password", "country"}`
(password 8+ chars) creates a coach registration in **Inactive** state. The
admin reviews pending coach registrations from `GET /auth/admin/pending-coaches`
and approves them by posting `{"status": "Active"}` to
`POST /auth/admin/pending-coaches/{user_id}`. Until a coach is approved,
`POST /auth/login` rejects the sign-in with a pending-approval error. Duplicate
emails get a 409.

`POST /auth/login` returns a JWT token. Send it on every request under
`/players`, `/matches`, `/selection`, and the simulation group:
`Authorization: Bearer <token>`. In `/docs`, click **Authorize** and paste the token.
The two `/auth/admin/pending-coaches` routes are the exception — they currently
take no token at all, so anyone who can reach the API can read pending
registrations and approve or suspend a coach. Put them behind `require_user`
(plus an admin role check) before this is exposed beyond localhost.
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
- `GET /matches?completed_limit=&gender=&country=&team1=&team2=` — upcoming fixtures (`f1`, `f2`…) + recent completed
- `GET /matches/{id}`
- `GET /matches/{id}/scorecard` — per-player batting/bowling figures rebuilt from
  ball-by-ball `deliveries`. Completed matches only: a fixture (`f1`…) hasn't been
  played, so it answers 400.
- `GET /teams?gender=` — the team names `/matches` and the AI endpoints accept
- `GET /dashboard/summary` · `GET /dashboard/alerts` · `GET /ticker`

**Phase 4 — selection & AI**
- `GET /selection/{match_id}` · `PUT /selection/{match_id}` — body `{"xi": [], "extra": [], "excluded": []}`, max 11 in the XI
- `POST /recommendations` — body `{"opponent": "...", "venue": "...", "team": "India", "gender": "female", "format": "T20", "auto_opponent_xi": false}` (everything but `opponent` optional). `auto_opponent_xi` also picks the opposition's probable XI and uses it to switch team-level matchups for real player-vs-player head-to-head.
- `GET /winprob?innings=2&balls_remaining=30&wickets=4&runs_required=40&gender=female&format=T20`

**Phase 5 — simulation & optimization** (calls `model-training` directly, no fake fallback — errors come back as the engine's own message)

Every XI below is given as **`player_id`s, never names** — a display name can be
genuinely ambiguous (two players sharing a short name), which the model refuses
to guess. Each id list must hold exactly 11 entries.

- `POST /analyze-xi` — body `{"team", "opponent", "player_ids": [11], "venue?", "format?", "gender?"}` — scores a coach's own hand-picked XI and compares it to the AI's optimal pick
- `POST /simulate` — body `{"team1", "team2", "team1_player_ids": [11], "team2_player_ids": [11], "toss_winner", "n_simulations?": 1-200, "force_dismissal?", "venue?", "format?", "gender?"}` — ball-by-ball Monte Carlo match simulation: scores, scorecards, bowling rotation, key moments, win-probability timeline
- `POST /optimize-bowling` — body `{"bowling_team", "batting_team", "bowling_player_ids": [11], "batting_player_ids": [11], "venue?", "format?", "gender?"}` — GA-searched bowler-to-over rotation
- `POST /optimize-batting` — body `{"batting_team", "bowling_team", "batting_player_ids": [11], "bowling_player_ids": [11], "target?", "venue?", "format?", "gender?"}` — GA-searched batting order

`gender` defaults to `female` on every one of these. Pass `"male"` explicitly for
a men's XI — otherwise the ids fall outside the scoped roster and the endpoint
answers with an empty `xi` and all 11 ids under `missing_player_ids`.
`format` accepts either `"T20"` or `"T20I"`; both normalize to the `T20` scope
the model artifacts are keyed by (`model_bridge.normalize_format`).

## The real AI model — model-training / criiq_models

`ai_stub.py` fakes `get_recommendations(match_context)` and
`get_win_probability(state)` **only as a fallback** — both now call the real
engine in `../model-training` (`criiq_models`) first, through `model_bridge.py`,
which shells out to `python -m criiq_models.cli ... --json` rather than
importing it directly (that package's pandas/numpy/scikit-learn/scipy
dependencies are intentionally kept out of this backend's venv). If the real
engine errors (models not trained yet, win-prob grids missing), `ai_stub.py`
logs a warning and serves the original hand-written fake data instead of
breaking the response — the same function names/arguments as before, so no
other file needed to change for that swap.

`simulation.py`'s four endpoints (`/simulate`, `/optimize-bowling`,
`/optimize-batting`, `/analyze-xi`) are new capabilities with nothing to fall
back to, so a `model_bridge` failure there becomes a 422 with the engine's own
error text.

**Setup**: `model-training` has its own, separate dependencies — install them
in its own venv (`cd ../model-training && pip install -r requirements.txt`),
then train the models it needs at least once per gender:
`python -m criiq_models.cli train --gender female` and `--gender male`. Win
probability additionally needs data-collection's grids
(`cd ../data-collection && python -m criiq_data.cli winprob`).

Two env vars point this backend at that other venv:
- `MODEL_TRAINING_DIR` — path to the `model-training` directory (default: `../model-training`)
- `MODEL_TRAINING_PYTHON` — path to the Python interpreter inside model-training's venv (default: this backend's own `sys.executable`, which only works if you installed both sets of dependencies into the same environment)

## File map

| File | Job |
|---|---|
| `main.py` | app setup, CORS, error shape, health, mounts the routers |
| `database.py` | opens criiq.db (read-only) + app.db + auth.db (ours), creates/seeds tables |
| `auth.py` | login/logout, JWT check (`require_user`), `/auth/me` |
| `players.py` | player list/detail/vs/compare + add/edit/delete manual players |
| `matches.py` | matches, dashboard summary + alerts, ticker, real scorecard |
| `selection.py` | playing XI save/load, recommendations, winprob |
| `simulation.py` | match simulation + batting/bowling optimization + analyze-XI |
| `model_bridge.py` | shells out to `model-training`'s CLI (`--json`); raises `ModelBridgeError` on failure |
| `ai_stub.py` | calls `model_bridge` for recommend/winprob; falls back to hand-written stub data if it fails |
| `roster_index.py` | in-memory index of which players play for which team/gender (from real appearances) |

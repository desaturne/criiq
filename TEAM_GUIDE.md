# CRIIQ — Team Guide

*How the pieces fit together, what's done, and what each person does next.*
*Last updated: 13 July 2026*

```
Sushma (data)            Dipa (backend)              Frontend teammate
┌──────────────────┐     ┌──────────────────┐        ┌──────────────────┐
│ criiq_data       │     │ FastAPI REST API │        │ Dashboard web app│
│ Python pipeline  ├────▶│ localhost:8000   │◀───────┤ calls the API    │
│ builds criiq.db  │read │ + its own app.db │  HTTP  │ with JWT token   │
└──────────────────┘only └────────┬─────────┘        └──────────────────┘
                                  │ imports (later)
                         ┌────────┴─────────┐
                         │ AI teammate:      │
                         │ replaces ai_stub  │
                         └───────────────────┘
```

---

## 1. What is DONE (the backend — Dipa)

A complete REST API in `backend/` (Python + FastAPI, ~9 small files).
All 17 endpoints below are **built and tested against real data**.

**Auth** — `POST /auth/login`, `GET /auth/me`. JWT tokens, 12-hour expiry.
Demo account (auto-created): `rahul@criiq.local` / `coach1234`, role coach.
Every endpoint except `/health` and `/auth/login` requires the header
`Authorization: Bearer <token>`.

**Players** — list with `?search=&role=&status=&page=&limit=` (returns name,
country, role, status, last-5 scores, form score); full player card
(career batting+bowling, form, phase splits, archetype, strengths,
importance score); record vs one opponent; compare 2–3 players; Add/Edit/
Delete for manually added players (their ids look like `m1`, `m2`).

**Matches & dashboard** — upcoming fixtures + completed matches with each
team's last-5 W/L; match detail with innings scores; dashboard summary
(squad counts, next match, win probability); form alerts; performance ticker.

**Selection & AI** — save/load the Playing XI per match (max 11, no
duplicates, stored in `app.db`); `POST /recommendations` and `GET /winprob`
(currently answered by `ai_stub.py` — fake but realistically shaped).

**Response shape (every endpoint, always):**
```json
{ "data": <the result>, "error": null }        // success
{ "data": null, "error": "human-readable why" } // failure (+ proper status code)
```

**Run it:**
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload        # -> http://localhost:8000
```

---

## 2. What the FRONTEND teammate should do

**Zero setup on your side** — CORS is already enabled, call the API from any
localhost port.

**Start here:** run the backend (5 commands above — but first ask Dipa or see
§3 to build `criiq.db` once), then open **http://localhost:8000/docs**. That
page lists every endpoint, lets you click "Authorize", paste a token, and try
real requests in the browser. It is the living API contract.

**The flow your app implements:**

1. **Login screen** → `POST /auth/login` with `{"email","password"}` →
   store `data.token` (e.g. localStorage) → send it on every request:
   ```js
   fetch("http://localhost:8000/players?search=mandhana", {
     headers: { Authorization: `Bearer ${token}` }
   }).then(r => r.json()).then(({ data, error }) => ...);
   ```
2. **Always unwrap the envelope**: check `error` first; the payload is in `data`.
   401 means the token expired → send the user back to login.

**Screen → endpoint map:**

| Your screen | Call |
|---|---|
| Dashboard (Match Command Center) | `GET /dashboard/summary`, `GET /dashboard/alerts`, `GET /ticker` (poll ticker every few seconds — no websockets) |
| Player Form | `GET /players/{id}` (career, form, phases, archetype, strengths, importance) |
| "VS AUSTRALIA" widget | `GET /players/{id}/vs/Australia` |
| Squads | `GET /players?search=&role=&status=&page=&limit=` |
| Add Player form | `POST /players` (then `PUT`/`DELETE /players/m…` to edit) |
| Player Comparison modal | `GET /players/compare?ids=id1,id2,id3` |
| Matches | `GET /matches`, `GET /matches/{id}` (fixture ids: `f1`; completed ids: numeric) |
| Squad Selection (Playing XI) | `GET /selection/{match_id}` and `PUT /selection/{match_id}` with `{"xi":[…],"extra":[…],"excluded":[…]}` |
| Recommendations | `POST /recommendations` with `{"opponent","venue"}` |
| Win probability bar | `GET /winprob?innings=2&balls_remaining=30&wickets=4&runs_required=40` |
| Reports / AI Assistant | not built yet — show a "coming soon" state |

**Heads-up on data quirks:** `batting_hand`, `bowling_style` and some
`country` fields are often `null` right now (see §3) — design for missing
values. Player ids are long UUID strings, not numbers.

---

## 3. What the DATA teammate (Sushma) should do

Your pipeline is the foundation and it already works end-to-end — the backend
reads `data-collection/data/criiq.db` **read-only** and never writes to it.

1. **Nothing to change in your code.** The backend consumes: `players`,
   `player_registry`, `player_cards` (incl. `card_json` → `form.last_innings`,
   `form.rfi`), `player_career`, `player_advanced` (incl. `profile_json` →
   `strengths`), `player_impact`, `player_phase`, `player_vs_opponent`,
   `dismissal_matchup`, `player_styles`, `matches`, `deliveries`.
   ⚠️ If you rename any of these tables/columns/JSON keys, tell Dipa — the
   API queries them by name.
2. **Re-run `python run.py refresh` before demos** so the "latest match" data
   is fresh. The backend picks up the new file automatically on restart.
3. **The gaps that show as `null` in the API** (all optional, your README
   documents them):
   - `styles --seed` and `styles --wiki` → fills batting hand / bowling
     style / nationality (powers the vs-pace/vs-spin splits too);
   - the ICC rankings CSV (`rankings --scaffold`) → fills `icc_rank`;
   - these would visibly improve the Squads screen and player cards.
4. **Each teammate must build the DB once on their own laptop** (it's not in
   git — only the code is): `cd data-collection && pip install -r
   requirements.txt && python run.py refresh` (~2 minutes).

---

## 4. What the AI teammate should do (when ready)

Replace `backend/ai_stub.py` with the real model, keeping the two function
signatures exactly:

```python
get_recommendations(match_context: dict) -> list[dict]   # ranked, with "reason"
get_win_probability(state: dict) -> dict                  # probabilities + phase
```

Same names, same arguments, same return shape → no other backend file changes.
The win-probability training data already exists: `ball_state` /
`win_prob` parquet files under `data-collection/data/features/`.

---

## 5. Who owns which files

| Area | Owner | Location | May others edit? |
|---|---|---|---|
| Data pipeline + criiq.db | Sushma | `data-collection/` | read-only for everyone else |
| REST API + app.db | Dipa | `backend/` | via PRs |
| AI model (stub for now) | AI teammate | `backend/ai_stub.py` | swap keeping the interface |
| Web dashboard | Frontend teammate | `frontend/` (to create) | — |

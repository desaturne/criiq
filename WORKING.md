# Criiq — How the System Actually Works, End to End

This is the one document that crosses all three parts of the repo — `frontend/`, `backend/`, `model-training/` — and traces, for every real user-facing capability, the exact chain of functions that makes it happen: which UI action calls which API function, which backend route handles it, which model-training function (or CLI subcommand) actually does the work, and what comes back. Nothing here is aspirational — every function/file named below was confirmed present in the codebase as it exists right now, not assumed from an earlier version of the code or an earlier plan.

**How this fits with the repo's other docs** (read this first if you're new; it tells you where to go next for depth):

| Doc | Answers |
|---|---|
| **`WORKING.md`** (this file) | "When a user does X, what code actually runs, in what order, across the whole stack?" |
| `model-training/ALGORITHMS.md` | "Why this algorithm/model and not another? What's the math?" — MILP, genetic algorithms, WPA regression, Monte Carlo simulation, SHAP, data pipeline. |
| `model-training/CODE_WALKTHROUGH.md` | File-by-file: what every function in `model-training/criiq_models/` does internally. |
| `data-collection/CODE_WALKTHROUGH.md` | File-by-file: what every function in `data-collection/criiq_data/` does internally (the pipeline that builds `criiq.db`). |
| `model-training/VALIDATION_REPORT.md` | "Does it actually work, and how accurate is it, on real data?" — including §11, which tests the two deliverables coaches actually use (XI recommendation, match simulation) against real historical matches the models never trained on. |
| `data-collection/dataset_analysis.ipynb` | Full description/shape/size/outlier/EDA analysis of the underlying dataset. |

No document above traces across the frontend/backend/model-training boundary — each is scoped to one package. That gap is what this file fills.

---

## 1. The three layers, and how they actually talk to each other

```
┌─────────────────────┐        HTTP/JSON         ┌──────────────────────┐      subprocess (JSON stdout)      ┌───────────────────────────┐
│  frontend/           │  ───────────────────►    │  backend/             │  ─────────────────────────────►    │  model-training/          │
│  React + Vite        │  ◄───────────────────    │  FastAPI              │  ◄─────────────────────────────    │  criiq_models (CLI)       │
│  (localhost:5173)     │   {data, error}          │  (localhost:8000)     │   `python -m criiq_models.cli ...` │  (its own separate venv)  │
└─────────────────────┘                          └──────────┬────────────┘                                   └─────────────┬─────────────┘
                                                              │ read-only SQLite                                            │ read-only SQLite
                                                              ▼                                                              ▼
                                                    data-collection/data/criiq.db  ◄───────── built by data-collection/criiq_data's pipeline
```

**Why a subprocess, not an in-process import, between `backend/` and `model-training/`?** `model-training`'s `criiq_models` package depends on `scikit-learn`, `shap`, `scipy`, etc. — a real ML stack. `backend/model_bridge.py`'s own module docstring states the reason directly: keeping those dependencies out of the backend's own virtual environment. Every call from the backend into the model layer goes through exactly one function, `model_bridge.run_cli()`, which shells out to `python -m criiq_models.cli <subcommand> ...` in `model-training`'s own `.venv`, and parses whatever JSON that process printed to stdout. If that subprocess fails for any reason (bad args, timeout, no output), `run_cli` raises `ModelBridgeError` — which most routes convert into an HTTP 422 (`players.py`'s `/explain`, and all four routes in `simulation.py`, via each module's own catch). Two routes are the exception: `/recommendations` and `/winprob` go through `ai_stub.py`, which **catches** `ModelBridgeError` internally and serves a hardcoded fallback instead of raising (see §4, §10) — so a model-layer failure there degrades gracefully rather than surfacing as an error.

**Why the backend, and not the frontend, talks to `criiq.db` directly for anything that's just a lookup (not a model computation)?** Things like "list of past matches," "player search," "team names" are answered by the backend reading `criiq.db` directly with plain SQL (`database.py`'s `criiq_db` connection, opened **read-only** — the backend, like `model-training`, never writes to the pipeline's own database). Only things that need the actual trained models or the simulator (recommendations, XI analysis, match simulation, GA optimizers, SHAP explanations) go through `model_bridge` into `model-training`.

**Three SQLite files, three different owners** (`backend/database.py`):
- `criiq.db` — owned by `data-collection`'s pipeline. Backend and model-training both only read it.
- `app.db` — the backend's own database (fixtures, manual players, saved squad selections).
- `auth.db` — login credentials and sessions, kept separate so resetting `app.db` can never accidentally wipe user accounts.

---

## 2. Authentication — every request after this point assumes it

**Frontend:** `lib/api.ts`'s `login`/`register`/`logout`/`me`, called from `pages/auth/LoginPage.tsx` and `app/App.tsx`'s `AppWithAuth` (which restores a persisted token on load via `api.me()`).

**Backend (`auth.py`):**
- `POST /auth/register` → inserts into `auth_db.users` with `status="Inactive"` (bcrypt-hashed password) — a new coach account needs approval before it can log in.
- `POST /auth/login` → checks `status == "Active"`, then `_issue_token(user)` (inserts an `auth_db.sessions` row and signs a JWT containing the session's `jti`).
- `require_user(request)` — the FastAPI dependency every other router (`players`, `matches`, `selection`, `simulation`) is gated on at the router level (`dependencies=[Depends(require_user)]`). Decodes the JWT, checks the `sessions` table for a still-live `jti`, and re-checks the user's current `status == "Active"` (so revoking a coach mid-session actually takes effect on their very next request, not just their next login).
- `GET /auth/admin/pending-coaches` / `POST /auth/admin/pending-coaches/{id}` — list/approve/reject pending coach signups. **Known gap, worth knowing about:** neither of these two routes has `Depends(require_user)` or any role check — confirmed by reading the file directly. Anyone who can reach the backend can list pending coaches and change any coach's status. Not model-layer-related, but a real gap in the current system worth fixing before this goes anywhere production-adjacent.

**Model-training involvement:** none. Authentication is entirely a backend/frontend concern.

---

## 2b. The admin portal — the real caller of §2's unguarded routes

**Frontend:** a separate, client-side-authenticated shell entered via `AdminLoginPage` → `app/App.tsx`'s `admin-app` mode (`AdminShell.tsx`), distinct from the coach-facing app. Two pages actually exercise the backend's admin routes: `admin/pages/AdminOverview.tsx` and `admin/pages/AdminUsers.tsx`, both calling `api.pendingCoachRegistrations()` (`GET /auth/admin/pending-coaches`) to list signups awaiting approval, and `api.reviewCoachRegistration(userId, status)` (`POST /auth/admin/pending-coaches/{id}`) to approve/reject/suspend one.

**Why this matters beyond §2's gap note:** the two unguarded backend routes aren't dead or theoretical — they're the entire data path for a real, working admin feature. §12's "known gap" framing (no `Depends(require_user)`, no role check) should be read with this in mind: it's not an unused endpoint sitting there by accident, it's backing live coach-approval workflows with no server-side auth at all, only whatever gate (if any) `AdminLoginPage`/`AdminShell.tsx` enforce client-side.

---

## 3. Player search, profile, and comparison

**Frontend:** `pages/DashboardPage.tsx` ("Player Form") and `pages/BuildXiPage.tsx` both list players via `api.listPlayers(...)`; `pages/PlayerProfilePage.tsx` shows one player's full detail; `components/player/PlayerCompareModal.tsx` compares 2-3.

**Backend (`players.py`):**
- `GET /players` → `list_players`. Builds a SQL `WHERE` clause from `search`/`role`/`status` against `criiq_db.players`/`player_registry`/`player_cards`; filters by `country`/`gender` using an **in-memory index** (`roster_index.py`'s `team_members`/`gender_members`, built once at import time from real match-appearance data — deliberately *not* trusting `players.nationality`, which the module's own comment flags as unreliable via a real found case). Applies eligibility filters (excludes retired/stale players) unless a `status` was explicitly requested, with a relaxed fallback if a country filter would leave fewer than 11 candidates. Each result row is mapped through `mappers.ts`'s `mapApiPlayerListItem` on the frontend.
- `GET /players/{id}` → `build_player_detail(player_id)` — the big assembly function: joins `player_cards`, `player_advanced`, `player_impact`, `player_phase`, `player_vs_opponent`, `player_match_impact`, `player_role_final` into one payload. Frontend maps it via `mapApiPlayerDetail`.
- `GET /players/{id}/vs/{opponent}` → single `player_vs_opponent` row; frontend patches it onto an already-mapped player via `applyVsOpponent`.
- `GET /players/{id}/explain` → **this is the one player-detail route that goes into `model-training`**: calls `model_bridge.explain_player(player_id, opponent, venue, fmt, gender)`, which runs `criiq_models.cli explain --player-id ... --shap`. That CLI command (`cmd_explain` in `cli.py`) calls `RecommendationScorer.score()` for that one player, `recommend/explain.py`'s `explain()` for the plain-language breakdown, and — because `--shap` is passed — `recommend/shap_explain.py`'s `explain_prediction()` for the exact per-feature SHAP attribution (§3.11 of `ALGORITHMS.md` covers the SHAP mechanics in depth). This is the only place in the whole system where a single player's WPA prediction gets a formal, additive feature-attribution breakdown, as opposed to `explain()`'s narrative summary.
- `GET /players/compare?ids=...` — defined (`comparePlayers` in `api.ts`) but **not currently called from anywhere in the frontend**; `PlayerCompareModal.tsx` does its own per-player `getPlayer`/`getPlayerVsOpponent` fetches instead. Dead code, not a bug — just unused.

---

## 3b. Squad roster management (manual-player CRUD) and retirement

Two real flows missing from an earlier version of this doc, both in `players.py`, neither touching `model-training`.

**Squad roster CRUD (`pages/SquadsPage.tsx`, routed at `/squads`):** a full roster-management screen distinct from Build XI — search/filter by role and status, CSV export (`exportToCSV`, `handleExportAll`, `handleExportSelected`), bulk-deactivate, and an Add/Edit Player slide-in panel (`handleAddPlayer`, `openEdit`, `handleDelete`).
- `POST /players` → `add_player` — inserts into `app_db.manual_players`, returning a synthetic id prefixed `m` (e.g. `m17`) so manually-added players are always distinguishable from real Cricsheet-sourced `player_id`s.
- `PUT /players/{id}` / `DELETE /players/{id}` → `update_player`/`delete_player` — both gated by `manual_id_or_403` (only an `m`-prefixed id can be mutated this way; a real player's Cricsheet-sourced row can't be edited or deleted through this path at all). **Worth knowing:** neither checks that the manual player belongs to the calling coach's own team — any authenticated coach can edit or delete *any* other coach's manually-added players, not just their own. This is narrower than §12's two fully-unauthenticated admin routes (it still requires a valid login, via the router-level `Depends(require_user)`), but it's a real missing ownership check, not by design.

**Player retirement (`pages/PlayerProfilePage.tsx`'s "Retired?" confirm dialog → `handleRetire` → `api.retirePlayer`):**
- `POST /players/{player_id}/retire` → `retire_player` — branches on whether the id is a manual (`m`-prefixed) or real player. For a **manual** player: checks `manual_players.country == user["country"]` (403 if not the coach's own team), then flips `status` to `'RETIRED'` in place. For a **real** player: resolves their current team via `roster_index.current_team(cricsheet_identifier)` (falling back to `player_cards.nationality` — the same "don't trust the stored nationality field alone" caution as §3's `roster_index.py` note), checks it against the coach's own team, then upserts into `app_db.retired_players` (a real player is never deleted or mutated in `criiq.db`, which this backend never writes to — retirement is recorded entirely in the backend's own `app.db`). Unlike the CRUD routes above, this one *does* enforce ownership correctly on both branches.
- This is the write side of what §13's FAQ ("What happens to a retired player?") only describes from the read side (`roster.team_pool` exclusion in `model-training`, `players.retired_names` checks elsewhere in the backend) — a coach can actually trigger this from the UI, it isn't only a data-pipeline concept.

---

## 4. AI Playing-XI Recommendation — the main "does this actually work" deliverable

This is the flow `model-training/VALIDATION_REPORT.md` §11 tested against real historical matches (55.8% overlap with the real historical XI vs. a 37.2% random baseline — see that section for the full methodology and numbers).

**Frontend (`pages/RecommendationsPage.tsx`):** the coach's own team is pinned to their profile's country (`teamLocked = !!user?.country`, the "Your team" selector is disabled — a deliberate fix, commit `33647ea`, not an oversight); they pick the gender, name the **opposition's specific XI** (required before "Generate Recommendation" is enabled — there's deliberately no auto-predicted-opponent fallback at generate time, only as an optional pre-fill convenience via `api.recommendations` called on the opponent first), then calls `api.recommendations({team, opponent, venue, format, gender, opponent_player_ids})`.

**Backend (`selection.py`):**
- `POST /recommendations` → validates the named opponent XI (exactly 11, no duplicates, none retired via `players.retired_names`), then calls `ai_stub.get_recommendations(match_context)`.
- `ai_stub.get_recommendations` → calls `model_bridge.recommend(team, opponent, venue, fmt, gender, opponent_player_ids)`. On any `ModelBridgeError` (the subprocess failing for some reason), falls back to a hardcoded 6-player fake list (`_fallback_recommendations`) — a safety net so the UI never hard-crashes, tagged distinctly so a caller can tell real output from the fallback.

**Model-training (`criiq_models.cli recommend --team ... --opponent ... --explain --shap`, i.e. `cmd_recommend`):**
1. `roster.team_pool(conn, team, fmt, gender)` — the real, point-in-time-safe candidate pool (eligibility-filtered: excludes retired players always, excludes long-inactive players unless recalled or recently active domestically).
2. `RecommendationScorer(conn, fmt, gender).score_many(pool_ids, opponent, venue_id, opponent_players=...)` — scores every pool player. Internally, `score()` per player: predicts `batting_wpa`/`bowling_wpa` from the persisted regressors (§3.3 of `ALGORITHMS.md`), converts that into `model_part`, and adds `matchup_part` (aggregate + style + bowling-side matchup vs. the *named* opponent XI, not just the opponent's team-wide average — this is the "counter-optimization" the README describes), `phase_fit_part`, `standing_part` (from the separate, hand-specified `importance_score`), `risk_part`, `strike_rate_part`, and (in `score_many`, after individual scoring) a synergy-aware `team_need_part`.
3. `selection.optimize.select_xi(scored)` — the MILP (§1 of `ALGORITHMS.md`) that actually picks the constrained 11 maximizing total score.
4. `selection.optimize.role_highlights(scored)` — best finisher/power-hitter/anchor across the *whole* pool, independent of who made the XI (so "who's our best finisher" is always answerable even if that player didn't make the constrained cut).
5. `recommend/matchup_matrix.head_to_head_matrix(conn, xi_ids, opponent_players, fmt)` — real per-pair dismissal history between the recommended XI and the *named* opponent XI, both directions.
6. `recommend/strength.strength_context(conn, team, opponent, fmt, gender)` — if this side is much stronger (ICC-rank gap), builds an alternate "rotation XI" resting the top performers.
7. With `--explain`/`--shap`: `recommend/explain.explain()` per player (plain-language reasoning, including their best alternative in the same role slot) and `recommend/shap_explain.explain_prediction()` per player if `--shap`.

**Frontend result rendering:** grouped into role pools, each card expandable to show `explain()`'s narrative plus a `ShapSection`/`ShapBar` diverging-bar visualization of the SHAP contributions (`RecommendationsPage.tsx`'s own local components, lazily fetched per-player via `api.explainPlayer` on first expand, cached in `shapById`).

**From here, two further actions are wired directly off this page:**
- **"Simulate this XI"** → navigates to `/simulator` with a `SimulatorPrefill` (both XIs, gender) via router `location.state` — see §6.
- **"Confirm Selection"** → `api.saveSelection(matchId, {xi, extra, excluded})`, then navigates to `/build-xi`.

---

## 5. Analyzing a coach's own hand-picked XI (not the AI's recommendation)

**Frontend:** `components/squad/AnalyzeXiModal.tsx`, opened from `SquadSelectionPanel.tsx`'s "Analyze this XI" button once a coach has manually built their own 11.

**Backend (`simulation.py`):** `POST /analyze-xi` → rejects retired players, calls `model_bridge.analyze_xi(team, opponent, player_ids, venue, fmt, gender)` (`criiq_models.cli analyze-xi`).

**Model-training (`cmd_analyze_xi` → `selection.optimize.analyze_xi`):** scores the coach's *specific* 11 against the identical constraints `select_xi` enforces (same soft-degradation rules — e.g. if the whole pool has zero flagged keepers, the keeper requirement drops to 0 for both, so the comparison is fair), reports which constraints the hand-picked XI violates (if any), then internally calls `select_xi` on the same pool to get the true provably-optimal XI and reports the score gap plus the exact players that differ between the two.

---

## 6. Match Simulation — the other main "does this actually work" deliverable

Also directly tested in `VALIDATION_REPORT.md` §11 (66.7% win-call accuracy on real matches with real XIs, Brier 0.222 vs. a 0.250 naive baseline).

**Frontend (`pages/SimulationPage.tsx`, `SimulateTab`):** two `TeamPicker`s, two `XIPicker`s (each backed by `useTeamRoster` → `api.listPlayers`, auto-filled to the AI's own recommended XI via `useRecommendedXI` → `api.recommendations`, cached per `team|opponent|gender`), a simulation-count input, "Run Simulation" → `api.simulateMatch({team1, team2, team1_player_ids, team2_player_ids, toss_winner, n_simulations, gender})`.

**Backend (`simulation.py`):** `POST /simulate` → validates both XIs are exactly 11 and non-retired, `toss_winner` matches one of the two team names, then `model_bridge.simulate(...)` (`criiq_models.cli simulate --json`, 300s timeout — this is genuinely the slowest call in the system, since it's running real ball-by-ball Monte Carlo reps).

**Model-training (`cmd_simulate`):**
1. `simulate.outcomes.build_outcome_model(conn, fmt, gender, team1_ids, team2_ids)` — the empirical, per-phase, matchup-adjusted ball-outcome distribution (§4.2-4.3 of `ALGORITHMS.md`).
2. `simulate.winprob_reader.WinProbLookup.load(fmt, gender)` — the persisted empirical win-probability grid.
3. `simulate.outcomes.build_player_profiles(conn, fmt, team1_ids, team2_ids, team1_name, team2_name, venue_id)` — batting/bowling profiles for every player on both sides.
4. `simulate.engine.simulate_match(team1, team2, batting_first, outcome_model, batter_profiles, bowler_profiles, winprob, n_reps=N)` — the actual ball-by-ball Monte Carlo loop, `N` times.
5. Post-processing per representative rep: `simulate.keymoments.detect_key_moments()`, `simulate.scorecard.batting_scorecard()`/`bowling_scorecard()`/`bowling_rotation()` for both innings, `simulate.report.aggregate_win_probability()` across all `N` reps (mean + p10/p90 band) if `N > 1`.

**Frontend result rendering:** score lines + winner, `components/match/WinProbChart.tsx` (only if `win_prob_timeline` present — i.e. `n_simulations > 1`), `components/match/Scorecard.tsx`'s `Scorecard` component (the *simulated*-match variant, distinct from the real-match one — see §9), and a Key Moments list.

**A related but separate flow — `SquadStrengthModal.tsx`** (opened from `RecommendationsPage`'s "Analyze Squad" once the opposition XI is complete): fires `api.optimizeBatting(...)` and `api.simulateMatch({..., n_simulations: 20, ...})` **in parallel** on mount, showing a Squad Strength score alongside a real simulated Match Win Rate for the exact same matchup — i.e. it reuses both the batting-order GA and the full simulator together as one combined "how strong is this squad, really" view.

---

## 7. The genetic-algorithm optimizers — bowling rotation & batting order

**Frontend:** `SimulationPage.tsx`'s `OptimizeBowlingTab` / `OptimizeBattingTab`, each with its own two `XIPicker`s and a run button; batting additionally takes an optional numeric `target` (chase framing).

**Backend (`simulation.py`):** `POST /optimize-bowling` / `POST /optimize-batting` → `model_bridge.optimize_bowling`/`optimize_batting` → `criiq_models.cli optimize-bowling`/`optimize-batting --json --explain`. Note the backend deliberately overrides the CLI's own `--pop-size`/`--generations` defaults (40/60, tuned for an offline notebook run) down to `FAST_POP_SIZE=16`/`FAST_GENERATIONS=20` — the module comment in `model_bridge.py` cites a measured ~10+ minutes for the CLI's own defaults on a live matchup vs. ~19s at the reduced settings, since this needs to return within a synchronous HTTP request.

**Model-training:**
- `simulate.ga_bowling.optimize_bowling_rotation(...)` — the GA over legal bowler-to-over rotations (§2 of `ALGORITHMS.md`); defaults to giving the recognized specialist bowlers (`_primary_bowlers`) the full quota unless `--no-primary-bowlers`.
- `simulate.ga_batting.optimize_batting_order(...)` — the GA over role-banded batting-order permutations, optimizing expected score or (with a target) chase win probability.
- With `--explain`: `simulate.lineup_explain.explain_bowling_rotation()` / `explain_batting_order()` — the baseline-comparison + sensitivity-testing explainability layer (§3.11 of `ALGORITHMS.md`).

**Frontend result rendering:** `BowlingRotationReasoning` / `BattingOrderReasoning` (local components in `SimulationPage.tsx`) render the GA's chosen order/rotation alongside the baseline comparison and (batting) the early-collapse/quick-chase contingency picks from `explain_batting_order`'s output.

---

## 8. Squad building & saved selections

**Frontend:** `pages/BuildXiPage.tsx` (grid of `PlayerCard`s with `SelectionControl` — Select/Reserve/Exclude — wired to a shared `selections` map in `AppContext`) and `components/squad/SquadSelectionPanel.tsx` (the slide-in Playing XI / Extras / Excluded view).

**Backend (`selection.py`):**
- `GET /selection/{matchId}` → reads `app_db.selections`; if the saved squad contains any player who has since retired, strips them and re-persists the cleaned squad automatically.
- `PUT /selection/{matchId}` → validates (≤11 in XI, no id duplicated across the three lists, none retired) and upserts into `app_db.selections`.

**Model-training involvement:** none directly — but `AnalyzeXiModal` (§5) and `SquadStrengthModal` (§6) both read the *current* `selections` state to know which 11 to send into `analyze-xi`/`optimize-batting`/`simulate`.

---

## 9. Matches — list, filter, detail, and real-match scorecard

**Frontend (`pages/MatchesPage.tsx`):** a gender toggle (Women/Men — men's and women's sides share team names, so this is always applied), and three filter modes (`all`/`country`/`h2h`, backed by `api.listTeams(gender)` for the dropdowns) feeding into `api.listMatches({gender, country?, team1?, team2?})`. **Deliberately shows only completed matches** — the page's own comment explains upcoming fixtures have no real result/scorecard to show yet, so listing them alongside played matches would be misleading.

**Backend (`matches.py`):**
- `GET /matches` → dynamic SQL `WHERE` combining `gender` + either the `team1`/`team2` head-to-head pair (order-independent) or a single `country` filter, against `criiq_db.matches`, capped at `min(completed_limit, 50)`.
- `GET /teams` → distinct team names from a `UNION ALL` over `team1`/`team2`, optionally gender-filtered.
- `GET /venues` → distinct venue list (`api.listVenues`), wired to `components/common/VenueSelect.tsx` — used on Recommendations, Build XI, and all three Simulator tabs wherever a venue can be picked. Not model-layer-related, but genuinely used across most of the model-facing pages above, so it's worth knowing about even though it has no section of its own.
- `GET /matches/{id}` → per-innings run/wicket/ball totals from `criiq_db.deliveries`, grouped by innings.
- `GET /matches/{id}/scorecard` → the real, per-player batting/bowling figures for an already-played match, built directly from ball-by-ball `deliveries` (`_innings_scorecard`, mirroring the exact same conventions — byes excluded from bowling figures, run-outs excluded from bowler-credited wickets — that `data-collection/criiq_data/stats.py` uses, so the numbers agree with the analytics DB's own player stats).

**Frontend (`pages/MatchDetailPage.tsx`):** fetches `api.getMatch(id)`; if the match is already completed, separately fetches `api.getMatchScorecard(id)` and renders it via `components/match/Scorecard.tsx`'s `RealMatchScorecard`.

**Model-training involvement: none for this whole feature.** Everything above is pure SQL aggregation in the backend against `criiq_db.deliveries`/`matches` — no subprocess call, no trained model. **Confirmed directly by reading the current code:** there is currently no win-probability graph, and no `GET /matches/{id}/winprob` endpoint, for a real past match — `MatchDetailPage.tsx` imports only `RealMatchScorecard`, not `WinProbChart`, and `lib/api.ts` has no function for it. (`components/match/WinProbChart.tsx` exists and works, but its only current caller anywhere in the frontend is the *simulated*-match flow in `SimulationPage.tsx` — see §6.) If a real-match win-probability graph is wanted later, the real historical ball-by-ball data (`deliveries`) and the persisted win-probability grid (`simulate.winprob_reader.WinProbLookup`) both already exist and could be replayed ball-by-ball the same way the simulator's per-ball lookup works today — that would be new work, not a matter of wiring up something already built.

---

## 10. Dashboard

**Frontend (`pages/DashboardOverviewPage.tsx`):** `api.dashboardSummary()`, `api.dashboardAlerts()`, plus `api.listPlayers({limit:1})` just to read `.total`.

**Backend (`matches.py`):**
- `GET /dashboard/summary` → next upcoming fixture, its saved squad size (if any), and a **baseline, non-team-specific** win probability via `ai_stub.get_win_probability({"innings":1,"balls_remaining":120,"wickets":0})` — the frontend explicitly labels this "not team-specific" with a link to the Simulator for a real number, since this call carries no team/opponent identity at all.
- `GET /dashboard/alerts` → a simple rule scan (not model-derived): last-3-innings all ≥50 → "in form"; all ≤10 → "out of form," read from `player_cards.card_json`.
- `GET /ticker` → top scorer (≥30 runs) / best bowler (≥3 wickets) per recent match, from `deliveries`. **Defined, but not currently called from anywhere in the frontend** — dead on the frontend side, though the endpoint itself works.

`ai_stub.get_win_probability` → `model_bridge.winprob(...)` → `criiq_models.cli winprob` → `simulate.winprob_reader.WinProbLookup.predict_one()` for a single game state, with the same hardcoded-fallback safety net pattern as `get_recommendations` (§4).

---

## 11. Key functions reference — one line each, grouped by layer

### Backend (`backend/`)
| Function | File | Purpose |
|---|---|---|
| `require_user` | `auth.py` | JWT + live-session dependency gating almost every route. |
| `_issue_token` | `auth.py` | Signs a JWT and records the session `jti` for later revocation. |
| `list_matches`, `match_detail`, `match_scorecard`, `list_teams`, `list_venues` | `matches.py` | Pure-SQL match history/filter/scorecard/venue lookups, no model layer involved. |
| `_innings_scorecard` | `matches.py` | Builds real per-player batting/bowling rows from raw `deliveries`. |
| `team_last5` | `matches.py` | Real `W`/`L` string for a team+gender, used by both fixtures and completed matches. |
| `list_players`, `build_player_detail` | `players.py` | Player search/list and full-detail assembly across 7+ tables. |
| `retired_names` | `players.py` | Shared retirement check called by both `selection.py` and `simulation.py`'s `_reject_retired`. |
| `retire_player`, `add_player`, `update_player`, `delete_player` | `players.py` | Coach-facing squad CRUD and the retirement write-path (see the new §3b/§8b below) — ownership-enforced against the coach's own team. |
| `run_cli` | `model_bridge.py` | The single choke point every model-training call funnels through (subprocess → JSON). |
| `recommend`, `analyze_xi`, `simulate`, `optimize_bowling`, `optimize_batting`, `explain_player`, `winprob` | `model_bridge.py` | One function per `criiq_models` CLI subcommand this backend exposes. |
| `get_recommendations`, `get_win_probability` | `ai_stub.py` | Wrap the matching `model_bridge` call with a hardcoded fallback on failure. |
| `_build`, `current_team`, `team_members`, `gender_members` | `roster_index.py` | In-memory, match-appearance-derived team/gender index (not `players.nationality`, which is unreliable). |

### Model-training (`model-training/criiq_models/`)
| Function | File | Purpose |
|---|---|---|
| `RecommendationScorer.score` / `.score_many` | `recommend/score.py` | Turns a player into one additive 0–100 score (§3 of `ALGORITHMS.md`). |
| `select_xi` | `selection/optimize.py` | The MILP that picks the constrained 11 (§1 of `ALGORITHMS.md`). |
| `analyze_xi` | `selection/optimize.py` | Scores/checks a coach's own hand-picked XI against the same rules. |
| `role_highlights`, `role_pools` | `selection/optimize.py` | Best-of-archetype and batting/bowling/all-rounder groupings, independent of the final XI. |
| `explain` | `recommend/explain.py` | Plain-language narrative for one player's score. |
| `explain_prediction` | `recommend/shap_explain.py` | Exact SHAP feature-attribution for one WPA prediction (§3.11 of `ALGORITHMS.md`). |
| `train` | `recommend/train.py` | Fits + persists the two WPA regressors and the SHAP background sample. |
| `head_to_head_matrix` | `recommend/matchup_matrix.py` | Real per-pair dismissal history between two named XIs. |
| `strength_context` | `recommend/strength.py` | Detects a lopsided matchup and builds a rotation XI. |
| `build_outcome_model` | `simulate/outcomes.py` | The empirical, matchup-adjusted per-ball outcome distribution the simulator samples from. |
| `build_player_profiles` | `simulate/outcomes.py` | Batting/bowling profiles for every player in a simulated match. |
| `simulate_match` / `simulate_innings` | `simulate/engine.py` | The ball-by-ball Monte Carlo loop itself. |
| `optimize_bowling_rotation` | `simulate/ga_bowling.py` | GA search over legal bowler-to-over rotations. |
| `optimize_batting_order` | `simulate/ga_batting.py` | GA search over role-banded batting-order permutations. |
| `explain_batting_order` / `explain_bowling_rotation` | `simulate/lineup_explain.py` | Baseline-comparison + sensitivity explainability for the two GAs (§3.11 of `ALGORITHMS.md`). |
| `WinProbLookup.predict_one` | `simulate/winprob_reader.py` | Single-ball win-probability lookup against the persisted empirical grid. |
| `detect_key_moments` | `simulate/keymoments.py` | Milestones/boundaries/hat-tricks/biggest swings from a ball log. |
| `batting_scorecard` / `bowling_scorecard` | `simulate/scorecard.py` | Post-match scorecards from a *simulated* ball log (distinct from the backend's real-match scorecard builder). |
| `team_pool` | `roster.py` | The real, eligibility-filtered, point-in-time-safe candidate pool for a team. |

### Frontend (`frontend/src/`)
| Function/Component | File | Purpose |
|---|---|---|
| `apiFetch` | `lib/api.ts` | Unwraps the backend's `{data, error}` envelope for every call. |
| `mapApiMatch`, `mapApiPlayerListItem`, `mapApiPlayerDetail`, `applyVsOpponent` | `lib/mappers.ts` | Backend JSON → the frontend's own `Match`/`Player` shapes. |
| `useTeamRoster`, `useRecommendedXI` | `pages/SimulationPage.tsx` | Fetch/cache a team's roster and its AI-recommended XI for the simulator's pickers. |
| `WinProbChart` | `components/match/WinProbChart.tsx` | Renders both a simulated Monte-Carlo band and (if ever wired up) a single real-match line — currently only used by the simulator. |
| `Scorecard` / `RealMatchScorecard` | `components/match/Scorecard.tsx` | Simulated-match vs. real-match scorecard rendering, same underlying table components. |
| `buildTargetSummary` | `components/squad/SquadStrengthModal.tsx` | Aggregates head-to-head matchups into a "who to target" summary. |

---

## 12. Known gaps, dead code, and honest status

Found by directly reading the current code (not inferred), worth knowing about rather than discovering by surprise later:

- **Two admin routes have no auth guard**: `GET /auth/admin/pending-coaches` and `POST /auth/admin/pending-coaches/{id}` (`auth.py`) — no `Depends(require_user)`, no role check. Every other route in the system is gated; these two currently aren't. These aren't unused either — the admin portal (§2b) is a real, working feature built entirely on top of them.
- **Manual-player CRUD has no ownership check**: `PUT /players/{id}` and `DELETE /players/{id}` (`players.py`, see §3b) require login (router-level `Depends(require_user)`) but never check the manual player's `country` against the calling coach's own team, unlike `retire_player` right next to them, which does. Any logged-in coach can edit or delete another coach's manually-added players.
- **No real-match win-probability graph exists yet** — the Matches feature (§9) has a real scorecard but no win-probability chart for a *played* match, only for a *simulated* one. The underlying data (ball-by-ball `deliveries`, the persisted `WinProbLookup` grid) already exists; nothing currently replays it for a real match.
- **Confirmed-dead functions** (defined, zero call sites anywhere in the frontend): `api.comparePlayers`, `api.ticker`, `api.winProb`, `components/common/FactorBar.tsx`, `components/common/CountdownTimer.tsx`. None of these are bugs — they're either superseded by another approach (`PlayerCompareModal` does its own fetches instead of `comparePlayers`) or simply not wired into any current page.
- **`ai_model.py` no longer exists** as a source file (only stale `.pyc` bytecode remains) — `ai_stub.py` is its replacement, keeping the old name in some comments despite no longer being a "stub" in the literal sense (it prefers the real model and only falls back on failure).
- **Does the core AI actually work?** Answered with real numbers, not just "yes/no," in `model-training/VALIDATION_REPORT.md` §11: the Playing XI recommendation overlaps a real historical starting XI by 55.8% (vs. 37.2% random baseline); the match simulator, given real XIs and the real toss, calls the winner correctly 66.7% of the time on real held-out 2026 matches the models never trained on. Both are genuinely better than chance, neither reproduces reality exactly — see that report for the full methodology, sample sizes, and honest caveats (the male-side sample for full match simulation was small).

---

## 13. FAQ — the questions people actually ask about this system

### Data & domain

**Q: Why isn't domestic (league) data used for men, only women?**
It's a scope decision recorded directly in `data-collection/criiq_data/config.py`: every men's domestic league (IPL, BBL, PSL, CPL) is defined as a `CricsheetSource` entry with `enabled=False`, right next to the women's leagues (WBBL, WPL, The Hundred Women, etc.) which are `enabled=True`. The code doesn't state an explicit reason beyond that — it reads as "women's domestic coverage was built out first," not a technical limitation. Turning men's domestic sources on is a one-line flip (`enabled=True`) plus a full `data-collection` pipeline re-run (download → ingest → rebuild every derived table) — no model-training or backend code needs to change, because `domestic_form_*` is already a shared, gender-agnostic feature in `MODEL_FEATURES` (see next answer).

**Q: If domestic data is off for men, how is a men's player's score actually calculated?**
The exact same formula as a women's player (`recommend/score.py`'s additive `model_part + matchup_part + phase_fit_part + standing_part + risk_part + strike_rate_part`) — `domestic_form_matches`/`domestic_form_batting_wpa`/`domestic_form_bowling_wpa` are real columns in the feature table for *every* player regardless of gender, they just come back as `0`/`NaN` for every men's player today because no men's `team_type='club'` rows exist in `criiq.db` yet. The shrinkage formula (`shrink()`, §5.1 of `ALGORITHMS.md`) handles a missing observed value gracefully by falling all the way back to the prior (the player's own international career WPA) — so a men's player's rating today is driven entirely by international-only signal (career/form WPA, opponent/venue history, phase fit, importance score), with the domestic-form component contributing exactly zero information, not a penalty and not an error.

**Q: How does a brand-new player get into the system — can it recommend someone who's never played before?**
No, not directly, and this is a real, honest limitation worth knowing. `roster.team_pool` (the function every recommendation/selection call uses to get a team's candidate pool) derives "who currently plays for this team" from `player_current_teams`, which only reads `match_players` joined to `matches` **filtered to `team_type='international'`** — i.e. a player needs at least one recorded *international* appearance before they exist in any team's pool at all. A domestic-only prospect who's never been capped internationally is invisible to `recommend`/`select_xi`, no matter how good their domestic numbers are. Once a human selector gives them their actual international debut (an event this system has no part in), they enter the pool immediately — but with `career_matches = 0`, so the model treats them as a cold start (next answer).

**Q: What happens to a player's rating right after their real debut, and how does it change as they play more matches?**
`score.py`'s cold-start gate is `model_applied = career_matches >= SETTINGS.min_matches_for_model` (10). Below that threshold, the trained regressor is skipped entirely — the fallback is a shrinkage-based estimate (`career_batting_wpa` shrunk toward the league-wide prior) — and even that fallback is scaled down by `confidence = min(1.0, career_matches / min_matches_for_model)`. A true debutant (`career_matches = 0`) therefore gets `model_part = 0` outright — their composite score comes almost entirely from `matchup_part`/`phase_fit_part`/`standing_part`/`risk_part`, all of which are also thin-to-empty for someone with no track record, so a genuine debutant's score starts low and rises smoothly, match by match, until they cross 10 caps and the real trained model takes over at full weight. This isn't a special case coded in for debutants specifically — it's the same continuous formula applied to a small number.

**Q: Why are men's and women's data never blended, even when a team shares a name (e.g. "India")?**
Because they're genuinely different real populations (different scoring rates, different player pools, different competitive levels) sharing an accidental naming collision — blending them would corrupt both. Every derived table and every model artifact is scoped by `(format, gender)` as a first-class pair, never inferred. This was in fact a real, previously-live bug the codebase's own history documents: model artifacts used to be written to one shared flat filename regardless of gender, so training a men's model would silently overwrite a women's model with no error. Fixed by routing every persist/load path through a `(gender, fmt)`-scoped artifacts directory (`recommend/train.py`'s `_artifacts_dir`).

**Q: Why is "female" the default gender everywhere, rather than "male"?**
Documented as a deliberate framing choice, not an oversight: women's and men's T20I are supported as equally first-class scopes, and `--gender` is a real flag/setting everywhere, never hardcoded — `gender=female` is only the *default* when the flag is omitted, chosen because the tool's earliest and most-exercised use case was women's T20I team selection.

**Q: What happens to a retired player?**
`player_registry.retirement_status` (`RETIRED_ALL`/`RETIRED_FORMAT`) excludes them from `roster.team_pool` unconditionally — there's no override for a retired player, unlike the separate `INACTIVE` status (a player simply absent for a while), which *can* stay eligible if genuinely recalled or still domestically active. On the backend side, `players.retired_names` is checked defensively at three separate points (saving a squad selection, generating recommendations with a named opposition XI, and every simulation/optimizer/analyze-xi call) so a retired player can never sneak into an XI through any entry point, even a stale saved selection from before they retired.

**Q: `players.nationality` sounds like the obvious way to know a player's team — why doesn't the system just use it?**
Because it's confirmed unreliable — `roster_index.py`'s own comment cites a real found case ("ER Oza") where trusting the stored nationality field gave a wrong answer. Every "which team does this player currently represent" question in this system instead derives from real match-appearance data (`match_players`, who actually turned up and played) — the most recent international appearance's team, not a static profile field that can be missing, stale, or simply wrong.

**Q: Is there a live, real-time win-probability during an actual in-progress match?**
No — the win-probability model (`WinProbLookup`) and the full ball-by-ball simulator both exist and work, but nothing in this system currently ingests a match *as it's happening*. `simulate` runs a hypothetical match end-to-end from a starting XI; the Matches feature shows real scorecards only for matches Cricsheet has already fully recorded and this project has already ingested. Wiring up genuinely live in-progress scoring would be new work (a live data feed, not something already built and just unconnected).

### System architecture

**Q: Why does the backend call model-training via a subprocess/CLI instead of importing `criiq_models` directly as a Python library?**
Stated directly in `model_bridge.py`'s own module docstring: to keep the ML dependency stack (`scikit-learn`, `shap`, `scipy`, `pandas`, ...) entirely out of the backend's own virtual environment, which only needs FastAPI/JWT/bcrypt. It's also a real process-isolation boundary — a crash or hang inside a Monte Carlo simulation or a GA run can't take down the API server, it just makes that one HTTP request return an error (`ModelBridgeError` → HTTP 422).

**Q: Given that tradeoff, why not run model-training as its own small persistent web service instead of spawning a fresh Python process on every call?**
The codebase doesn't state this explicitly, but the practical tradeoff is visible in the code: a persistent service would remove the per-call Python-startup/import cost (spinning up `scikit-learn` etc. fresh every time), at the cost of a second long-running process to deploy, monitor, and keep healthy, plus a second protocol to define beyond "read this CLI's stdout as JSON." For a tool used by a small number of coaches making occasional requests (not a high-throughput API), the subprocess approach is the simpler thing that works, and `model_bridge.py`'s deliberately reduced GA defaults for backend calls (`FAST_POP_SIZE=16`/`FAST_GENERATIONS=20` vs. the CLI's own 40/60) show the team already actively managing the resulting latency rather than treating it as a non-issue.

**Q: Why SQLite instead of a "real" client-server database like PostgreSQL?**
`backend/database.py`'s own comment gives the reason directly: everything the backend does against `criiq.db` is a handful of plain `SELECT`/`INSERT` statements — no complex joins across a live-writing multi-user system, no need for row-level locking or a connection pool serving many concurrent writers. Adopting an ORM/client-server database "would force us to describe all 25+ pipeline tables as Python classes for zero benefit" — SQLite is in the standard library, needs no separate server process, and the one place concurrency actually matters (many read requests while `data-collection`'s pipeline periodically rebuilds the file) is handled by opening the connection in explicit read-only mode rather than by switching databases.

**Q: Why does model-training re-implement some of data-collection's logic (e.g. resolving a player's identity, or the win-probability lookup) instead of importing it directly?**
A deliberate architectural boundary, stated in multiple places (`features/historical.py`'s docstring, `roster.py`'s `_player_id_map`, `simulate/winprob_reader.py`): `model-training` never imports `data-collection`'s own Python code, only reads the SQLite file and persisted artifacts it produces. This keeps the two packages independently deployable/versionable (each has its own `.venv`) and keeps `model-training` from silently breaking if `data-collection`'s internals change shape, at the cost of maintaining two small, independently-tested mirrors of the same logic (identity resolution, win-probability binning) that need to be kept in sync by hand if the underlying convention ever changes.

**Q: Why does the backend read `criiq.db` directly for some things (matches, players, teams) but go through model-training's subprocess for others (recommendations, simulation)?**
Because those are genuinely different kinds of work. "List the last 10 completed matches" or "what's this player's career strike rate" are plain lookups/aggregations SQL already does well — going through a Python subprocess just to run a SQL query would be pure overhead. Anything that needs a *trained model* or the *simulator* (a WPA prediction, a Monte Carlo match, a genetic-algorithm search) has no SQL equivalent — that logic only exists in `model-training`. The dividing line is exactly "does this need the ML/simulation layer," not an arbitrary split.

**Q: Why is there both a plain-language `explain()` narrative and a separate SHAP breakdown (`--shap`) — isn't that redundant?**
No — they answer different questions at different levels of rigor, by design (§3.11 of `ALGORITHMS.md` covers this in depth). `explain()` is a human-readable *summary* of everything known about a player (form, matchup history, status) — useful on its own, but not a decomposition of the model's actual number. SHAP is a mathematically exact, additive attribution of *one specific prediction* (`base_value + Σcontributions = the actual predicted value`) — useful when someone specifically wants to know "why did the model output this exact number," which the narrative doesn't claim to answer. `--shap` is opt-in (adds real compute cost — a background-sample permutation pass for one of the two sub-models) precisely because most callers only need the narrative.

**Q: Why does `/matches` only show completed matches now, when the backend can also return upcoming fixtures?**
A frontend product decision, not a backend limitation — `GET /matches` still returns both `upcoming` and `completed` in its response. `MatchesPage.tsx`'s own comment explains the reasoning: an upcoming fixture is a placeholder row with no real result, scorecard, or win-probability to show yet, so listing it in the same feed as matches that actually happened was judged confusing rather than useful.

**Q: Why is there no win-probability graph for a real, already-played match, only for simulated ones?**
Purely because it hasn't been built yet, not because it's impossible with the current data. The two ingredients already exist: real ball-by-ball history (`deliveries`) and the persisted win-probability model (`simulate/winprob_reader.WinProbLookup`, already used per-ball inside the simulator). A real match's win-probability graph would need something that replays a real match's actual deliveries through that same per-ball lookup — genuinely new code, but a small, well-scoped addition rather than new infrastructure.

**Q: What would it actually take to turn on men's domestic-league data?**
Flip `enabled=True` on the four `CricsheetSource` entries in `data-collection/criiq_data/config.py` (IPL, BBL, PSL, CPL), then re-run the full `data-collection` pipeline (`refresh.py`'s stages: download → ingest → every derived-table builder) so the new `team_type='club'` matches flow through `wpa.py`'s `build_domestic_form_for_format` into `player_domestic_form`. No `model-training` code needs to change — `domestic_form_*` is already gender-agnostic in `MODEL_FEATURES`; the very next `train` run would simply start seeing real, non-empty values for men where it previously saw none.

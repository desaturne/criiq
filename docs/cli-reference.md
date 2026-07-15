# Criiq — CLI Command Reference

Every command in both packages: what it does, what it reads (accesses) and what it writes or extracts (produces), and how to run it. Complements `criiq-technical-documentation.md` (which covers *why* the system is built this way) with the concrete *how*.

Both CLIs share conventions:
- All output is indented JSON to stdout unless noted otherwise.
- `--format` defaults to `T20` everywhere.
- model-training's `--gender` defaults to `female`; every command accepts `--gender male` as a first-class alternative, not an afterthought — training, backtesting, recommending, and explaining are all fully symmetric between genders.
- data-collection commands that touch player data are gender-*agnostic* by default (they process every gender present in the database in one pass) except where a command inherently needs one gender picked (`vs-team`, `winprob --state`).
- Every command opens its own DB connection and closes it on exit; none hold a long-lived connection.

---

## 1. `data-collection` (`python run.py <cmd>` or `python -m criiq_data.cli <cmd>`)

Reads/writes `data-collection/data/criiq.db` (SQLite, read-write — this package is the sole owner) plus `data-collection/data/features/*.parquet` and `data-collection/data/models/*` (win-probability grids). Also reads/writes the human-editable CSV workflows under `data-collection/data/{styles,rankings,overrides}/`.

### Pipeline orchestration

#### `refresh [--force] [--enrich] [--seed-styles] [--no-rss]`
**What it does:** runs the full 12-stage pipeline end-to-end, idempotently (only new work happens on a re-run).
**Accesses:** everything below, in order — register → download → ingest → identity → (enrich) → (styles) → (rss) → registry/career/cards → advanced → opponents/impact/venues/matchups/phases → ml → winprob.
**Extracts/produces:** the fully rebuilt `criiq.db` plus all Parquet features; a summary dict of each stage's return value; `meta.last_successful_refresh` is updated on success.
**Note:** `wpa` and `role-finalize` are **not** part of `refresh` — run them separately (see below); a scheduler running only `refresh` will leave WPA/role data stale.
```bash
python run.py refresh --enrich --seed-styles
```

#### `init`
**What it does:** creates the SQLite schema (all `CREATE TABLE IF NOT EXISTS` statements) if it doesn't exist yet.
**Accesses:** nothing (fresh DB or existing schema, no-op if already present).
**Extracts/produces:** an empty/ready `criiq.db`.
```bash
python run.py init
```

#### `download [--force]`
**What it does:** downloads the Cricsheet people register and every enabled `CricsheetSource` ZIP (women's + men's T20I, women's domestic leagues), skipping unchanged files via an HTTP `HEAD` fingerprint check unless `--force`.
**Accesses:** `cricsheet.org/register/people.csv`, `cricsheet.org/downloads/*.zip`; `meta` table for stored fingerprints.
**Extracts/produces:** raw ZIPs under `data/raw/`; updated fingerprints in `meta`.
```bash
python run.py download --force
```

#### `ingest`
**What it does:** parses every downloaded match archive (info + deliveries CSVs), validates each row, and writes raw tables. Only `T20`/`IT20` matches are ingested; only `team_type='international'` is kept (domestic leagues are the one exception, tagged `team_type='club'`). Matches dated after `SETTINGS.data_cutoff_date` are routed to `matches_holdout`/`deliveries_holdout`/`match_players_holdout` instead of the production tables.
**Accesses:** raw ZIPs under `data/raw/`.
**Extracts/produces:** `matches`, `deliveries`, `match_players`, `identifier_map`, `people` rows; rejected rows go to a timestamped CSV under `data/quarantine/` with a `_reject_reason` column instead of being silently dropped.
```bash
python run.py ingest
```

#### `identity`
**What it does:** resolves every `(cricsheet_identifier, gender)` pair to a stable `player_id` (UUID5), splitting the ~32 identifiers Cricsheet itself reuses across two genuinely different real people of different genders; also normalises raw venue strings to a canonical `venue_id`.
**Accesses:** `identifier_map`, `people`, `deliveries` (venue strings), `matches`.
**Extracts/produces:** `players` (upserted, `needs_review` flagged when no `key_cricinfo` exists), `venues`.
```bash
python run.py identity
```

#### `enrich [--limit N] [--refetch]`
**What it does:** best-effort fills date of birth, nationality, role, and batting hand from the ESPNcricinfo core JSON API, keyed by `key_cricinfo`. Opt-in — the pipeline is fully functional without it.
**Accesses:** `players.key_cricinfo`; `core.espnuk.org/v2/sports/cricket/athletes/{id}` (rate-limited, retried, cached).
**Extracts/produces:** updates to `players` (DOB, nationality, role, batting_hand); a JSON response cache under `data/cache/cricinfo/`.
```bash
python run.py enrich --limit 500
```

### Registry, styles, rankings, overrides — the pluggable/human-in-the-loop CSV workflows

#### `registry`
**What it does:** classifies every player as `ACTIVE` / `INCONSISTENT` / `INACTIVE` / `UNKNOWN` / `RETIRED_FORMAT` / `RETIRED_ALL` from ICC-rank presence, real match-appearance recency (international-only for the status label itself), and selection rate within the team's recent matches; also computes career phase and age advisories, and applies any loaded `status_overrides`.
**Accesses:** `matches`, `match_players`, `identifier_map`, `icc_rankings`, `status_overrides`, `player_domestic_form` (for the separate `recent_domestic_activity` eligibility flag, kept distinct from the international-only status label).
**Extracts/produces:** `player_registry` (one row per player per format).
```bash
python run.py registry
```

#### `styles [--scaffold [--all]] [--seed] [--wiki] [--load] [--limit N]`
**What it does:** four sub-workflows for bowling style / batting hand coverage, chosen by flag (mutually exclusive; no flag = report current coverage):
- `--scaffold`: writes `data/styles/player_styles.csv` — a template of players missing style data (`--all` includes already-filled rows too) for manual research.
- `--seed`: seeds role/nationality from Wikidata via SPARQL.
- `--wiki`: fills bowling style + batting hand from Wikipedia infoboxes (regex-parsed wikitext), unrestricted by team.
- `--load`: merges the manually-filled `data/styles/player_styles.csv` back in (existing values always win — never clobbers a better-sourced value).
**Accesses:** `players`; Wikidata SPARQL endpoint / Wikipedia API (for `--seed`/`--wiki`); `data/styles/player_styles.csv` (for `--load`).
**Extracts/produces:** `player_styles`, and `players.bowling_style`/`players.batting_hand` backfilled (never overwritten if already set).
```bash
python run.py styles --wiki --limit 1000
python run.py styles --scaffold
```

#### `rankings [--scaffold] [--fetch]`
**What it does:** loads ICC top-10-per-discipline rankings, then rebuilds `player_registry` and `player_cards` so the new ranks are reflected everywhere immediately. `--scaffold` writes a template CSV; `--fetch` pulls the public ICC endpoint (gated on `CRIIQ_ICC_RANKINGS_CLIENT_ID` — refuses to guess/bypass credentials); no flag loads the local `data/rankings/icc_rankings.csv`.
**Accesses:** `data/rankings/icc_rankings.csv`, or the public ICC rankings endpoint (`--fetch`).
**Extracts/produces:** `icc_rankings`; rebuilds `player_registry` and `player_cards`.
```bash
python run.py rankings --fetch
```

#### `status-override [--scaffold]`
**What it does:** loads manually-researched, human-confirmed retirement/availability corrections (`RETIRED_FORMAT`/`RETIRED_ALL`/`UNAVAILABLE`/`ACTIVE`/`UNKNOWN`) — the mechanism for facts pure appearance-recency can't infer, e.g. an explicitly announced retirement. `--scaffold` writes a template.
**Accesses:** `data/overrides/player_status.csv`; matches by `key_cricinfo` first, falls back to fuzzy name match (RapidFuzz, threshold 90) only when no `key_cricinfo` is given.
**Extracts/produces:** `status_overrides` (upserted). Run `registry` afterward to actually apply the override to `player_registry.retirement_status`.
```bash
python run.py status-override
python run.py registry   # apply it
```

#### `rss`
**What it does:** scans ICC/ESPNcricinfo RSS feeds for retirement keywords ("retires", "steps down", "hangs up", ...).
**Accesses:** the configured `RSS_FEEDS` URLs.
**Extracts/produces:** `retirement_alerts` rows with status `PENDING` — never auto-applies a status change from a headline.
```bash
python run.py rss
```

#### `alerts [--confirm N | --dismiss N]`
**What it does:** human-in-the-loop review of pending retirement alerts. No flag lists them; `--confirm`/`--dismiss` mark one by row id.
**Accesses/extracts:** `retirement_alerts`.
```bash
python run.py alerts
python run.py alerts --confirm 14
```

### Derived analytics builders (each independently re-runnable)

#### `career`
**What it does:** builds career batting/bowling aggregates per player per format from the shared per-match innings frame.
**Accesses:** `deliveries`, `matches`, `match_players`, `identifier_map`, `players` (via `stats.build_innings`).
**Extracts/produces:** `player_career`.

#### `cards`
**What it does:** builds a nested dashboard JSON blob per player (identity, career, recent form index, impact, status, ranking, recent head-to-head vs their most recent opponent).
**Accesses:** `player_career`, `player_registry`, `player_impact`, `icc_rankings`, plus the same innings frame; `h2h.player_vs_team` for the H2H field.
**Extracts/produces:** `player_cards`.

#### `advanced`
**What it does:** builds the detailed JSON profile — phase splits, control/aggression proxies (dot/boundary/rotation %), acceleration (first 10 balls vs. after), batting archetype (`anchor` / `power hitter` / `finisher` / `balanced`), and vs-pace/vs-spin and vs-batting-hand splits (only where Wikipedia style coverage exists).
**Accesses:** the innings frame, `player_styles`/`players.bowling_style`/`players.batting_hand`.
**Extracts/produces:** `player_advanced` (`archetype` column + full `profile_json`).

#### `opponents`
**What it does:** builds each player's full record against every opponent team they've faced (matches, win %, batting, bowling, player-of-match rate).
**Accesses:** the innings frame.
**Extracts/produces:** `player_vs_opponent`.

#### `impact`
**What it does:** builds the transparent, weighted `importance_score` (contribution share + winning contribution + player-of-match standout + a bowling bonus split equally between top-order wicket-taking rate and economical-spell rate + a batting-innings-worth-having bonus), plus contextual splits (pressure/wins-vs-losses, setting/chasing average and strike rate).
**Accesses:** the innings frame, `deliveries` (for wicket-credit and dismissal-position detail), `matches.player_of_match`.
**Extracts/produces:** `player_impact` (`importance_score` + a JSON `importance_components` breakdown of every sub-part).

#### `venues`
**What it does:** builds per-ground batting/bowling records per player, split by batting-first vs. chasing.
**Accesses:** the innings frame, `venues`, `matches.venue_id`.
**Extracts/produces:** `player_by_venue`.

#### `matchups`
**What it does:** builds batter-vs-bowler dismissal-matchup samples (balls/runs/dismissals, minimum 6 balls faced so "safely contained" pairs are visible too, not just dismissals) at both the format-wide and per-venue level.
**Accesses:** `deliveries`, `identifier_map`, `matches`.
**Extracts/produces:** `dismissal_matchup`, `venue_dismissal_matchup`.

#### `phases`
**What it does:** builds powerplay/middle/death splits for batting and bowling, with each player's rank and percentile *within their own team* per phase (minimum 30 balls).
**Accesses:** the innings frame, `deliveries` (phase bucketing by over).
**Extracts/produces:** `player_phase`.

#### `role-finalize [--format T20] [--load-external CSV]`
**What it does:** two sub-modes. No `--load-external`: a local pass refining `derived_role` using median batting position (a specialist bowler with tail-end batting balls is reclassified from "all-rounder" to "bowler" if their median position is ≥8). With `--load-external CSV`: merges an externally-researched roles/wicket-keeper CSV (`key_cricinfo, is_keeper, primary_role_override, bowling_style, confidence, source_url`) — the **only** source of wicket-keeper status, since Cricsheet's ball-by-ball export has no fielder-of-dismissal data at all. Currently covers 18 women's T20I nations; zero men's nations (a data-research gap, not a code one).
**Accesses:** the innings frame (batting position), or the external CSV matched strictly by `key_cricinfo` (never by raw name, to avoid minting duplicate identities).
**Extracts/produces:** `player_role_final` (`primary_role`, `is_keeper`, `batting_position_median`, `keeper_confidence`, `keeper_source`); style rows also backfill `player_styles`/`players.bowling_style`.
```bash
python run.py role-finalize
python run.py role-finalize --load-external data/overrides/external_roles.csv
```

#### `ml`
**What it does:** builds the three ML-specific artifacts: `match_features` (pre-match-only rolling form + head-to-head + toss, leakage-safe by construction), the player-agnostic ball-state Parquet (training data for the win-probability model), and `player_match_impact` (per-match dot%/boundary%/bowling-strike-rate detail).
**Accesses:** `deliveries`, `matches`, `match_players`.
**Extracts/produces:** `match_features`, `data/features/ball_state_T20.parquet`, `player_match_impact`.

#### `wpa`
**What it does:** replays every ball, scores it with the already-fitted (per-gender) win-probability model, and credits the swing to the striker (+) and bowler (−) — Win-Probability-Added. **Out-of-band, not part of `refresh`.**
**Accesses:** `deliveries`, `matches`, `identifier_map`; the persisted `winprob_{format}_{gender}_*` model files (must be built first via `winprob`).
**Extracts/produces:** `player_match_wpa` (per match), `player_phase_wpa` (career per-phase rates), `player_domestic_form` (domestic-only recent WPA, separated by `team_type`).
```bash
python run.py winprob   # build the model first
python run.py wpa
```

#### `winprob [--format T20] [--gender female] [--match ID] [--state "k=v,..."]`
**What it does:** three modes. No flag: fits and persists one `EmpiricalWinProb` model **per gender** (never blended — men's and women's T20 have genuinely different scoring/required-run-rate distributions) and scores every ball into one combined Parquet. `--match ID`: prints a per-over win-probability timeline for a real match. `--state "innings=2,balls_remaining=30,wickets=4,runs_required=40"`: ad-hoc win probability for a hand-written game state, using `--gender`'s specific fitted model (this is the one mode where `--gender` actually selects which persisted model file to query — building/`--match` always process/show both genders together).
**Accesses:** `data/features/ball_state_T20.parquet` (build mode); `data/features/win_prob_T20.parquet` (`--match` mode); `data/models/winprob_T20_{gender}_*.parquet` + `_meta.json` (`--state` mode).
**Extracts/produces:** (build mode) `data/models/winprob_T20_{gender}_*.parquet`/`_meta.json` per gender, `data/features/win_prob_T20.parquet` (combined).
```bash
python run.py winprob
python run.py winprob --match 1234567
python run.py winprob --gender male --state "innings=2,balls_remaining=30,wickets=4,runs_required=40"
```

### Inspection / reporting commands (read-only views, no writes)

#### `status`
**What it does:** a one-shot health/coverage snapshot — table row counts, registry status breakdown, age-advisory count, style coverage, `key_cricinfo` coverage, players needing review, data freshness, last successful refresh timestamp.
**Accesses:** most tables (see the CLI source for the exact list); `refresh.freshness`.
```bash
python run.py status
```

#### `card --name NAME [--format T20] [--first]`
**What it does:** prints one player's full dashboard card (fuzzy name lookup; `--first` picks the first match instead of erroring on ambiguity).
**Accesses:** `player_cards` (via `players` name lookup).
```bash
python run.py card --name "Mandhana"
```

#### `profile --name NAME [--format T20] [--first]`
**What it does:** prints one player's detailed advanced profile (phase splits, archetype, vs-pace/spin splits, plain-language strengths).
**Accesses:** `player_advanced` (via `players` name lookup).
```bash
python run.py profile --name "Ecclestone"
```

#### `sheet --name NAME [--format T20] [--opponents N]`
**What it does:** the curated individual selector sheet — the single richest human-facing report, combining career, form, standing, status, and per-opponent breakdowns.
**Accesses:** `sheet.py`'s aggregation of `player_career`, `player_impact`, `player_registry`, `player_vs_opponent`, and more.
```bash
python run.py sheet --name "H Kaur" --opponents 5
```

#### `h2h --batter NAME --bowler NAME [--format T20]`
**What it does:** head-to-head ball-by-ball record between one named batter and one named bowler (gender-resolved per player since the fix documented in the technical doc's gender-isolation section).
**Accesses:** `deliveries`, `matches`, `identifier_map` (via `h2h.names_for_player`/`batter_vs_bowler`).
```bash
python run.py h2h --batter "S Mandhana" --bowler "MA Starc"
```

#### `vs-team --name NAME --team OPPONENT [--format T20] [--gender female]`
**What it does:** a player's full matchup breakdown against one specific opponent team — every bowler faced (if they bat) and every batter bowled to (if they bowl), each with a highlighted bogey-bowler / best-matchup / most-expensive-batter pick.
**Accesses:** `dismissal_matchup`, `venue_dismissal_matchup` (via `matchups.batter_vs_team_bowlers`/`bowler_vs_team_batters`).
```bash
python run.py vs-team --name "E Perry" --team India
```

---

## 2. `model-training` (`python -m criiq_models.cli <cmd>`)

Reads `data-collection/data/criiq.db` **read-only** (opened via a `mode=ro` SQLite URI — the engine itself enforces this package can never write to it). Writes only its own trained model artifacts under `model-training/artifacts/player_recommendation/{gender}_{format}/`.

#### `features [--format T20] [--gender female]`
**What it does:** builds the leakage-safe training feature table (point-in-time reconstruction — every feature strictly pre-dates the match it's attached to) and reports its row count and date range. Doesn't persist anything; a diagnostic/dry-run command.
**Accesses:** `player_match_impact`, `player_match_wpa`, `player_domestic_form`, `player_role_final`/`player_registry` (role), `matches` (for `--gender` scoping).
```bash
python -m criiq_models.cli features --gender male
```

#### `train [--format T20] [--gender female]`
**What it does:** fits and persists the two WPA regressors (`batting_wpa`: RandomForest; `bowling_wpa`: a HistGradientBoosting + RandomForest voting ensemble) for one `(format, gender)` scope.
**Accesses:** the same tables as `features`.
**Extracts/produces:** `artifacts/player_recommendation/{gender}_{format}/model_batting_wpa.joblib`, `model_bowling_wpa.joblib`, `training_metadata.json` (feature list, row counts, date range, holdout MAE/R²). Training one gender never touches the other's files — each scope is fully independent.
```bash
python -m criiq_models.cli train --gender female
python -m criiq_models.cli train --gender male
```

#### `backtest [--format T20] [--gender female]`
**What it does:** temporal-holdout regression report for the currently-persisted model of this scope — MAE, baseline MAE, R², Pearson correlation, top-quartile hit rate, all against **raw, unclipped** holdout labels.
**Accesses:** the trained model artifacts for this `(format, gender)`; rebuilds the same feature table as `train`.
```bash
python -m criiq_models.cli backtest --gender male
```

#### `rank-backtest [--format T20] [--gender female]`
**What it does:** fits a throwaway LightGBM learning-to-rank model on the same temporal split and compares its top-11-hit-rate/Spearman-correlation against the persisted regression model's — answers "would a dedicated ranker beat the shipped regressors" empirically, without changing what's actually deployed.
**Accesses:** same as `backtest`, plus the trained regression models for the comparison baseline.
```bash
python -m criiq_models.cli rank-backtest
```

#### `teams [--format T20] [--gender female]`
**What it does:** lists every known team name for this `(format, gender)` scope (distinct `team1`/`team2` values in `matches`).
**Accesses:** `matches`.
```bash
python -m criiq_models.cli teams --gender male
```

#### `recommend --team A --opponent B [--venue V] [--format T20] [--gender female] [--explain] [--pretty]`
**What it does:** scores every eligible player in team A's pool for a matchup against B (optionally at venue V), splits them into batting/all-rounder/bowling role pools, and selects the constrained-optimal playing XI (MILP: exactly 11, ≥5 batting-capable, ≥5 bowling-capable, ≥1 keeper, ≥2 openers — each minimum gracefully degrades to what the pool can actually support). `--explain` adds per-player plain-language reasoning; `--pretty` renders an actual team sheet instead of JSON (implies `--explain`). `--venue` takes a ground **name** (fuzzy-matched, "did you mean" on ambiguity), not a raw `venue_id`.
**Accesses:** `roster.team_pool` (eligibility: `player_registry`, `matches` for current-team resolution), the trained model artifacts, everything `RecommendationScorer`/`explain` read (career/impact/phase/venue/matchup tables, registry status).
**Extracts/produces:** nothing persisted — prints the scored pool, role-grouped pools, the selected XI, and a `role_options` block (the best available finisher / power hitter / anchor across the whole pool, ranked by finishing/hitting quality rather than the composite score, so a strong finisher shows up even when outside the auto-XI), each pick with a plain-language profile (archetype, strike rate, boundary%, sixes, best phase). JSON or rendered team sheet.
```bash
python -m criiq_models.cli recommend --team India --opponent Australia --venue "Lord's" --gender male --pretty
```

#### `explain (--player-id ID | --name NAME) --opponent B [--venue V] [--format T20] [--gender female]`
**What it does:** the full component breakdown for one player against one opponent — every score component (model/matchup/phase-fit/standing/risk), the raw inputs behind each, and the plain-language narrative sentences `recommend --explain` would show for that player.
**Accesses:** same as `recommend`, scoped to one player.
```bash
python -m criiq_models.cli explain --name "V Kohli" --opponent Australia --gender male
```

#### `analyze-xi --team A --opponent B [--venue V] [--format T20] [--gender female] (--players "N1,N2,..." | --player-ids "id1,id2,...") [--explain] [--pretty]`
**What it does:** the counterpart to `recommend` — scores and checks a **coach's own hand-picked XI** (not the algorithm's suggestion) against the identical constraints and scoring `recommend`'s XI is held to, then reports a direct diff against the provably-optimal XI (score gap, and exactly which players are in one but not the other). Unrecognized/ineligible names or ids are reported as a warning and excluded, never silently dropped without explanation.
**Accesses:** same as `recommend`.
**Extracts/produces:** nothing persisted — prints the scorecard (total/average score, constraint satisfaction, violations, comparison-to-optimal) as JSON or a rendered analysis.
```bash
python -m criiq_models.cli analyze-xi --team India --opponent Australia \
  --players "RG Sharma,YBK Jaiswal,V Kohli,SA Yadav,..." --gender male --pretty
```

---

## 3. Quick lookup — "I want to know/extract X, which command?"

| I want to... | Command |
|---|---|
| Rebuild everything from scratch | `data-collection: refresh` |
| See one player's full dashboard | `data-collection: card --name X` |
| See one player's archetype/style/phase profile | `data-collection: profile --name X` |
| See one player's selector one-pager | `data-collection: sheet --name X` |
| See two specific players' head-to-head | `data-collection: h2h --batter X --bowler Y` |
| See a player's record vs. one opponent team | `data-collection: vs-team --name X --team Y` |
| Query win probability for a hand-written match state | `data-collection: winprob --state "..."` |
| Replay a real match's win-probability timeline | `data-collection: winprob --match ID` |
| Check DB health/coverage/freshness | `data-collection: status` |
| Add/fix a player's retirement status | `data-collection: status-override` then `registry` |
| Add/fix a wicket-keeper flag | `data-collection: role-finalize --load-external CSV` |
| Get a recommended XI for a matchup | `model-training: recommend --team A --opponent B` |
| Get the reasoning behind one player's score | `model-training: explain --name X --opponent Y` |
| Check a coach's own hand-picked XI | `model-training: analyze-xi --team A --opponent B --players "..."` |
| Retrain the models after a data change | `model-training: train --gender female` **and** `--gender male` (independent) |
| Check current model accuracy | `model-training: backtest` |

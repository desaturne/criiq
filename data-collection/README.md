# Criiq — Data Collection

Reliable, incremental data pipeline for the Criiq cricket selection system.
Cricsheet ball-by-ball data is the authoritative spine; ESPNcricinfo enrichment
is best-effort and optional. Scope: **T20I** (women's primary, men's in scope).

## What it produces

A single SQLite database (`data/criiq.db`) containing:

| Table | Contents |
|---|---|
| `matches` / `deliveries` | every international T20I match and ball |
| `people` | Cricsheet register incl. **`key_cricinfo`** (the match key) |
| `players` | canonical players (stable `player_id`, joined to ESPNcricinfo id) |
| `player_registry` | eligibility per player/format: activity status (ACTIVE/INCONSISTENT/INACTIVE/UNKNOWN/RETIRED), selection rate, recall flag, age advisory, career phase, ICC rank |
| `icc_rankings` | ICC player rank + rating per format/discipline, with source URL/path, rank date, and extraction timestamp |
| `player_career` | full career batting (avg/SR/HS/50s/100s) **and** bowling (overs/wickets/economy/avg/SR/best) per player/format |
| `player_cards` | dashboard-ready cards: career totals, latest score, form/RFI, team impact, H2H |
| `player_advanced` | derived strengths: phase splits, control/aggression, archetype, bowling usage, vs-pace/spin, vs-LHB/RHB |
| `player_vs_opponent` | full batting+bowling record vs **each opponent** + W/L + Player-of-the-Match |
| `player_impact` | match-impact & importance: contribution share, partnership-breaking, top-order scalps, win contribution, PotM, setting-vs-chasing, importance score |
| `player_phase` | phase split (PP/middle/death) batting+bowling with **rank within own team** |
| `player_by_venue` | batting+bowling performance **at each ground** |
| `dismissal_matchup` | every batter-vs-bowler pair with a real sample (**6+ balls**, safe matchups included, not just dismissals) — **bogey bowler** (overall + per opponent) and favourite victims |
| `match_features` | **win/loss prediction** training table: leakage-safe pre-match form, H2H, toss + label |
| `player_match_impact` | per-player per-match contribution + result label, incl. bowling containment quality (`bowl_dot_pct`, `bowl_boundary_pct`, `bowl_strike_rate`) |
| `ball_state` (parquet, `data/features/`) | per-ball in-game state + outcome label for **live win-probability** models |
| `win_prob` (parquet, `data/features/`) | per-ball **win probability** (batting & bowling team) across all phases, from the empirical model in `data/models/` |
| `player_styles` | bowling style / batting hand / role + provenance |
| `player_role_final` | finalized batter/bowler/all-rounder role (batting-position-refined, not just ball-count) + **wicket-keeper flag** for major nations' current squads, sourced from Wikipedia and merged strictly by `key_cricinfo` |
| `retirement_alerts` | RSS retirement alerts (PENDING until human-confirmed) |
| `venues` | venue alias normalisation |

## How the two sources match

Cricsheet publishes a people register (`people.csv`) with **`key_cricinfo`** — the
ESPNcricinfo player id — so the join is **deterministic by id**, not fuzzy names.
On the live data **100% of actual players resolve with a `key_cricinfo`** (zero
need fuzzy review). The chain:

```
delivery name --[match info registry]--> cricsheet identifier
              --[people.csv]--> key_cricinfo --> ESPNcricinfo
```

Authority: **Cricsheet wins on events** (balls, lineups, results, last-appearance);
**ESPNcricinfo wins on metadata** (DOB, role, retirement). H2H is **computed from
Cricsheet** and cross-checked against Cricinfo.

## Gender-scoped player identity (men's + women's T20I, safely)

The database already ingests **both** men's and women's T20I (3,393 male
matches alongside 2,035 female, at time of writing) — "men's in scope" above
isn't aspirational, the raw data is already there. That surfaced a real
correctness problem: Cricsheet's own per-match player registry (parsed
verbatim in `ingest.py`'s `registry,people,<name>,<identifier>` rows — this
is their data, not a matching bug in this codebase) confirmedly **reuses the
same identifier across two genuinely different real people of different
genders** in 32 cases (e.g. "K Joshi" resolves to both a Nepal women's player
active as of June 2026 and an unrelated men's player) — every derived table
built by `format` alone, not `gender`, would otherwise silently blend two
different people's stats into one corrupted profile.

`identity.py`'s `player_id_for(identifier, gender=None)` and
`resolve_players()` fix this at the root: the ~99.5% of identifiers that only
ever appear under one gender keep the exact same id they've always had (zero
churn); the ~32 confirmed-colliding identifiers each mint two distinct,
stable ids (one per gender, `players.gender` set — the schema's old
`cricsheet_identifier UNIQUE` constraint was relaxed to
`UNIQUE(cricsheet_identifier, gender)` for this). Every derived-table builder
that resolves identifiers to player_ids (`career.py`, `impact.py`,
`phases.py`, `matchups.py`, `advanced.py`, `opponents.py`, `venue_stats.py`,
`registry.py`, `role_finalize.py`, `wpa.py`, `ml_features.py`) now groups by
`(identifier, gender)`, not identifier alone, and resolves through
`identity.player_id_map`/`resolve_player_ids` — real corruption this
uncovered on rebuild: **2,842 orphaned rows** (the old blended records) were
found and removed across every derived table when this was rolled out on the
live DB.

**Why this specifically unblocks men's data being *used*, not just present**:
model-training's whole pipeline already reads this DB scoped by
`gender=SETTINGS.gender` (a settings value, not hardcoded) — extending
recommendations to men's T20I later is a one-line config change *precisely
because* player identity is now safe to share across both genders in the
same tables. Before this fix, doing that would have meant every one of the
32 collision cases actively corrupting both a men's and a women's player's
career stats, phase splits, WPA, and matchup history simultaneously —
correctness debt that would only have gotten worse (more players, more
short-name collisions) the more men's data got used, not less.

**Known residual gap**: `h2h.py`'s `names_for_player` (used by
`batter_vs_bowler`/`player_vs_team`, and transitively by `sheet`/`profile`'s
drill-down views) still resolves by raw display name without a gender
filter, so a specific head-to-head lookup involving one of the 32 split
identifiers can still pull deliveries from both real people. This doesn't
affect anything the recommendation engine actually reads (`player_career`,
`player_impact`, `player_phase`, `dismissal_matchup`, `player_advanced`,
`player_match_impact`, `player_match_wpa` are all fixed) — it's scoped to
data-collection's own standalone reporting commands for those specific 32
identifiers. `player_card.py` has the same residual gap for the same reason
(a display/dashboard table, not read by model-training).

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Full pipeline (incremental; safe to re-run — only new work is done)
python -m criiq_data.cli refresh
python -m criiq_data.cli refresh --enrich      # + best-effort ESPNcricinfo metadata
python -m criiq_data.cli refresh --force       # force re-download

# Individual stages
python -m criiq_data.cli download [--force]
python -m criiq_data.cli ingest
python -m criiq_data.cli identity
python -m criiq_data.cli registry
python -m criiq_data.cli cards
python -m criiq_data.cli career                 # career batting + bowling totals
python -m criiq_data.cli advanced               # derived strengths/style profiles
python -m criiq_data.cli rss                    # scan retirement feeds
python -m criiq_data.cli alerts [--confirm N | --dismiss N]
python -m criiq_data.cli rankings --fetch      # pull public ICC rankings when CRIIQ_ICC_RANKINGS_CLIENT_ID is set
python -m criiq_data.cli rankings --scaffold   # write ICC rankings CSV template
python -m criiq_data.cli rankings              # fetch if configured, otherwise load data/rankings/icc_rankings.csv

# Player styles (for pace/spin & LHB/RHB splits)
python -m criiq_data.cli styles --seed          # seed role/nationality from Wikidata
python -m criiq_data.cli styles --scaffold      # write data/styles/player_styles.csv to fill
python -m criiq_data.cli styles --load          # merge the filled CSV
python -m criiq_data.cli styles                 # coverage report

# Selector deliverables
python -m criiq_data.cli opponents              # record vs each opponent
python -m criiq_data.cli impact                 # match-impact & importance
python -m criiq_data.cli phases                 # phase splits + intra-team rank
python -m criiq_data.cli venues                 # per-ground performance
python -m criiq_data.cli matchups               # batter-vs-bowler dismissals (bogey bowler)
python -m criiq_data.cli vs-team --name "S Mandhana" --team Australia   # her per-bowler/per-batter breakdown vs one opponent
python -m criiq_data.cli ml                      # win/loss + ball-state + per-match impact (model-ready)
python -m criiq_data.cli winprob                 # build ball-by-ball win-probability model (all phases)
python -m criiq_data.cli winprob --match 1429395 # per-over WP timeline for a match (powerplay->death)
python -m criiq_data.cli winprob --state "innings=2,balls_remaining=30,wickets=4,runs_required=40"
python -m criiq_data.cli sheet --name "A Gardner" --format T20   # full performance sheet

# Inspect
python -m criiq_data.cli status
python -m criiq_data.cli card    --name "MM Lanning" --format T20 --first
python -m criiq_data.cli profile --name "A Gardner" --format T20 --first
python -m criiq_data.cli h2h --batter "MM Lanning" --bowler "SFM Devine" --format T20
```

## The individual performance sheet (selector view)

`sheet --name <player>` curates everything onto one page for a selector/coach:
identity + age + eligibility status, career (batting **and** bowling), match-impact
& a transparent **importance score** (0-100), the **record vs every opponent**, the
derived strengths summary, and the last match — plus a plain-language summary. It
reads from `player_career`, `player_impact`, `player_vs_opponent`, `player_advanced`
and the card, so it is assembled instantly with no recomputation.

`python run.py <command>` is equivalent to `python -m criiq_data.cli <command>`.

## "Updated regularly"

`refresh` is idempotent and incremental:
- ZIPs are re-downloaded only when their Last-Modified/Content-Length changes;
- matches already in the DB are not re-ingested;
- ESPNcricinfo is re-fetched only for players missing metadata (cached as Parquet);
- a `last_successful_refresh` marker drives a staleness banner
  (warn > 7 days, stale > 14 days — see `refresh.freshness()`).

Point any scheduler at `python -m criiq_data.cli refresh` (GitHub Actions cron,
local cron, or APScheduler — orchestration-agnostic).

## Advanced data ("detailed" player profiles)

`player_advanced` holds a derived, **fully data-backed** profile per player:

- **Batting** — phase strengths (powerplay/middle/death SR, boundary%, dot%,
  dismissals), overall boundary%/dot%/scoring%/rotation% (control & aggression
  proxies), acceleration (first-10 vs after-10 SR), and an **archetype**
  (anchor / aggressor / finisher / balanced).
- **Bowling** — economy/wickets/dot% by phase, new-ball vs death **usage share**,
  bowling strike rate (balls/wicket) and average.
- **vs-pace / vs-spin** (batting) and **vs-RHB / vs-LHB** (bowling) splits — these
  populate only once `player_styles` is filled (see below).
- A plain-language **strengths summary** for the scouting report.

### What is NOT obtainable (and is therefore not faked)

These were requested but have **no free/legal source** for this scope and are
deliberately excluded rather than fabricated:

- **Ball speed (km/h)** — proprietary ball-tracking (Hawk-Eye/CricViz); not in
  Cricsheet, no free API, and essentially non-existent for women's T20I /
  associate cricket.
- **Shot-control %** — a proprietary CricViz metric from manual ball-coding.
- **Preferred shots / wagon wheels** — needs shot-coded logs; ESPNcricinfo
  **blocks scraping (verified HTTP 403)** and coverage is absent for this scope.
- **Length/line (e.g. "4–6 m"), foot movement ("forward ball %", front/back
  foot), sweep/shot detection** — all require ball-tracking pitch maps or manual
  shot-coding. Cricsheet's per-ball rows have **no** length, line, foot or shot
  columns, so these can't be derived. The genuine, defensible substitutes we *do*
  ship are the **vs pace / spin / off-spin / leg-spin / slow-left-arm** and
  **vs RHB/LHB** splits above (who a batter/bowler is effective against), just not
  *where on the pitch* or *off which foot*.

The phase/control/aggression metrics above are the genuine, defensible
equivalents derived from ball-by-ball. If a board supplies a proprietary feed,
it can be wired into a dedicated table without touching the derived profile.

### Per-opponent matchup breakdown (`vs-team` — the "player card, clicked against a team" view)

`dismissal_matchup` used to only store a batter/bowler pair once the bowler
had actually dismissed her at least once — meaning a bowler who had safely
contained a batter for 50 balls without ever getting her out was invisible
in this table entirely, even though "she's never lost her wicket to X" is
exactly as real a matchup fact as "X has dismissed her 3 times". The filter
is now `balls >= 6` (about an over — enough to be a real sample, not a
single fluke ball) regardless of dismissal count, so every matchup with a
genuine sample is kept (54,145 -> 74,931 rows on the live DB).

`vs-team --name <player> --team <opponent>` surfaces this per-player,
per-opponent, in both directions:

- **Batting** (`batter_vs_team_bowlers`) — every bowler from the opponent
  she's faced for 6+ balls: runs, balls faced, strike rate and dismissal
  rate, with the **bogey bowler** highlighted (ranked by dismissal *count*
  first, then balls — the same convention `top_dismissers` already uses, so
  a bowler who's gotten her out 3 times in 80 balls outranks a lucky 1-for-6
  even though the second has the higher raw rate).
- **Bowling** (`bowler_vs_team_batters`) — every batter from the opponent
  she's bowled 6+ balls to: runs, balls, economy and the batter's own strike
  rate, with **two** highlights answering two different questions —
  `best_matchup` is the batter she's dismissed the *most times*, `most_expensive`
  is the batter who's hit the *most total runs* off her regardless of how many
  balls that took. These are deliberately allowed to be different players
  (verified live: Ellyse Perry vs India — `best_matchup` is Shafali Verma on
  4 wickets, `most_expensive` is Jemimah Rodrigues on 44 runs).

An all-rounder gets both sections; a specialist just gets her one real side
(e.g. Sophie Ecclestone vs Australia carries both — she has a genuine, if
thin, batting record too). Because `dismissal_matchup` has no
`batting_team` column, the bowling direction scopes "the opponent's
batters" through actual roster membership (`role_finalize.team_candidates`)
rather than a stored team field — which surfaced and fixed a second,
smaller instance of the cross-gender identity collision (see above):
`team_candidates`'s join wasn't gender-qualified, so a split identifier
could have matched both the male and female player rows for one real
appearance. Fixed with the same `(p.gender IS NULL OR p.gender = m.gender)`
pattern used everywhere else.

### Retirement, age & ICC rank

The registry no longer marks everyone `UNKNOWN`. Status is inferred from the
**complete** cricsheet appearance history — recency **and** how regularly the
player was selected — with the ICC ranking as a confirming bonus:

- **ACTIVE** — present in an ICC (top-10) ranking; or appeared recently *and* was
  picked for at least `regular_selection_rate` (default 35%) of their team's
  matches since they came into the side; or appeared recently for a team with too
  small a sample to judge consistency.
- **INCONSISTENT** — appeared recently but was an in-and-out selection (picked for
  fewer than the regular threshold of their team's matches since first appearing
  in the window). This is the new bucket for rotation/fringe players, distinct
  from both regulars and the retired/dropped.
- **INACTIVE** — no appearance for 3+ years (likely retired/dropped).
- **UNKNOWN** — an aging gap (outside the active window but not yet stale) with no
  positive signal.

Recency is measured relative to the **most recent match in the data** (`as_of`),
not wall-clock time, so re-running the same snapshot is reproducible and players
in the latest fixtures never drift into "stale". The registry stores
`selection_rate`, `window_player_matches` and `window_team_matches` so each
status is explainable; `status_reason` spells it out in words. Windows and
thresholds live in `Settings` (`selection_window_days`, `min_window_team_matches`,
`regular_selection_rate`).

Age advisory and career phase are role-specific (fast bowler threshold 38, others
40; phase bands per role). Age comes from the Wikidata DOB seed (partial coverage),
so phase/advisory populate only where DOB is known.

**A real, serious bug found and fixed via a live demo check**: `recall_flag`
is meant to flag a borderline-stale player worth a selector's second look —
it is *not* supposed to override a genuinely `INACTIVE` (3+ years absent)
player back into eligibility. Its old formula (`1 if days_since >
recall_flag_days (180) else 0`) never checked that, and since
`recall_flag_days` (180) is far smaller than `inactive_window_days` (1095),
**every unranked `INACTIVE` player automatically got `recall_flag=1`** —
model-training's `roster.team_pool` treats `INACTIVE & recall_flag==0` as
excluded, so this silently defeated that exclusion for anyone not
ICC-ranked. Caught concretely: "RK Parwin", last appearance for India in
**2012**, was still surfacing in 2026 team recommendations. Fixed by adding
the missing guard (`recall_flag` can no longer be 1 once a player is already
past `inactive_window_days`); rebuilding the real registry dropped the count
of players wrongly holding `recall_flag=1` from 5,134 to 2,815. Verified
against the *entire* live database: **zero** players with a last real
appearance before 2023 remain in any of the 90 known teams' current pools
after the fix. A genuine recall-from-retirement (a real selector decision,
not a date arithmetic guess) still has a path — `overrides.py`'s manual
status override — this just stops the automatic heuristic from fabricating
one.

**ICC rank** confirms the elite few but is *not* the primary signal: ICC publishes
only the **top 10** per discipline (Wikipedia carries the same top 10, and the full
list sits behind ICC's credentialed Sportz Interactive widget), so the appearance
history above does the heavy lifting for everyone below the top 10. The rankings
importer uses ICC's public Sportz Interactive endpoint only when a public client id
is configured with `CRIIQ_ICC_RANKINGS_CLIENT_ID`; it sends the project user agent,
requests JSON directly, and refuses to guess credentials or bypass access controls.
Successful fetches are persisted to `data/rankings/icc_rankings.csv`. If no client id
is configured, rank remains a **pluggable CSV**: `rankings --scaffold` writes the
template (columns: format, gender, discipline, rank, rating, player_name,
key_cricinfo); fill it and `rankings` loads it. Ranked players are then marked
ACTIVE and carry their rank/rating.

## Win probability (all phases of a game)

Win probability is **P(the batting team wins | the game state at this ball)**,
scored at every legal ball — so the curve spans powerplay -> middle -> death for
both innings. The training data is the `ball_state` parquet (state + eventual
outcome); `winprob` fits the model, writes a per-ball `win_prob` parquet, and
persists the fitted model under `data/models/`.

The shipped estimator is **empirical** (no extra dependencies): it bins historical
ball-states and takes the actual win frequency, shrunk toward the innings prior so
sparse buckets stay stable. Setting (innings 1) and chasing (innings 2) are scored
by **separate grids** because the target is known only in the chase. Calibration is
reported honestly on a **hold-out split by match, never by ball** (balls from one
game are correlated; a ball-level split would leak). On the live data it beats the
constant-prior baseline comfortably (Brier ~0.17 vs ~0.25, log-loss ~0.51 vs ~0.69).

`EmpiricalWinProb` exposes a small `fit` / `predict` interface, so a calibrated
scikit-learn model (`HistGradientBoosting`/logistic, extensible with team-strength
priors from `match_features`) can be dropped in behind the same surface later
without touching the build or CLI. Two known v1 limitations: the curve is
step-shaped (coarse bins), and it is conditions-agnostic (no team-strength prior).

```bash
python -m criiq_data.cli winprob                  # build model + print calibration
python -m criiq_data.cli winprob --match <id>     # per-over WP timeline (all phases)
python -m criiq_data.cli winprob --state "innings=2,balls_remaining=30,wickets=4,runs_required=40"
```

## Player styles workflow (for the vs-pace/spin & LHB/RHB splits)

Bowling style and batting hand are **not** in Cricsheet, and ESPNcricinfo blocks
scraping. Wikidata (via the ESPNcricinfo-id property) supplies **nationality**
and **partial role** but not style/hand. So:

1. `styles --seed` — pulls role/nationality from Wikidata (free, legal, partial).
2. `styles --wiki` — **auto-fills batting hand + bowling style from Wikipedia
   cricketer infoboxes**, reached via Wikidata sitelinks (cricinfo id → article).
   Free and legal; strong coverage for internationals, partial for associates /
   domestic (players without an English Wikipedia article are simply skipped).
   Existing values are never overwritten, so the manual CSV acts as an override.
   Real yield from running it unrestricted (no `--limit`) against the live DB:
   7,218 candidates processed, 2,269 new bowling styles + 2,582 new batting
   hands filled in under 2 minutes — bowling-style coverage among real female
   T20 bowlers alone went from 127/1,739 (7.3%) to 568/1,739 (32.7%). Re-run
   after any large data refresh brings in new players.
3. `styles --scaffold` — writes `data/styles/player_styles.csv` pre-filled with
   `key_cricinfo` + name; fill/override `bowling_style`, `batting_hand`,
   `playing_role` by hand for anything Wikipedia missed or got wrong.
4. `styles --load` (also run automatically by `refresh`) — merges the CSV; then
   `advanced` recomputes and the vs-pace/spin + vs-RHB/LHB splits populate.

Once hand/style are filled, `player_advanced` and the player card carry:
**batting hand (RHB/LHB)** and **bowling type**; the batter's record **vs pace /
vs spin** *and* a finer **vs off-spin / leg-spin / slow-left-arm** split (runs,
SR, boundary%, dismissals, average); and the bowler's economy / strike-rate /
average **vs RHB and vs LHB**. The strengths summary turns these into coach-facing
matchup notes ("least effective vs leg-spin — a matchup to exploit").

## Finalized role & wicket-keeper flag (`player_role_final`)

`derived_role` (in `players`) classifies purely from ball counts (>=60 balls
faced/bowled = all-rounder), which conflates a genuine batting all-rounder
with a specialist bowler who's simply faced enough tail-end balls over a long
career. Wicket-keeper status has **no signal at all** in the ball-by-ball
data (Cricsheet's CSV export carries no fielder-of-dismissal), so it can only
come from an external source.

```bash
python -m criiq_data.cli role-finalize                              # local pass: batting-position-refined role
python -m criiq_data.cli role-finalize --load-external CSV           # merge externally-researched roles/keeper flags
```

- **Local pass** (`role_finalize.compute_batting_positions` +
  `finalize_local_roles`): derives each player's median batting position from
  the same ball-by-ball data, and reclassifies a ball-count "all-rounder"
  whose median position is deep in the order (>=8) as a bowler instead —
  genuinely new, offline, no external dependency.
- **External merge** (`merge_external_roles`): squad-page role/keeper data
  (currently covers 18 women's T20I nations' current squads, sourced
  from Wikipedia — the original 13 major nations plus UAE, Namibia, Nepal,
  Netherlands, and Hong Kong, added by real match-volume ranking among
  previously-uncovered teams) matched to existing `players` rows and merged **strictly by
  `key_cricinfo`** — never by raw name — so it can never create a duplicate
  identity for a player already resolved (e.g. "Smriti Mandhana" merging
  into the same record as cricsheet's "S Mandhana", not a new one). Squad-page
  names ("First Last") are matched to cricsheet's "XY Surname" convention by
  surname + leading initial (see `role_finalize.match_full_name_to_cricsheet`)
  — plain string-similarity scoring rates these two formats as different
  enough to fall below the project's usual fuzzy_threshold (88), so a
  domain-specific heuristic is used instead. Unmatched names (uncapped
  players not yet in cricsheet's history, or genuine ambiguity) are reported,
  never guessed.

## Scope & config

Edit `criiq_data/config.py`:
- `CRICSHEET_SOURCES` — flip `enabled` to add ODI (scaffolded, off by default).
- polite delays, recall-flag window, RFI parameters, freshness thresholds.

Set `CRIIQ_DATA_DIR` / `CRIIQ_DB` env vars to relocate data.

## Tests

```bash
python -m pytest tests/ -q
```

Unit tests run offline on a synthetic DB (identity join, H2H math, registry
recall/conservative defaults, card form/RFI, info-CSV parsing, validation).

## Design notes

- Pandera was intentionally replaced with lightweight pandas validation
  (`validate.py`) to keep the stack reliable on Python 3.13.
- Cards are built only for players with batting/bowling data; the registry covers
  every selected player (XI membership), so it is the complete eligibility source.
- ESPNcricinfo enrichment uses the ESPN core JSON API and degrades gracefully —
  the whole pipeline runs to completion on Cricsheet alone.

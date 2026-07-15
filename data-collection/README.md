# Criiq — Data Collection

Reliable, incremental data pipeline for the Criiq cricket selection system.
Cricsheet ball-by-ball data is the authoritative spine; ESPNcricinfo enrichment
is best-effort and optional. Scope: **T20I** (women's primary, men's in scope)
**and** major women's domestic T20 leagues (WBBL, WPL, The Hundred, Women's
T20 Blast, Women's T20 Challenge, Women's CSL, T20 Blaze) — see "Domestic
leagues" below.

## What it produces

A single SQLite database (`data/criiq.db`) containing:

| Table | Contents |
|---|---|
| `matches` / `deliveries` | every T20I **and** domestic T20 league match/ball, tagged `team_type` ('international'/'club') |
| `matches_holdout` / `deliveries_holdout` / `match_players_holdout` | anything dated after `SETTINGS.data_cutoff_date` — a genuine forward-test set, never read by any production builder |
| `people` | Cricsheet register incl. **`key_cricinfo`** (the match key) |
| `players` | canonical players (stable `player_id`, joined to ESPNcricinfo id) |
| `player_registry` | eligibility per player/format: activity status (ACTIVE/INCONSISTENT/INACTIVE/UNKNOWN/RETIRED), selection rate, recall flag, age advisory, career phase, ICC rank |
| `icc_rankings` | ICC player rank + rating per format/discipline, with source URL/path, rank date, and extraction timestamp |
| `player_career` | full career batting (avg/SR/HS/50s/100s) **and** bowling (overs/wickets/economy/avg/SR/best) per player/format |
| `player_cards` | dashboard-ready cards: career totals, latest score, form/RFI, team impact, H2H |
| `player_advanced` | derived strengths: phase splits, control/aggression, archetype, bowling usage, vs-pace/spin, vs-LHB/RHB |
| `player_vs_opponent` | full batting+bowling record vs **each opponent** + W/L + Player-of-the-Match |
| `player_impact` | match-impact & importance: contribution share, partnership-breaking, top-order scalps, win contribution, PotM, setting-vs-chasing, importance score (**batting and bowling bonuses are symmetric** — see below) |
| `player_phase` | phase split (PP/middle/death) batting+bowling with **rank within own team** |
| `player_by_venue` | batting+bowling performance **at each ground** |
| `dismissal_matchup` | every batter-vs-bowler pair with a real sample (**6+ balls**, safe matchups included, not just dismissals) — **bogey bowler** (overall + per opponent) and favourite victims |
| `match_features` | **win/loss prediction** training table: leakage-safe pre-match form, H2H, toss + label |
| `player_match_impact` | per-player per-match contribution + result label (**international-only** — see "Domestic leagues"), incl. bowling containment quality (`bowl_dot_pct`, `bowl_boundary_pct`, `bowl_strike_rate`) |
| `player_match_wpa` / `player_phase_wpa` | per-match / career-phase Win-Probability-Added, tagged `team_type`; `player_phase_wpa` stays international-only, same reason as `player_career` |
| `player_domestic_form` | recent-N **domestic-only** matches' average batting/bowling WPA per player — the "quiet internationally, in-form domestically" signal |
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

**~~Known residual gap: `h2h.py`/`player_card.py` still resolved by raw
display name~~ — fixed**, along with two more real cross-gender/cross-venue
bugs a full re-audit (prompted directly by a user request to re-verify that
men's and women's data — and venue-specific analysis — are genuinely never
mixed, "for all country") found and confirmed on live data:

- **`player_card.py` was the most severe of the four**: `build_cards_for_format`
  grouped by raw `identifier` alone (no gender in the key at all, unlike
  every other builder in this file), so for all 32 colliding identifiers the
  female player's `player_cards` row was **silently absent entirely**, and
  the male row's `matches_played`/career/form/impact JSON was the straight
  **sum of both real people's careers**. Confirmed on live data: "SR Taylor"'s
  card showed `matches_played=103` (22 true male + 81 true female, blended);
  after the fix both genders get their own correct, separate card (22 and 81).
  Fixed by threading `gender` through `_ident_to_player`/`_support_tables` and
  the main groupby, same `(identifier, gender)` pattern every other builder
  already used.
- **`h2h.py`'s `names_for_player`** resolved a `player_id` to display names via
  `identifier_map` (which has no gender column) with no gender filter, so
  `batter_vs_bowler`/`player_vs_team` — and `phases.py`'s `phase_vs_opponent`,
  and `player_card.py`'s own `h2h_vs_latest_opponent` field, and the CLI's
  `h2h` command, all downstream of it — silently summed both real people's
  deliveries for any of the 32 collision names. Confirmed on live data: real
  "A Sharma" (India women's vs. an unrelated UAE men's player) vs New Zealand
  returned an identical blended 101 balls/108 runs for *either* player_id
  queried, instead of the true 27/24 (female) and 74/84 (male) splits. Fixed
  by having `names_for_player` also return the player's own `gender` (`None`
  for the ~99.5% of unsplit, unambiguous names — no filter needed for them at
  all), and threading an `AND m.gender=?` clause through every affected query.
- **The ball-by-ball win-probability model itself (`winprob.py`) was fit on
  both genders' balls blended together**, with gender never used as a
  conditioning variable — the single most foundational fix in this list,
  since `player_match_wpa`/`player_phase_wpa`/`player_domestic_form` (and
  therefore every WPA-based feature and training target model-training uses)
  all derive from it. Men's and women's T20 have genuinely different typical
  scores and required-run-rate distributions, so a shared model was
  miscalibrated for both. Fixed by fitting, evaluating, and persisting a
  separate `EmpiricalWinProb` per `(format, gender)` (`winprob_{fmt}_{gender}_*`,
  mirroring model-training's own `_artifacts_dir(fmt, gender)` fix) and
  scoring each gender's deliveries with its own model in both `winprob.py`
  and `wpa.py`'s `compute_ball_wpa`. Real post-fix calibration, confirmed
  distinct per gender: female Brier 0.1557 vs. baseline 0.2447 (93,714 test
  balls); male Brier 0.1727 vs. baseline 0.25 (145,372 test balls). Both
  gender's model-training artifacts were retrained afterward since the WPA
  labels/features themselves changed.
- **`styles.py`'s `bowler_buckets()`/`batter_hands()`** (feeding `advanced.py`'s
  vs-pace/vs-spin and vs-batting-hand splits) resolved by raw player name with
  no gender in the key either — dormant (zero of the 32 collision identifiers
  currently have *both* genders' style data populated at once, confirmed by
  direct query), but unsafe the moment ongoing Wikipedia enrichment fills in
  both sides for one of them. Fixed the same way, pre-emptively: both
  functions now key by `(player_name, gender)`, with a
  split-then-unsplit-fallback lookup in `advanced.py`.

None of the four affect anything the recommendation engine's actual scoring
path reads except through the (now-fixed) shared `winprob`/`wpa` chain —
`player_career`, `player_impact`, `player_phase`, `dismissal_matchup`,
`player_advanced`, `player_by_venue`, `player_registry` were all independently
re-verified clean across all 32 colliding identifiers as part of this same
audit (zero cross-gender join mismatches via `player_match_wpa`/`matches.gender`,
plausible/distinct real numbers on direct inspection).

### A related, separately-confirmed venue bug: genuinely different grounds sharing one venue_id

`identity.py`'s `normalise_venues()` falls back to `raw.split(",")[0]` for any
raw venue string not in the curated `_VENUE_ALIASES` dict — fine for a
specific ground recorded with varying city detail (e.g. "Kensington Oval,
Barbados" / "Kensington Oval, Bridgetown"), but for a *generic* ground name
this silently merges genuinely different real stadiums that happen to share
a bare prefix. Confirmed on live data (checked all 117 canonical names built
from more than one raw string; these were the only two genuine conflations):

- `venue_id='county-ground'` merged 6 raw strings spanning **5 different**
  real English county grounds (Bristol, Chelmsford, Derby, Hove, Northampton,
  New Road/Worcester) — 54 matches sharing one venue_id, `player_by_venue`
  showing implausible combined match counts, `venue_dismissal_matchup` listing
  bowlers from three different countries as top dismissers "at" one ground.
- `venue_id='national-stadium'` merged New Zealand's National Stadium
  (Hamilton) with Pakistan's National Stadium (Karachi) — 29 matches across
  two continents under one venue_id.

Fixed by adding explicit `_VENUE_ALIASES` entries disambiguating each
specifically-qualified raw string (keeping the city, not stripping it), and
giving the *unqualified* "County Ground"/"National Stadium" raw strings
(which genuinely don't say which real ground — Cricsheet's own data
ambiguity, not guessable) their own honestly-labelled "(ground unspecified)"
canonical name/venue_id rather than merging them with any specific one — the
same "don't fake what isn't there" principle as the rest of this README.
"County Ground, Taunton" (2 matches) was confirmed to be the *same* real
ground as "The Cooper Associates County Ground[, Taunton]" (Somerset's
sponsored name) and aliased to join that pair correctly, rather than being
left to collide with the other cities. Rebuilt on live data:
`venues`/`venue_stats`/`matchups` all re-run; `resolve_venue("County
Ground, Bristol")` now correctly resolves to its own distinct venue_id, and
`resolve_venue("County Ground")` now surfaces the full honest "did you
mean" list (all 6 named grounds plus the unspecified bucket) instead of
silently picking the wrong one.

## Domestic leagues, a hard data cutoff, and the national-team-vs-recency split

International T20I alone had a real selection blind spot: a player who's gone
quiet internationally but is in strong current form in a domestic league
(WBBL, WPL, The Hundred, ...) couldn't outrank someone still picked
internationally but playing poorly, because domestic data simply wasn't
ingested, and even *eligibility* (`player_registry`'s activity status) was
computed purely from international appearances — a 3+ year international
absence hard-excluded her from any team pool regardless of what she was doing
domestically.

**Data ethics**: domestic leagues are downloaded from the same Cricsheet site,
same politely rate-limited `download_cricsheet.py` mechanism, same shared
people-register identity resolution already relied on for the international
data — no new scraping target, no new legal exposure beyond what's already
accepted for the international pipeline. `config.py`'s men's domestic entries
are scaffolded `enabled=False`, matching the existing men's ODI pattern —
present, not yet active, trivial to flip on later.

**`ingest.py`** no longer drops non-international matches — it stores
Cricsheet's own `team_type` field ('international'/'club') on every row
instead. A new `SETTINGS.data_cutoff_date` (`"2026-06-15"`, the live DB's
actual latest date at time of writing — a forward safeguard, not a present-day
trim) routes anything newer into `matches_holdout`/`deliveries_holdout`/
`match_players_holdout` — a genuinely untouched forward-test set, so **no
other file needs a date filter added anywhere**.

**The critical fix, found by a design-review pass before this shipped**: two
different questions were sharing one data path and had to be split.
"Which national team does she currently play for" (`registry.py`'s
`recent_team`/`team_dates`/`selection_rate` windowing, and model-training's
`roster.player_current_teams`) must stay **international-only** — otherwise a
domestically-heavy recent window resolves a player's "team" to a franchise
name, silently dropping her out of her own *country's* candidate pool
entirely (the opposite of the intended effect). "Is she still playing
competitive cricket" (the recency signal feeding
ACTIVE/INCONSISTENT/INACTIVE/UNKNOWN) is the **union** of international and
domestic appearance dates — this is the actual fix for the scenario above.
Explicit `RETIRED` status (Cricsheet's own signal, or `overrides.py`'s manual
override) is untouched by either change — a domestic cameo never un-retires
someone a human explicitly marked retired (verified live: Meg Lanning's
`last_appearance_date` correctly updates to her recent WBBL matches, but her
manual `RETIRED_ALL` override still holds).

Every derived-table builder that was previously implicitly international-only
(by construction, since nothing else existed) now says so explicitly —
`career.py`, `impact.py`, `phases.py`, `matchups.py`, `advanced.py`,
`venue_stats.py`, `opponents.py`, `player_card.py`, `h2h.py`, `role_finalize.py`,
and `ml_features.py`'s win/loss + win-probability training data all filter to
`team_type='international'` (via `stats.build_innings`'s new `team_type`
parameter where they share that helper, or a direct clause where they don't) —
otherwise the moment domestic matches existed in `matches`/`deliveries`, every
one of these would have silently blended domestic stats into what's meant to
be a pure international career line.

**`wpa.py`** is the one deliberate exception: it processes *every* match
(international and domestic both, tagged by `team_type` in the resulting
`player_match_wpa` row) — domestic matches are *scored* by the same
already-fitted, international-trained `EmpiricalWinProb` model, the same way
an international match is (a reasonable reuse, not a new assumption; domestic
T20 win-probability dynamics are similar enough, and building a separate
domestic-only model wasn't warranted for this signal). `player_phase_wpa`
(the career-phase aggregate) still filters back down to international-only,
matching `player_career`; `player_domestic_form` is the new, separate,
domestic-only aggregate built from the same tagged rows.

Real verification (live DB): `GA Elwiss`, `A Wellington`, `L Winfield` — all
last appeared internationally 3+ years ago, all recently active in WBBL/The
Hundred — now correctly resolve to their real country (not a franchise) via
`player_current_teams`, are no longer misclassified `INACTIVE`, and are
present in their country's full eligible roster pool (previously hard-excluded
entirely).

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

### Importance score: a symmetric batting bonus

`impact.py`'s importance score used to give bowlers/all-rounders a
`bowling_impact_part` bonus (up to 15 pts, for a high rate of top-order
wickets) with no batting equivalent — checked against the live DB, this
wasn't theoretical: pure batters averaged **28.3** importance score vs
**50.5** for all-rounders, and ~10.4 of that ~22-point gap was specifically
the bonus a pure batter could structurally never earn (the rest is the
`contribution_part` bucket legitimately rewarding genuine dual-discipline
contribution). Fixed by adding a real, percentile-matched `batting_impact_part`
(rate of 30+ run innings — "an innings worth having", mirroring "a wicket
worth having" — multiplied by 70, chosen so its mean and 75th-percentile line
up with `bowling_impact_part`'s own real distribution, not a guessed
constant), plus the final-score clamp to 100 this makes necessary now that a
genuine all-rounder can earn both 15-pt bonuses at once. Re-checked post-fix:
pure batters' average rose to **37.85** — almost exactly the ~9.4 the
calibration targeted — and the residual gap to all-rounders is attributable
only to genuine dual-discipline contribution, not a structural bonus a pure
batter could never reach.

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
  proxies), **six rate** (sixes per 100 balls), acceleration (first-10 vs
  after-10 SR), and an **archetype** (anchor / power hitter / finisher /
  balanced).
  - **Archetype is classified against each gender's own population, not a
    shared absolute bar.** Men's and women's T20 six-hitting and strike-rate
    distributions differ sharply (men's six rate p90 ~8.0 per 100 balls vs
    women's ~1.9, SR p90 ~146 vs ~115 on the live DB), so an absolute SR/six
    threshold would tag most men "power hitters" and almost no women, for no
    cricketing reason. `_gender_archetype_thresholds` computes per-gender
    percentile bars once per build; `_archetype` classifies against them:
    **finisher** = bats a real share at the death *and* is genuinely
    destructive there (death SR *and* death boundary% both above the gender
    high bar — strike rate + sizes + boundaries, what a death finisher needs);
    **power hitter** = clears the rope well above the gender norm (six rate at
    or above the gender p75) at a high strike rate (six rate is the primary
    signal — a raw six *count* just tracks career length); **anchor** =
    accumulator (bats up top, rotates hard, below-median SR). finisher takes
    precedence, so a death specialist who also hits sixes (e.g. RM Ghosh)
    reads as the more specific role.
  - A **minimum-sample gate** (60 balls faced, 40 of them at the death for a
    finisher) blocks tiny-sample false positives — a real one found on live
    data: a bowler who faced 7 balls at the death was being tagged "finisher"
    before the gate.
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
- `CRICSHEET_SOURCES` — flip `enabled` to add ODI or men's domestic leagues
  (all scaffolded, off by default).
- `data_cutoff_date` — the forward-test-set boundary (see "Domestic leagues..."
  above); anything newer routes to the `_holdout` tables automatically.
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

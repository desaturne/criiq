# Criiq — Algorithms, Models & Math, Explained

This document explains **every algorithm, model, and mathematical concept used across `data-collection` and `model-training`**, why each was chosen over alternatives, where the numbers come from, and the cricket intuition behind them. Read top-to-bottom, or jump to a section.

---

## 0. Where the data actually comes from

Before any algorithm runs, there has to be data. This section explains the raw source, what competitions are included, how much data exists, and how "domestic form" is built and used — because none of the modeling later makes sense without knowing this first.

### 0.1 Primary source: Cricsheet

**Cricsheet** (`cricsheet.org`) is the raw data spine — a free, community-maintained archive of **ball-by-ball** cricket scorecards, published as CSV/YAML per match, for essentially every recorded T20I and major T20 league match. Criiq's `data-collection/criiq_data/download_cricsheet.py` downloads Cricsheet's ZIP archives per competition, and `criiq_data/ingest.py` parses each match into two core tables:

- **`matches`** — one row per match (teams, date, venue, gender, format, toss, result, `team_type` = `"international"` or `"club"`).
- **`deliveries`** — one row **per ball bowled** (batter, bowler, non-striker, runs off the bat, extras, wicket type and dismissed player if any, over/ball number). This is the atomic unit everything else — win probability, WPA, the match simulator's outcome distributions — is built from.

**Why Cricsheet and not, say, ESPNcricinfo scorecards directly:** Cricsheet already publishes *structured, ball-by-ball* data for free and legally; ESPNcricinfo has finer detail in places (shot type, line/length) but actively blocks scraping (confirmed HTTP 403) and would be both legally and technically unreliable as a primary source. ESPNcricinfo is instead used as a **secondary, best-effort enrichment** layer (player metadata, rankings) — the whole pipeline is designed to run to completion on Cricsheet alone if that enrichment is unavailable.

Player identity across the two sources is joined deterministically via Cricsheet's own `people.csv`, which carries an ESPNcricinfo player key (`key_cricinfo`) — no fuzzy name matching needed for this particular join.

### 0.2 What's actually ingested: T20I plus 7 women's domestic T20 leagues

The scope is **not just international cricket**. `criiq_data/config.py` lists every competition source, each independently switchable:

| Competition | Gender | Status |
|---|---|---|
| T20 Internationals | Female | **Enabled** |
| T20 Internationals | Male | **Enabled** |
| ODIs | Both | Disabled (scaffolded, not currently ingested) |
| **Women's Big Bash League (WBBL)** | Female | **Enabled** |
| **Women's Premier League (WPL)** | Female | **Enabled** |
| **The Hundred (Women's competition)** | Female | **Enabled** |
| **Women's T20 Blast** | Female | **Enabled** |
| **Women's T20 Challenge** | Female | **Enabled** |
| **Women's Cricket Super League (WSL)** | Female | **Enabled** |
| **T20 Blaze** | Female | **Enabled** |
| IPL, Big Bash League, PSL, CPL, (men's) T20 Blast | Male | Disabled (scaffolded, not currently ingested) |

So today, the live database contains **T20 internationals (both genders) plus seven women's domestic T20 leagues**. Men's domestic leagues (IPL, BBL, PSL, CPL) are wired into the config but deliberately left switched off — meaning the current "domestic form" signal that feeds the model is a **women's-cricket-specific enrichment** for now; the men's side of the pipeline runs on international data only until those sources are turned on.

**Why domestic league data at all, not just internationals?** A player can be quiet at international level for stretches (out of the XI, a lean patch) while genuinely in career-best form in their domestic league right now — international-only stats would miss that entirely. Domestic data closes that gap, at the cost of needing extra care so it doesn't *contaminate* the international-only statistics (see §0.4).

**Confirmed real counts:**
- T20 internationals: **3,393 male matches** and **2,035 female matches** in the live DB (at time of writing in the codebase's own README).
- Distinct female T20 bowlers in the DB: **1,739** (used as the denominator for a bowling-style coverage improvement from 127 → 568 players, 7.3% → 32.7%, after a Wikipedia enrichment pass processed 7,218 candidate players in under 2 minutes).
- The `dismissal_matchup` table (head-to-head batter-vs-bowler history) holds **74,931 rows** on the live DB after a sample-size filter fix (previously 54,145 — the fix widened qualifying pairs, it did not shrink them).
- Win-probability model evaluation held out **93,714 test balls** (female) and **145,372 test balls** (male) — see §4.4 for what these numbers measure.
- Distinct players overall: **4,449 distinct men's T20 players vs. 2,549 distinct women's T20 players**, confirmed by direct DB query (`model-training/README.md`) — a larger raw pool for men's despite men's domestic leagues still being switched off, since men's T20I alone has been played longer and more widely.
- The domestic-form shrinkage cap (§0.4) was grid-searched "at the current ~220-domestic-player data scale" — i.e., roughly 220 distinct players in the DB currently have any domestic-league (`team_type='club'`) match history at all, out of the women's domestic leagues that are switched on.
- `age_years` feature coverage (tried, ultimately not adopted as a model feature — see §3.7): **55.8% of women's training rows** and **60.6% of men's training rows** had a resolvable `date_of_birth`.

### 0.3 The ingestion → derived-stats pipeline

Twelve sequential stages, orchestrated by `criiq_data/refresh.py`, turn raw Cricsheet files into every table the model layer reads:

```
1. download_register   → Cricsheet's people.csv (player identity registry)
2. download_cricsheet  → competition ZIP archives
3. ingest               → raw files → matches / deliveries tables
4. identity             → resolves (cricsheet_identifier, gender) → stable player_id
5. scrape_cricinfo (*)  → optional ESPNcricinfo metadata enrichment
6. styles               → player_styles (batting hand, bowling style — manual CSV + optional Wikipedia)
7. rss_monitor          → retirement_alerts (news-feed monitoring)
8. rankings/registry/career → player_registry, player_career, player_cards
9. advanced             → player_advanced (batting profile: SR, boundary%, dot%, phase splits, archetype)
10. opponents/impact/venue_stats/matchups/phases → player_vs_opponent, player_impact,
    player_by_venue, dismissal_matchup, player_phase
11. ml_features         → match_features, ball_state (parquet), player_match_impact
12. winprob             → fits EmpiricalWinProb per (format, gender), persists the win-probability grids
```

A 13th stage (run separately via the CLI, since it depends on stage 12's already-fitted win-probability model) computes **WPA**: `wpa.build_wpa_for_format` → `player_match_wpa` / `player_phase_wpa`, then `wpa.build_domestic_form_for_format` → `player_domestic_form`.

**(*) an important, deliberate change:** ingestion used to *drop* non-international matches outright. It no longer does — every match, domestic or international, is kept and tagged with Cricsheet's own `team_type` field (`"international"` vs `"club"`). This single flag is what lets every downstream table choose, explicitly, whether to include domestic matches or not (see next section) — rather than domestic data being unavailable at all.

### 0.4 Domestic form: kept separate from career stats, on purpose

This is one of the more carefully-reasoned design decisions in the whole project, so it's worth explaining precisely.

**The risk:** if you naively blended a player's domestic-league and international performances into one "career average," you would be comparing apples to oranges — bowling economy in a batter-friendly T20 league is not on the same scale as international bowling economy, playing conditions and opposition quality differ, and a player who dominates domestically may not (yet) perform the same way internationally. Blending them would *corrupt* the career signal the same way mixing preseason-game and playoff-game stats would corrupt an NBA player's "true" scoring average.

**The fix — two parallel tracks, joined only for one specific purpose:**

1. **International-only tables** (`player_career`, `player_impact`, `player_phase_wpa`, and several others) explicitly filter to `team_type = 'international'`. These are the tables that answer "how good is this player, historically, at the level that matters for team selection."
2. **`player_domestic_form`** is a *separate*, explicitly domestic-only aggregate: `wpa.build_domestic_form_for_format` filters to `team_type = 'club'`, takes each player's **most recent 10 domestic matches** (`SETTINGS.impact_recent_matches = 10`), and computes their mean batting/bowling WPA over just those matches.
3. There is exactly **one** deliberate exception where domestic and international data mix in the same computation: `player_match_wpa` (the table `player_domestic_form` reads from) is built from *every* match regardless of `team_type`, because it needs to score domestic matches using the *same, already-fitted, international-trained* win-probability model — this is a considered reuse of a good model on new data, not letting domestic *stats* leak into international *stats*.

**How it's actually used in scoring:** `domestic_form_batting_wpa` / `domestic_form_bowling_wpa` are two extra features fed into the batting/bowling WPA prediction models (§3), *not* a separate scoring bucket — they let the model learn "does recent domestic form predict anything about a player's likely international impact, beyond what their international career stats already say." Crucially, this domestic signal is itself **shrunk toward the player's international career WPA** (§4.3 explains the shrinkage formula), with the *sample size fed into that shrinkage capped* at a maximum of 10 effective matches — meaning no amount of domestic-league volume can ever fully override the international prior. This cap was chosen from an actual grid search (5/10/15/20 effective matches, same repeated-holdout methodology used everywhere else in this project) rather than guessed — the real finding was that, at the current ~220-domestic-player scale the codebase's README describes, the different cap values scored within noise of each other on the holdout metrics, so 10 was kept as a reasonable middle setting rather than because it measurably won.

**Concrete real example, quoted from the project's own output** (`explain --player-id <GA Elwiss> --opponent Australia`):

> "Recent domestic form (10 matches): shifting win probability by -4.6% per match with the bat and +1.2% with the ball — factored into the model above, alongside 7 international career matches."

This is an honest (not cherry-picked) example: her domestic batting form was actually negative when this was captured, and the system reported that plainly rather than only surfacing flattering numbers.

---

## 1. Picking the Playing XI — Mixed-Integer Linear Programming (MILP)

**File:** `selection/optimize.py` (`select_xi`, `analyze_xi`)

### What MILP is, formally

A **Mixed-Integer Linear Program** is an optimization problem of the form:

```
maximize      c^T x                     (a linear objective)
subject to    A x ≤ b                   (linear constraints)
              x_i ∈ {0, 1}   for some i  (some variables restricted to integers/binary)
```

Here, `x_i ∈ {0,1}` is a binary "select player *i* or not" variable per candidate, `c_i` is that player's score, and the constraint matrix `A`/vector `b` encode things like "exactly 11 players," "at least 5 batting-capable," etc.

### Applied to XI selection

- **Decision variables:** `x_1, ..., x_n ∈ {0,1}` — one per player in the candidate pool, `1` if selected.
- **Objective:** `maximize Σ score_i · x_i` — total score of the chosen XI.
- **Constraints (all linear):**
  - `Σ x_i = 11` (exactly 11 players)
  - `Σ (is_batting_capable_i) · x_i ≥ 5`
  - `Σ (is_bowling_capable_i) · x_i ≥ 5`
  - `Σ (is_keeper_i) · x_i ≥ 1` (only enforced if the pool actually has keeper data — soft constraint, see below)
  - `Σ (is_opener_i) · x_i ≥ 2` (same, soft)

`scipy.optimize.milp` solves this with a **branch-and-bound** algorithm: solve the "relaxed" version first (allow `x_i` to be any real number between 0 and 1, which is a much easier plain linear program), and if the answer isn't already all 0s/1s, pick a fractional variable, branch into two subproblems (force it to 0, force it to 1), and recurse — pruning branches that can't beat the best whole-number solution found so far. This is a *complete* search (not an approximation) — it is guaranteed to return the true global optimum, or prove no feasible solution exists.

### Why this, not a genetic algorithm or a greedy heuristic

**Rule of thumb: if a problem can be written exactly as linear objective + linear constraints, solve it exactly — don't approximate what you can compute directly.** A genetic algorithm *could* search this space too, but it would only ever produce an approximate, possibly-suboptimal answer to a problem that has an exact, efficiently-computable answer. That's strictly worse here — like using trial-and-error guessing to solve `2x + 3 = 7` when you could just solve the equation.

**Worked mini-example.** Suppose a pool of 4 players, need exactly 2, at least 1 batting-capable:

| Player | Score | Batting-capable? |
|---|---|---|
| A | 9 | No |
| B | 8 | Yes |
| C | 7 | Yes |
| D | 6 | No |

Greedy-by-score picks A+B = 17 (satisfies the constraint by luck here). But if the constraint were "at least 2 batting-capable," greedy-by-score would pick A+B (only 1 batting-capable) and then have to awkwardly patch the choice — whereas the MILP simply *knows* the feasible region up front and finds the true best combination inside it (here, B+C = 15, the only feasible pair with 2 batting-capable players) in one solve, without ever needing a fix-up step.

### Constraint softening

`min_keepers` / `min_openers` degrade automatically (`min(setting, available)`) when real data can't support them (e.g., a team with zero recorded keepers) — this avoids the MILP being **infeasible** (no solution at all) purely because of a data gap, which in production would be a worse failure than temporarily not enforcing a keeper.

### Fallback

If the solver still fails, `_greedy_fallback` takes the top-11 by score and swaps in the cheapest fix for any violated constraint — not optimal, but guarantees *some* legal XI is always returned.

---

## 2. Bowling Rotation & Batting Order — Genetic Algorithms

**Files:** `simulate/ga_bowling.py`, `simulate/ga_batting.py`

### What a genetic algorithm is, formally

A **Genetic Algorithm (GA)** is a stochastic, population-based search heuristic for optimization problems where you can't (or don't want to) write the objective as clean algebra, but *can* evaluate any candidate solution's quality. It maintains a **population** of candidate solutions and repeats, for many **generations**:

1. **Fitness evaluation** — score every individual in the population.
2. **Selection** — keep the better-scoring individuals, discard the rest (survival of the fittest).
3. **Crossover (recombination)** — combine pairs of surviving individuals to produce new "offspring" that mix both parents' structure.
4. **Mutation** — apply small random changes to offspring, to keep introducing genuinely new possibilities the population hasn't tried.

**Term-by-term, mapped to biology (the literal analogy the algorithm is named after):**

| GA term | Biological analogy | What it means here (bowling rotation example) |
|---|---|---|
| Individual / chromosome | An organism's genome | One candidate 20-over bowling rotation |
| Gene | A single trait | One over's assigned bowler |
| Population | A breeding population | 40 candidate rotations at once |
| Fitness | Reproductive success | `-mean(runs conceded)` across simulated innings |
| Selection | Natural selection | Keep the top-scoring rotations, discard the rest |
| Crossover | Sexual reproduction | Splice two rotations together at a random over |
| Mutation | Random genetic mutation | Randomly reassign a few overs to different bowlers |
| Generation | A generation | One full cycle of selection → crossover → mutation |

### Why GA, not MILP, here

The bowling-rotation problem *looks* similar to XI selection but genuinely isn't linear, for two reasons:

1. **The objective has no formula.** "Expected runs conceded for a given 20-over sequence" depends on ball-by-ball dynamics (who's on strike, momentum, matchups) that only exist by *actually running the match simulator*. There's no `runs = Σ coefficient_i · x_i` to write down — you can only *sample* the objective, not compute it directly.
2. **Legality is sequence-dependent**, not sum-dependent. "No bowler may bowl two overs in a row" is a constraint between *adjacent positions* in an ordered sequence — a fundamentally different (and harder) kind of constraint than "at least 5 of this type," which is why this is closer to a scheduling problem than a linear program.

**When the objective is an expensive black box and the search space is large and discrete, a GA (or another evolutionary/metaheuristic search) is the standard tool.** It only needs to *generate* candidates and *evaluate* them — it never needs the objective's formula.

### 2a. Bowling Rotation GA — full mechanics

- **Chromosome:** a list of 20 bowler-IDs, one per over.
- **Fitness:** run the match simulator `n_reps` times (default 8) with this exact rotation fixed, take `-mean(runs conceded)` (negated because the GA maximizes fitness, but fewer runs conceded is the actual goal).
- **Population initialization:** not random — `_quotas` first splits 20 overs across the pool giving the up-to-5 recognized specialist bowlers their real 4-over quota (matching how a real captain plans overs), then `_sequence` places overs using the classic **"always assign whichever remaining bowler has the most overs left, excluding whoever bowled the previous over"** rule — the standard, provably-correct algorithm for arranging repeated items with no two identical items adjacent (same underlying idea as the well-known "rearrange task IDs with a cooldown" scheduling problem), guaranteed to succeed whenever the most-frequent item's count doesn't exceed half the total slots.
- **Selection:** truncation selection — sort by fitness, keep roughly the top half.
- **Crossover:** single-point — pick a random over-index `k`, `child = parentA[:k] + parentB[k:]`.
- **Mutation:** each of the 20 overs independently has a 15% chance of being reassigned to a uniformly random bowler from the pool.
- **Repair, not penalize:** crossover/mutation will produce illegal rotations (a bowler over 4 overs, or two identical overs adjacent). Rather than penalizing bad candidates in the fitness score (wasteful — you'd spend simulator calls on things you'll discard anyway) or rejecting them (shrinks the population), `_repair` deterministically fixes every child: count each bowler's overs, cap at 4, reassign overage to bowlers with spare capacity (preferring specialists), then re-sequence with the same greedy no-repeat rule.
- **Handling a noisy fitness function.** `-mean(runs conceded)` over only 8 simulated innings is a noisy estimate — two equally good rotations can show different scores just from randomness, the same way flipping a coin 8 times and getting 6 heads doesn't prove the coin is biased. Two protections:
  - **Elitism** — the best-known individual always survives into the next generation regardless of how it happens to score on a fresh sample, so a genuinely good rotation can never be lost to bad luck.
  - **Re-verification** — before accepting a new "best," it's re-scored with 3× the reps (24 instead of 8); the final answer is verified with 30+ reps. This mirrors why clinical trials need a large-enough sample before declaring a result real — a small sample can look convincingly different purely from noise.
- **Fitness history is monotonic by construction** — it logs the *running best-known* fitness, not each generation's raw top score, specifically because plotting the raw noisy top score visibly bounces up and down and looks like "the GA isn't converging" even when the tracked best genuinely never regresses (a real, documented bug fixed this way).

### 2b. Batting Order GA — what's different

Same skeleton (population, truncation selection, elitism, re-verification), but:

- **Chromosome:** a *permutation* of the 11 batters, searched **within role bands** (openers / top-middle order / tail) rather than one free-for-all permutation — players are grouped by real historical batting position + role, and the GA only permutes within a group, never moving a specialist bowler up to open. This isn't a post-hoc rule; it shrinks the search space to combinations that make cricket sense, so generations aren't wasted testing nonsensical orders.
- **Crossover — Order Crossover (OX), specifically because this is a *permutation*, not an independent list.** A batting order has each player exactly once; naive single-point crossover on a permutation is *broken*. Example: parent A = `[1,2,3]`, parent B = `[3,1,2]`. A single-point splice at index 1 gives `[1] + [1,2] = [1,1,2]` — player 3 vanished, player 1 duplicated, an illegal order. **Order crossover fixes this:** copy a contiguous slice from parent A verbatim into the child, then fill the remaining slots with parent B's players *in the order they appear in B*, skipping anyone already placed. This always produces a valid permutation. (OX is a standard, well-known genetic operator specifically for permutation problems — the traveling-salesman problem is the classic textbook example that popularized it.)
- **Mutation:** swap two random positions within the same role band, 20% probability.
- **Fitness:** mean simulated score (first-innings framing) — or, given a `--target` (a chase scenario), the **fraction of simulated reps that actually reach the target**, i.e., an approximate win probability for a chase. This matters because "maximize expected runs" and "maximize the chance of reaching exactly 162" are genuinely different objectives — an order that occasionally scores 220 but often falls short of 160 can have a *worse* chase win-rate than a steadier order that reliably clears 165, even with a lower average.

---

## 3. Predicting Player Impact — Win-Probability-Added (WPA) Regression Models

**Files:** `recommend/train.py`, `recommend/score.py`, `features/historical.py`, `data-collection/criiq_data/wpa.py`, `data-collection/criiq_data/impact.py`

### 3.1 What "Win Probability Added" means, with the exact formula

For every single ball in a match, the already-fitted win-probability model (§4.4) outputs `win_prob_batting` — the batting side's probability of winning *given the match state right after that ball* (score, wickets, overs used/remaining, target). WPA is simply the **change** in that probability caused by one ball:

```
delta_wp(ball_t) = win_prob_batting(state after ball_t) - win_prob_batting(state after ball_{t-1})
```

(the very first ball of an innings uses the true starting-state win probability instead of an undefined "previous ball," since there is no ball 0.)

**Attribution:** the batter on strike is credited `+delta_wp` toward their **batting WPA**; the bowler is credited `-delta_wp` toward their **bowling WPA** (a ball that helps the batting side necessarily hurts the bowling side's win chance, so the sign simply flips for the bowler's ledger). The non-striker gets nothing — they weren't directly involved in that ball's outcome.

**Worked numeric example:** suppose before a ball the batting side's win probability is 42%, and after a six it's 47%. `delta_wp = +0.05`. The striker's batting WPA for that ball is `+0.05`; the bowler's bowling WPA for that ball is `-0.05`. Summed and averaged across a whole match (or many matches), this becomes each player's per-match WPA — the actual quantity the regression models (§3.3) are trained to predict for *future, not-yet-played* matches, from historical stats.

### 3.2 Why WPA instead of "contribution share"

The engine originally used **contribution share** (% of team runs scored, % of team wickets taken) as its ranking signal, and this produced a real, documented failure: a part-time all-rounder outranked a long-proven opener, because contribution-share measures *how big your numbers looked*, not *whether your team actually won because of you*. A batter who scores 40 off 25 balls in an already-decided blowout "contributes" a lot numerically but barely moves the result; a batter who scores 20 tense, well-timed runs in a close chase might contribute far less by raw count but be the actual reason the team won.

Concrete evidence quoted from the project: Smriti Mandhana's average batting WPA is **+0.077 per match** across 144 matches; the player who had wrongly outranked her under the old contribution-share metric averaged **-0.002** across 23 matches — despite that player's raw "contribution" numbers looking competitive. This single comparison was the concrete trigger for switching the whole engine to WPA.

**Analogy:** this is exactly the difference between a basketball player's total point count and their **win-probability-added** (an established, real sports-analytics metric) — a garbage-time three-pointer in a 30-point blowout counts identically to a game-winning buzzer-beater in the box score, but the two are worlds apart in actual impact on the result.

### 3.3 The regression models: exact architecture, hyperparameters, and training procedure

Two separate models are fit — one predicting `batting_wpa`, one predicting `bowling_wpa` — **not** one combined "overall impact" label, so a pure specialist bowler's nonexistent batting involvement never drags down their bowling rating. Everything in this subsection is quoted directly from `recommend/train.py`.

**Preprocessing pipeline (`_rf_pipeline`, shared by every Random Forest variant):**
```python
pre = ColumnTransformer([
    ("num", SimpleImputer(strategy="median"), NUMERIC_FEATURES),
    ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
])
Pipeline([("pre", pre), ("model", RandomForestRegressor(...))])
```
Missing numeric values are imputed with the column **median** (robust to outliers, unlike mean imputation); the one categorical feature (`role_bucket`) is one-hot encoded, with `handle_unknown="ignore"` so a role value never seen in training doesn't crash live scoring.

**`batting_wpa` model — exact hyperparameters:**
```python
RandomForestRegressor(
    n_estimators=300,
    max_depth=10,
    min_samples_leaf=5,
    max_features="sqrt" if gender == "female" else None,
    random_state=42,
    n_jobs=-1,
)
```
- `n_estimators=300` — number of individual decision trees averaged together (more trees → lower variance, at a roughly linear extra compute cost; 300 is well past the point of diminishing returns for a dataset this size).
- `max_depth=10` — caps how many splits deep any single tree can go, limiting how finely it can carve up the data (and therefore how much it can memorize noise).
- `min_samples_leaf=5` — a leaf node (final prediction group) must contain at least 5 training rows; forbids the tree from creating a leaf tailored to a single freak match.
- `max_features="sqrt"` (**female scope only**) — `RandomForestRegressor`'s own default (unlike its classifier sibling) considers *every* feature at each split, so trees barely decorrelate from one another; explicitly subsampling to `sqrt(n_features)` candidates per split is the textbook Random Forest regularization for that, and it measurably helped — but a live check found it does NOT generalize to the male scope (see "Why these specific numbers" below), so it's applied conditionally rather than assumed universal.
- `random_state=42` — fixes every source of randomness (bootstrap sampling, feature subsampling per split) so training is exactly reproducible run-to-run.
- `n_jobs=-1` — use all available CPU cores to train trees in parallel (Random Forest trees are independent of each other, so this parallelizes trivially, unlike boosting).

**`bowling_wpa` model — exact hyperparameters (a `VotingRegressor` averaging two sub-models):**
```python
hgb = HistGradientBoostingRegressor(
    categorical_features="from_dtype",
    random_state=42,
    max_depth=2,
    min_samples_leaf=50,
)
rf = RandomForestRegressor(
    n_estimators=300, max_depth=6, min_samples_leaf=50,
    random_state=42, n_jobs=-1,
)
VotingRegressor([("hgb", hgb), ("rf", rf)], weights=[0.7, 0.3])
```
- `max_depth=2` on the boosted-tree half — deliberately very shallow (a depth-2 tree can only ask 2 sequential questions before predicting), because bowling-WPA is the weaker/noisier of the two targets and an unconstrained booster was found to overfit it badly (correlation actually *improved* from ≈0.088 to ≈0.105 purely from this one change, confirmed on holdout).
- `min_samples_leaf=50` (both halves) — a much stricter floor than batting's `5`, again because bowling's signal is thinner and needs more aggressive regularization to avoid chasing noise.
- `weights=[0.7, 0.3]` — favors the depth-limited HistGB over the Random Forest, **not** an even split. A later live check (see below) found reweighting away from equal-weight measurably helped on both gender scopes; equal weight was the original, since-superseded choice.

**Why these specific numbers, not others — the search process.** No automated hyperparameter search (`GridSearchCV`, `RandomizedSearchCV`, Optuna, etc.) exists anywhere in the codebase. Instead, hyperparameters were selected by a **manual, repeated-holdout comparison** run in a separate notebook (`model_comparison.ipynb` / `model_comparison_robust.ipynb`), *not* baked into `train.py` as search code — the notebook trains candidate configurations, `train.py`'s comment block documents the winning configuration and the reasoning, and a maintainer must re-run the notebook and update `train.py` by hand if the feature set changes. The validation protocol for every tuning decision was: **3 different temporal-holdout fractions (0.15 / 0.2 / 0.25) × 5 random seeds each = 15 independent evaluations**, averaged — specifically to avoid a decision being driven by one lucky/unlucky split (the same reason a single coin flip tells you almost nothing about whether a coin is fair). Concretely documented deltas from this process:
- Depth-limiting the bowling booster to `max_depth=2`: mean correlation ≈0.088 → ≈0.105 across all 3 splits, **and** run-to-run standard deviation roughly halved (≈0.005 → ≈0.002) — both accuracy *and* stability improved together, a good sign the change was genuinely helpful rather than a lucky trade-off.
- Adding the `VotingRegressor` ensemble on top: ≈0.105 → ≈0.110–0.118 depending on split.
- Batting's `RandomForestRegressor(max_depth=10, min_samples_leaf=5)` was chosen over an unregularized forest because the unregularized version was confirmed (by actually running it, not assumed) to fall *below* a trivial mean-predictor baseline on holdout MAE — too much capacity for too little real signal.

**A later live search** (`training_and_selection_walkthrough.ipynb`, this repeats the same
3-fraction protocol but with 3 seeds rather than 5, plus a paired t-test on top) tried roughly 20
further candidates per target — different depths/leaf sizes, ensemble weights, winsorize
quantiles, and `max_features` — and, critically, **checked every apparent winner on both gender
scopes separately before adopting it**, rather than assuming a female-validated change transfers
to male for free (a repeat of the exact caution this doc's "Age as a model feature" section already
demonstrates the value of, §3.7). Two survived that check:
- `RandomForestRegressor`'s `max_features="sqrt"` for `batting_wpa`: female mean correlation
  0.1208 → 0.1260 (paired diff +0.0052, p=0.0024, won all 9/9 fraction/seed comparisons — a real
  effect); male 0.0859 → 0.0850 (paired diff -0.0009, p=0.4871, won only 3/9 — statistically
  indistinguishable from doing nothing). Applied for female only.
- Reweighting the bowling `VotingRegressor` to `weights=[0.7, 0.3]` (favoring HGB) plus widening
  the training-label clip to (0.02, 0.98): female paired diff +0.0028 (p=0.0033, won 8/9), male
  +0.0064 (p=0.0000, won 9/9 — the cleanest result in the whole search). Generalized cleanly across
  genders, applied unconditionally.

**Label winsorizing before fitting** (`TARGET_CLIP_QUANTILES`, applied only to *training* labels, never to evaluation labels):
```python
TARGET_CLIP_QUANTILES = {"batting_wpa": (0.05, 0.95), "bowling_wpa": (0.02, 0.98)}
```
Batting's 5th–95th clip is unchanged from the original tuning round. Bowling's clip was originally
the more aggressive (0.10, 0.90) — the reasoning at the time being that its fatter-tailed per-match
WPA distribution needed more protection against dominating the fit — but the later live search
above found that reasoning had overshot: a milder (0.02, 0.98) clip (paired with the `weights=[0.7,
0.3]` reweighting) measurably beat the (0.10, 0.90) version on both gender scopes. The originally
plausible-sounding "more aggressive clip for the fatter-tailed target" intuition wasn't wrong in
direction, just in degree — checked and corrected by the same real-backtest discipline this
project applies everywhere else, not re-derived from first principles.

**Train/test split used *inside* `train()` — for reporting only, not model selection.** This is a subtle but important distinction: `train()` does a plain **random** 80/20 split (`sklearn.model_selection.train_test_split(X, y, test_size=0.2, random_state=42)`), gated to only run if at least 50 rows exist, purely to compute and persist `holdout_mae`/`holdout_r2` in the saved metadata for visibility. That split's probe model is then **discarded** — the actual shipped model is re-fit on **100% of the available data** (`model.fit(X, _clip_target(y))`) right after, since once a train/test split has told you how good the model family is expected to be, there's no reason to withhold real data from the final production model. (The *real*, decision-driving evaluation — the one used to compare model families and pick hyperparameters — is the **temporal** holdout in `evaluate/backtest.py`, described in §3.4, not this internal random split.)

**What "training" does, end to end (`train()` in `recommend/train.py`):**
1. Build the leakage-safe feature table (`features/historical.py::build_training_table`) for the given `(format, gender)`.
2. For each target (`batting_wpa`, `bowling_wpa`): fit the model as above, compute the internal random-split holdout metrics, then refit on all data.
3. Persist each fitted model with `joblib.dump(model, artifacts_dir / f"model_{target}.joblib")`, into a directory scoped by `(format, gender)`: `artifacts/player_recommendation/{gender}_{format}/` — e.g. `artifacts/player_recommendation/female_T20/model_batting_wpa.joblib`. This scoping is itself a fixed real bug (see §3.9) — models used to be written to one shared flat filename, so training a second `(format, gender)` scope used to silently overwrite the first's models.
4. Persist a `training_metadata.json` alongside it, containing: `format`, `gender`, `trained_at` (an ISO timestamp of *when* training ran — **not** a duration), `n_rows_total`, `date_range` (min/max match date in the training table), the full `features`/`categorical_features` lists used, and per-target `{"n_rows", "holdout_mae", "holdout_r2"}`.

**On training runtime — reported honestly, not invented.** There is **no elapsed wall-clock-time logging anywhere** in `train.py`, `backtest.py`, or `cli.py` — no `print`/`logging` call in the training path reports how long fitting took. The `criiq_models.cli train` command simply pretty-prints the `training_metadata.json` contents (row counts, date range, holdout metrics) once training finishes; `trained_at` is a timestamp of when the run happened, not how long it took. Given the dataset scale (thousands, not millions, of rows — T20I alone is 2,035 female + 3,393 male matches, roughly 22 players' worth of rows each) and `RandomForestRegressor(n_estimators=300, n_jobs=-1)`/depth-limited boosting, actual training time is realistically on the order of seconds to low tens of seconds on ordinary hardware — but this is a reasonable inference from the model sizes and data volume involved, not a number measured or reported anywhere in the codebase, and should be described as such rather than as a confirmed figure.

### 3.4 Why tree ensembles, not linear regression or deep learning

- **Linear regression** assumes every feature's effect is independent and additive; cricket performance is full of interactions (a batter's strike rate matters differently in the death overs than the powerplay) that tree-based models capture automatically via splits, and linear models measurably underperformed in the real comparison notebook.
- **Deep neural networks** need far more data than exists here (thousands, not millions, of match-rows) to avoid overfitting, and add tuning complexity without evidence of benefit on structured/tabular data like this. This matches a very standard, broadly-replicated finding in applied ML: **tree ensembles (gradient boosting, random forests) are usually the strongest choice on small-to-medium tabular data**, while deep learning's advantages show up on unstructured data (images, audio, text) or genuinely massive tabular datasets.
- **Gradient boosting** builds trees sequentially, each new tree fitting the *residual errors* of the ensemble so far — powerful at squeezing out signal, but prone to memorizing noise on a weak target unless constrained (hence `max_depth=2` for bowling-WPA, the weaker of the two targets).
- **Random Forest** builds many trees independently on bootstrap-resampled data and averages their predictions — the averaging step reduces variance (the same statistical logic behind why averaging many independent measurements gives a more stable estimate than trusting any single one), at the cost of not correcting for other trees' mistakes the way boosting does.

### 3.5 Evaluation — exact metrics, exact formulas, and how the temporal holdout works

**File:** `evaluate/backtest.py`. This is the evaluation that actually drives model/hyperparameter decisions — separate from, and more rigorous than, the internal random 80/20 split described in §3.3 (which exists only for quick visibility, not decision-making).

**The holdout split is by match *date*, never by row or ball** — because rows from the same match are statistically correlated (a batter's WPA in a given match is entangled with their team's bowlers' WPA in that same match), a random row-level split would leak information between train and test. Instead:
```python
dates = pd.to_datetime(table["date"])
cutoff = dates.quantile(1 - SETTINGS.backtest_test_fraction)   # backtest_test_fraction = 0.2
train_df, test_df = table[dates < cutoff], table[dates >= cutoff]
```
The cutoff is the date at the **80th percentile** of all match dates — everything before it trains the model, everything on/after it is held out for evaluation. This directly mimics the real deployment scenario: predicting future matches from past ones.

**The model evaluated is the exact same model family and hyperparameters used in production** — `backtest.py` imports `_make_model`/`_clip_target` directly from `recommend/train.py` rather than reimplementing anything, so a reported holdout number is guaranteed to reflect what's actually shipped, not a stand-in.

**Four metrics are computed per target, exact formulas:**

1. **MAE (Mean Absolute Error):**
   ```
   MAE = mean(|prediction - actual|)
   ```
   In the same units as the target itself (raw WPA) — directly interpretable as "how far off is a typical prediction."

2. **Baseline MAE (mean-predictor baseline):**
   ```
   baseline_MAE = mean(|actual - train_set_target_mean|)
   ```
   The error you'd get by ignoring every feature and just always predicting the training set's average WPA. This is the crucial sanity-check number — a model that can't beat this baseline isn't actually learning anything useful from the features, it's just producing an expensive way to approximate the average. (The project's own "Known Limitations" section honestly reports that batting-WPA MAE only barely beats this baseline — 0.082 vs. 0.081 — which is why *correlation*, not MAE, is treated as the more informative metric for this particular ranking task; see point 3.)

3. **Pearson correlation** between predicted and actual values:
   ```
   corr = np.corrcoef(pred, actual)[0, 1]
   ```
   This measures whether predictions *rank* players correctly relative to each other, which matters more for a selection/ranking use case than raw absolute error does — two metrics can disagree (the project found the mean-predictor baseline has the *lowest* MAE for both targets, yet correlation is what actually distinguishes a useful model, since a mean-predictor's correlation with anything is exactly 0).

4. **Top-quartile hit-rate within match:**
   ```python
   for each match:
       pred_top25   = players with predicted WPA in the match's own top 25%
       actual_top25 = players with actual WPA in the match's own top 25%
       hit_rate_this_match = |pred_top25 ∩ actual_top25| / |actual_top25|
   report = mean(hit_rate_this_match across all held-out matches with ≥4 players)
   ```
   This directly measures the practically relevant question — "of the players who actually turned out to have the best match, how many did the model also flag as its top picks *for that specific match*" — rather than an abstract error number across the whole dataset.

**Real reported numbers** (from the project's own backtest output, default 0.2 split, current DB
snapshot, both gender scopes): batting-WPA female MAE 0.095 vs. baseline 0.096, correlation
**0.122**, top-quartile hit-rate **35.1%**; male MAE 0.089 vs. baseline 0.090, correlation 0.093,
hit-rate 31.1% (both vs. a random ~25% baseline for picking 1-in-4); bowling-WPA female MAE 0.077
vs. baseline 0.078, correlation **0.076**, hit-rate **26.9%**; male MAE 0.070 vs. baseline 0.071,
correlation **0.073**, hit-rate 25.2%. (Earlier snapshots reported different absolute numbers as
the live DB has grown — the tuning-history *deltas* below, each measured within one fixed snapshot,
are the numbers that actually drove each decision.)

**Net effect of the tuning process** (depth-limiting → winsorizing → ensembling → reweighting +
re-clipping, each validated across a repeated-holdout protocol described in §3.3): within the most
recent tuning round alone, bowling-WPA correlation moved **female 0.075 → 0.076, male 0.068 →
0.073**; batting-WPA (the `max_features="sqrt"` change, female-only) moved **female 0.111 →
0.122**, male unchanged — genuine, checked improvements, but honestly reported as modest in
absolute terms for bowling. The project's own stated reason a much larger jump isn't realistic:
per-match cricket outcomes are inherently high-variance (one dropped catch or one hat-trick swings
a single match's WPA hugely), so a materially stronger model would likely need richer raw signal
(pitch/conditions data, true delivery type, a bowler's specific plan for a specific batter) rather
than further tuning of the existing feature set.

### 3.5b Learning-to-rank as an alternative — tried, evaluated, rejected

**File:** `evaluate/rank_backtest.py`. Since XI selection is fundamentally a *ranking* task ("who are the best 11"), a natural alternative to two independent regressions is a model trained directly to rank — `LightGBM`'s `LGBMRanker`, using the **LambdaRank** objective (a pairwise ranking loss that directly optimizes the *ordering* of items within a group, rather than each item's absolute predicted value).

**Exact hyperparameters:**
```python
LGBMRanker(
    objective="lambdarank",
    n_estimators=300,
    max_depth=6,
    learning_rate=0.05,
    random_state=42,
    verbosity=-1,
)
```

**Label construction — a single graded relevance label per player-match**, since a ranker needs one ordering criterion, not two separate targets:
```python
combined = batting_wpa.fillna(0) + bowling_wpa.fillna(0)
grade = pd.qcut(combined, 5, labels=False, duplicates="drop")   # 5 quantile-based grades, 0 (worst) to 4 (best)
```
`qcut` splits the combined-WPA distribution into 5 equal-sized bins by quantile (not equal-width — this guarantees each grade has roughly the same number of players, which is what a ranking loss expects).

**Fitting**, grouped by match (the ranker needs to know which rows compete against which — you rank players *within* a match, not across the whole dataset):
```python
ranker.fit(train_df[MODEL_FEATURES], train_grades, group=group_sizes_per_match)
```
Same temporal (date-based, 80th-percentile cutoff) holdout as §3.5, guarded to require at least 200 training rows and 50 test rows.

**Metrics — both computed per-match, then averaged:**
- **Top-11 hit-rate:** `|top-11-by-prediction ∩ top-11-by-actual-label| / 11`, per match, then averaged — directly answers "if you picked your XI by this model's ranking, how many of the real top-11 would you actually get."
- **Mean Spearman rank correlation** (`scipy.stats.spearmanr`) between predicted scores and actual labels, per match (skipping matches with fewer than 3 players or no variation in the label), then averaged — measures overall ranking-order agreement, not just the top-11 cutoff.

**Real result — the ranker lost, decisively, to the simpler regression-based approach:** top-11 hit rate **0.626 (regression) vs. 0.579 (ranker)**; Spearman correlation **0.28 (regression) vs. 0.116 (ranker)**. The project's own documented explanation: collapsing batting and bowling WPA into a single blended relevance label throws away the role-specific signal that two independent regressors naturally preserve — a specialist bowler's strong bowling WPA and weak (near-zero) batting WPA average out to a middling combined grade, muddying exactly the distinction the two-regressor approach is designed to keep clean. The ranker is **not** wired into `select_xi` as a result — it's kept as a documented, re-runnable comparison (`criiq_models.cli rank-backtest`) rather than silently discarded, specifically so the comparison can be re-checked if the feature set or labeling approach changes materially. This is a useful real-world lesson: the theoretically more "directly optimized for the task" approach doesn't automatically win — it has to actually be checked against the alternative on real data, which is exactly what happened here.

### 3.6 `importance_score` — a separate, transparent (non-ML) composite formula

Distinct from the learned WPA models, `data-collection/criiq_data/impact.py` computes a fully transparent, hand-specified **importance score** (0–100) per player, used as one input (`standing_part`) to the final recommendation score, not a replacement for WPA:

```
overall_contrib     = (bat_contribution_pct or 0) + (bowl_contribution_pct or 0)
contribution_part   = min(35.0, overall_contrib * 0.9)
winning_part        = 25.0 * (win_pct or 0) / 100
standout_part       = 25.0 * min(1.0, (potm_awards / matches) / 0.12)
wicket_rate_part    = min(7.5, (top_scalps / matches) * 15)
economy_part        = min(7.5, (economical_spells / matches) * 15)
bowling_part        = wicket_rate_part + economy_part
batting_impact_part = min(15.0, (big_innings / matches) * 70)

importance = round(min(100.0,
    contribution_part + winning_part + standout_part
    + bowling_part + batting_impact_part
), 1)
```

where `big_innings` = matches with 30+ runs scored, and `economical_spells` = spells of at least 2 overs (`balls_bowled ≥ 12`) with an economy rate `≤ 6.0`. Each `min(cap, ...)` term is a deliberate ceiling so no single component (e.g., a huge raw contribution share) can dominate the score alone — this is what makes it "transparent": every number a coach sees traces back to one of these named, capped components rather than a black-box prediction. A real calibration fix is documented: before `batting_impact_part` existed, pure batters averaged an importance score of **28.3** versus **50.5** for all-rounders (an unfair, purely structural gap — batters simply had fewer scoring opportunities in the formula), which the new component corrected to **37.85** for pure batters.

### 3.7 Feature leakage-safety, shrinkage, and cross-stream joins

The single most important correctness property of `features/historical.py` is that **every feature for a training row uses only information available strictly *before* that match's date** — rolling recent form, expanding career-to-date average, opponent/venue history *to date*. This is the same discipline as backtesting a trading strategy only on data that would genuinely have been visible at the time: if a model accidentally sees the future during training, it looks great on paper and fails in real deployment, because live predictions genuinely don't have tomorrow's information.

**Domestic-form bridging** uses `pd.merge_asof(direction="backward")` to attach "the most recent domestic form as of this international match's date" onto each international row — the right tool specifically because domestic and international matches are two separate event streams, and a normal `groupby().transform()` (which assumes the joined rows belong to the same group being averaged) doesn't apply across streams. `merge_asof` is the standard technique for exactly this "most recent prior record in another timeline" pattern (the same join used in finance for "most recent stock price as of this trade's timestamp").

**Feature selection was empirical, not intuition-driven** — several plausible-sounding features (bowling dot%/boundary% metrics, player age, a coarse pace/spin category) were tried and *explicitly rejected* because repeated real holdout tests showed they didn't help or actively hurt prediction quality, and were removed from the model rather than kept "just in case." This is a deliberately disciplined practice: it's easy to convince yourself a clever feature must help; the actual rule followed here is to check and remove anything that doesn't earn its place.

### 3.8 The complete feature list (`MODEL_FEATURES`)

Every feature fed to both regression models, grouped by category (`features/schema.py`). `MODEL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES`; targets are `["batting_wpa", "bowling_wpa"]`.

**Career-to-date** (expanding mean over every prior match, computed strictly before the current match's date):
- `career_matches` — running count of prior matches
- `career_bat_contribution_pct`, `career_bowl_contribution_pct`
- `career_bat_sr` (career batting strike rate), `career_bowl_economy`
- `career_batting_wpa`, `career_bowling_wpa`
- `career_bowl_wickets_per_match` — masked to only matches where `balls_bowled > 0` before averaging, specifically because `player_match_impact.wickets` is stored as `0` (not `NULL`) for matches a specialist batter didn't bowl in at all; without the mask, the feature would be diluted toward zero for anyone who mostly bats.

**Recent form** (recency-weighted rolling mean over the last `form_window_matches=15` matches, decay factor `form_recency_lambda=0.9` — more recent matches count more, older ones fade out; always shifted so the current match is never included in its own feature):
- `form_bat_contribution_pct`, `form_bowl_contribution_pct`
- `form_bat_sr`, `form_bowl_economy`
- `form_batting_wpa`, `form_bowling_wpa`
- `form_bowl_wickets_per_match`

**Opponent-to-date** (expanding mean restricted to prior matches against this specific opponent, shrunk toward the career-wide baseline when sparse — §5.1's formula):
- `vs_opp_matches`, `vs_opp_bat_contribution_pct`, `vs_opp_bowl_contribution_pct`, `vs_opp_win_pct`

**Venue-to-date** (same idea, restricted to prior matches at this specific venue, same shrinkage treatment):
- `venue_matches`, `venue_bat_contribution_pct`, `venue_bowl_contribution_pct`

**Domestic form** (bridged from the separate `team_type='club'` event stream via `merge_asof`, shrunk toward international career WPA with the sample size capped at `domestic_form_max_effective_matches=10` — §0.4):
- `domestic_form_matches`, `domestic_form_batting_wpa`, `domestic_form_bowling_wpa`

**Categorical (one-hot encoded):**
- `role_bucket` — batter / bowler / all-rounder / keeper, from `player_role_final.primary_role`, falling back to a mapped `player_registry.role` when unset.

**Explicitly tried and rejected** (confirmed by real backtest ablation to make predictions *worse* or add no measurable value, and therefore removed rather than kept speculatively): `bowl_dot_pct`, `bowl_boundary_pct`, `bowl_strike_rate` (bowling containment metrics — correlation dropped from 0.103 to as low as 0.088 individually), `age_years` (helped batting by an amount indistinguishable from noise, measurably *hurt* men's targets), `bowl_style_bucket` (a coarse pace/spin category — no measurable difference once a bowler's own historical economy/wicket-rate is already a feature). These are still computed and shown as descriptive-only narrative color in `explain` output — just never fed back into a prediction.

### 3.9 All training-relevant configuration values, in one place

**File:** `criiq_models/config.py`, a frozen (immutable) `Settings` dataclass:

| Setting | Default | What it controls |
|---|---|---|
| `min_matches_for_model` | `10` | Below this many career matches, the trained regressor is **skipped entirely** in favor of a shrinkage-based fallback (§3's `model_part`, cold-start handling) — a 3-match player's rating is not trusted to a model trained mostly on established players. |
| `form_window_matches` | `15` | How many most-recent matches count toward "recent form" features. |
| `form_recency_lambda` | `0.9` | Exponential decay rate for weighting recent-form matches — more recent matches count more. |
| `shrinkage_prior_matches` | `8` | The `k` constant in the general shrinkage formula (§5.1) for opponent/venue features — "how many real matches of evidence it takes to trust the specific number as much as the broad prior." |
| `secondary_discipline_weight` | `0.4` | An all-rounder's *secondary* discipline (e.g. bowling, for a batting-primary all-rounder) contributes only 40% as much to `model_part` as their primary discipline — reflects that XI selection cares most about a player's best skill, with secondary skills as a real but smaller bonus. |
| `wpa_scale` | `450.0` | Converts a raw WPA prediction (naturally tiny — median ≈0, 95th percentile ≈+0.046, 99th ≈+0.086, max ≈+0.13 across real players with 10+ matches) into `model_part` points on a 0–45 scale. Calibrated (not blindly guessed) so a genuinely elite average WPA (≈0.09, near the real 99th percentile) lands close to, but doesn't exceed, the 45-point cap. |
| `sr_penalty_cap` / `sr_penalty_scale` | `6.0` / `20.0` | Cap and scale for the strike-rate soft penalty (§3's `strike_rate_part`) — how much a below-par career strike rate can cost, before the game-awareness offset. |
| `min_matches_for_model` combined with `career_matches` | — | Also drives the cold-start `confidence` multiplier: `min(1.0, career_matches / min_matches_for_model)` — a player with 3 career matches gets at most 30% of the fallback model_part, linearly scaling up to full trust at 10 matches. |
| `domestic_form_max_effective_matches` | `10` | Caps the sample size fed into the domestic-form shrinkage formula, so no volume of domestic-league matches alone can fully override the international-career prior. Chosen via a real grid search over `{5, 10, 15, 20}` on the ~220-domestic-player-scale dataset; the codebase's own comment notes the differences across this grid were within noise at current data volume, so 10 was kept as a reasonable middle value rather than a decisively-winning one. |
| `backtest_test_fraction` | `0.2` | The temporal holdout fraction used by both `evaluate/backtest.py` and `evaluate/rank_backtest.py` (§3.5) — the most recent 20% of matches by date are held out. |
| `random_state` | `42` | The single seed value used everywhere randomness needs to be fixed for reproducibility: `RandomForestRegressor`, `HistGradientBoostingRegressor`, `LGBMRanker`, and the internal random `train_test_split` probe in `train.py`. |
| `xi_size` | `11` | The MILP's `Σx_i = 11` constraint (§1). |
| `min_batting_capable` / `min_bowling_capable` | `5` / `5` | The MILP's role-count constraints. |
| `min_keepers` | `1` | The MILP's keeper constraint (soft — degrades to `min(setting, available)` when the pool has no keeper data). |
| `min_openers` | `2` | The MILP's opener constraint (same soft-degradation behavior). |
| `pool_size` | `20` | How many top-scoring candidates are shown in the display shortlist (the MILP itself always runs over the *full* candidate pool, never just this display slice — running it on a truncated pool was a real, fixed bug, since a required keeper/opener can rank outside the top 20 by raw score). |

### 3.10 How the trained model's predictions actually flow into the MILP — the exact mechanical link

This is the piece that connects §1 (MILP) and §3 (trained regressors) into one system, and it's worth tracing precisely since it's easy to assume there's some complex hand-off — there isn't; the link is a single number per player.

**Step 1 — the regressors produce a raw WPA prediction** (`recommend/score.py`). For a live-scoring call, the exact same `MODEL_FEATURES` used in training are recomputed for the *current* context (this team, this opponent, this venue, as of today) and fed into the persisted `joblib` models:
```python
row = pd.DataFrame([{f: feats[f] for f in MODEL_FEATURES}])
predicted_batting_wpa = float(self.models["batting_wpa"].predict(row)[0])
predicted_bowling_wpa = float(self.models["bowling_wpa"].predict(row)[0])
```
This only happens if the player clears the cold-start gate (`career_matches >= min_matches_for_model`); otherwise a shrinkage-based fallback substitutes for the missing model prediction (§4.3's shrinkage formula, applied to `career_batting_wpa`/`career_bowling_wpa` toward a league-wide prior).

**Step 2 — the raw prediction(s) become `model_part`, a 0–45-point score component:**
```python
active_wpa = []  # only disciplines this player's role_bucket actually supports
if batting_capable and predicted_batting_wpa is not None:
    active_wpa.append(predicted_batting_wpa)
if bowling_capable and predicted_bowling_wpa is not None:
    active_wpa.append(predicted_bowling_wpa)
active_wpa.sort(reverse=True)

primary = active_wpa[0] if active_wpa else 0.0
secondary_bonus = sum(active_wpa[1:]) * secondary_discipline_weight   # 0.4
model_part = min(45.0, (primary + secondary_bonus) * wpa_scale)       # wpa_scale = 450.0

if not model_applied:   # cold-start case
    confidence = min(1.0, career_matches / min_matches_for_model)
    model_part *= confidence
```
A pure batter's `model_part` comes entirely from `predicted_batting_wpa`; an all-rounder's comes from their *stronger* discipline at full weight plus their weaker discipline at 40% weight — deliberately rewarding genuine dual-skill value without letting it fully double-count.

**Step 3 — `model_part` is summed with every other score component into one final number** (`score.py`):
```python
total = round(max(0.0, min(100.0,
    model_part + matchup_part + phase_fit_part
    + standing_part + risk_part + strike_rate_part
)), 1)
# team_need_part is added afterward, in score_many(), on top of the already-clamped total:
player["score"] = round(min(100.0, player["score"] + team_need_bonus), 1)
```
where `matchup_part` (±8 aggregate dismissal history + ±5 style edge + ±8 bowling-side matchup, each independently capped), `phase_fit_part` (0–8, phase specialization), `standing_part` (0–20, from the separate transparent `importance_score` formula, §3.6 — note this is a *different* signal from the learned WPA models, deliberately combining a learned component with a hand-specified one), `risk_part` (≤0, age/inconsistency/inactivity penalties), and `strike_rate_part` (≤0, the game-awareness-offset soft penalty) round out the additive formula, clamped to `[0, 100]`.

**Step 4 — this single `score` number becomes the MILP's objective coefficient, with zero further transformation:**
```python
scores = np.array([p["score"] for p in ranked], dtype=float)
result = milp(c=-scores, constraints=[...], bounds=Bounds(0, 1), integrality=np.ones(n))
```
`selection/optimize.py` does **no independent scoring or blending of its own** — it simply negates each player's already-finished `score` (because `scipy.optimize.milp` minimizes by convention, so maximizing `score` means minimizing `-score`) and hands the resulting vector straight to the solver as `c`. Everything upstream of this one line — the trained regressors, the shrinkage fallbacks, the hand-specified `importance_score`, the matchup/phase/risk adjustments — exists purely to produce that single per-player number; the MILP's only job is to pick the constrained subset of 11 that maximizes the sum of whatever numbers it's handed. This is a clean separation of concerns: *scoring* (how good is this player, for this context) is entirely the responsibility of `recommend/score.py` and the models it calls; *selection* (which valid combination of scored players is best) is entirely the responsibility of the MILP in `selection/optimize.py`, and neither module needs to know how the other does its job.

### 3.11 Explaining *why* — SHAP for the WPA predictions, baseline-comparison for the GA outputs

Everything in §3.1–§3.10 produces a *number* (a WPA prediction, a composite score, an XI). Two further techniques — added later, both purely explanatory, neither changing what gets picked or simulated — answer "why that number," for the two different kinds of "number" this project produces: a **learned model's prediction**, and a **search algorithm's chosen solution**.

**A. SHAP (SHapley Additive exPlanations) — for the WPA regressors' predictions.** SHAP is a formal, game-theoretically-grounded feature-attribution method, based on the Shapley value from cooperative game theory: imagine building up a prediction feature-by-feature, in every possible order, and averaging each feature's marginal effect across all those orderings. The result is an *exact, additive* decomposition — `base_value + Σ(each feature's contribution) = the actual prediction`, not an approximation or a plausible-sounding story. This is what makes SHAP different from `explain.py`'s existing plain-English narrative (§ elsewhere in this doc): the narrative is a human-readable *summary* of what's known about a player; SHAP is a mathematically exact *attribution* of one specific number a trained model produced.

**Why SHAP, and not a simpler method (e.g. just reading off feature importances, or a linear-regression-style coefficient)?** Global feature importances (e.g. "career_matches matters most on average across all players") don't answer "why did *this specific player* get *this specific* predicted WPA" — a feature can matter a lot on average and yet contribute almost nothing for one particular player whose value on that feature happens to sit right at the model's baseline. SHAP is computed *per prediction*, which is exactly the granularity a coach asking "why is this player rated this way" needs. Tree-based models like the ones this project uses also make an *exact* SHAP computation tractable (`TreeExplainer`) rather than requiring an expensive approximation — a happy match between the technique and the model family already chosen for other reasons (§3.3–3.4).

**The mechanical complication, and why it needed real engineering, not just calling one library function:** the shipped `bowling_wpa` model is a `VotingRegressor` blending two *differently-shaped* sub-models — a `RandomForestRegressor` inside a `Pipeline` (with a `OneHotEncoder` step), and a `HistGradientBoostingRegressor` that encodes its one categorical feature natively, with no separate encoding step to introspect. SHAP's fast, exact tree method (`TreeExplainer`) works directly on the first; the second needs the slower, model-agnostic **Permutation explainer** (repeatedly perturb each feature against a reference "background" sample, and measure how much the prediction moves) instead — which itself needs a background sample, hence `train.py` now persists one (a random slice of the training table, `SETTINGS.shap_background_size=100` rows) as a real training artifact. The two sub-models' SHAP values are then combined using the *exact same averaging weights* the `VotingRegressor` itself uses for its predictions, so that the combined SHAP values sum to the combined model's actual combined prediction — preserving the "this is an exact decomposition, not an estimate" property all the way through a blended model, not just through either half alone.

**Worked example, in spirit:** for a specific player scored against a specific opponent, SHAP might report `base_value = 0.01` (the model's prediction if it knew nothing about this player beyond the training population's average), then `career_batting_wpa: +0.04`, `form_bat_sr: +0.02`, `vs_opp_bat_contribution_pct: -0.01`, ... summing to the model's actual predicted WPA. A coach reading this learns not just "the model rates her at X" but "her recent strike-rate form is what's actually driving that rating up, while her history against this specific opponent is pulling it down slightly" — genuinely actionable, and mathematically exact rather than a guess.

**B. Baseline-comparison + sensitivity testing — for the GA-optimized batting order and bowling rotation.** SHAP doesn't apply here, because a genetic algorithm's output isn't a single model's prediction to decompose — it's a *search result* (a specific order/rotation chosen from a huge combinatorial space). The natural explainability question for a search result is different: **"how much better is this than the obvious non-AI choice, and how sensitive is it to small changes?"** `simulate/lineup_explain.py` answers both, directly and empirically, by re-running the *exact same simulation-based fitness metric* the GA itself optimized (§2's `_fitness`/`_batting_metric`/`_bowling_metric`), rather than inventing a new proxy metric that might not actually match what the GA cared about:

- **Baseline comparison**: build the simple, defensible thing a coach might do by hand without a GA — batters sorted by strike rate within each role band; bowlers given an even split of overs — and measure it with the identical metric. Report the gap (`improvement_over_baseline`) as a real, checked number.
- **Sensitivity testing (a lightweight counterfactual)**: for the batting order, swap every *adjacent pair within the same role band* and re-measure — this directly answers "was swapping these two specific batters actually correct, and by how much," surfacing the single riskiest micro-decision (`most_costly_adjacent_swap`) rather than treating the whole order as an unexaminable black box.
- **Contingency heuristics** (batting order only): a simple, explicitly-labelled-as-heuristic (not re-simulated) suggestion for who to promote on an early collapse (lowest strike rate — the most patient rebuild option) vs. a chase running short on time (highest chasing strike rate — the most direct accelerant) — a small, honest "if X happens, consider Y" note rather than a false claim of having simulated every possible in-match contingency.

**Why this two-technique split, rather than one universal "explainability" method for everything:** the two outputs are fundamentally different kinds of thing — a regression model's prediction (SHAP's natural domain) versus a search algorithm's chosen solution among many valid ones (where "why" is better answered by "compared to what, and how fragile is it" than by a feature attribution, since a GA's choice doesn't decompose into additive per-feature contributions the way a regression prediction does). Using the technique that actually fits each output's shape, rather than forcing one method to cover both, is the same "right tool for the shape of the problem" principle this whole document has followed since §0.

---

## 4. Match Simulation — Monte Carlo Simulation over Empirical Probability Distributions

**Files:** `simulate/engine.py`, `simulate/outcomes.py`, `data-collection/criiq_data/winprob.py`

### 4.1 What "Monte Carlo simulation" means, formally

Monte Carlo simulation is a technique for estimating a quantity that's too complex to compute in closed form, by instead **repeatedly sampling the random process it depends on and looking at the distribution of results**. Formally: if you want `E[f(X)]` (the expected value of some outcome `f` under a random process `X`) but can't derive it analytically, you instead draw many samples `X_1, X_2, ..., X_N` of the process, compute `f(X_i)` for each, and estimate `E[f(X)] ≈ (1/N) Σ f(X_i)`. As `N` grows, this average provably converges to the true expected value (the **Law of Large Numbers**).

**Applied here:** a full T20 match involves hundreds of sequential, mutually-dependent random events (each ball's outcome depends on who's batting, who's bowling, the current phase, score, wickets, free-hit status...). There is no clean formula for "probability team A wins" given all of this — so instead of solving for it analytically, `simulate_innings`/`simulate_match` literally *play out* a random match (sampling one outcome per ball from the model in §4.2) and repeat this hundreds of times (`--n-simulations`), then report the resulting distribution of scores/results.

**Analogy:** if you want the odds of winning at a complex casino game, you can either derive the exact combinatorial probability by hand (hard, error-prone for a complicated game with lots of rules) — or just play the game a million times in simulation and count how often you win. Criiq does the second, for cricket matches.

### 4.2 What an "empirical distribution" is, and why it's used here instead of a textbook distribution

A **probability distribution** describes how likely each possible outcome is. There are two ways to get one:

- **Parametric distribution:** assume outcomes follow a known mathematical family (e.g., "runs per over follow a Poisson distribution with rate λ") and estimate just its parameters from data. Compact, but only as accurate as the assumption is correct.
- **Empirical distribution:** *don't* assume any particular family — just use the **actual observed frequencies** in real data as the probability distribution directly. If, out of 10,000 real deliveries in the death overs, 620 went for a wicket, the empirical wicket probability for that bucket is simply `620/10000 = 6.2%` — no formula, just the historical count.

Criiq's ball-outcome model (`outcomes.py`) is built this way, deliberately: it classifies real historical deliveries from `deliveries` into exactly one of ten mutually-exclusive outcome buckets — `("0","1","2","3","4","6","wicket","wide","noball","bye")` — separately for each **match phase** (powerplay = overs 1-6, middle = 7-15, death = 16-20 — because real scoring behavior genuinely differs by phase) and each `(format, gender)` scope, and uses the resulting real frequency table as the base probability distribution for simulated deliveries.

**Why empirical, not parametric, here:** cricket scoring is genuinely not well-approximated by simple textbook distributions — six-hitting, for instance, is much more "bursty"/streaky in reality than a memoryless process like Poisson would predict (a batter who's just hit two sixes is not equally likely to hit a third as a random over would suggest — form, field settings, and bowler adjustments all interact). With enough real historical deliveries to make the empirical frequencies reliable (which the dataset has, at 2,000+ international matches plus domestic-league data), using the real observed frequencies directly is more faithful than betting on any particular assumed curve being right.

### 4.3 Per-ball adjustment: shrinkage-based, Bayesian-*flavored* reweighting

The phase-level empirical distribution above is a good *baseline*, but it's the same for every batter/bowler pairing — clearly wrong, since a strong hitter facing a part-time bowler should have meaningfully different odds than a tailender facing a strike bowler. So the baseline gets adjusted **per ball**, for the specific two players involved:

- **Boundary probability** (chance of a 4 or 6) is scaled by:
  ```
  sr_factor   = batter's effective strike rate / league-average strike rate
  econ_factor = bowler's economy / league-average economy
  boundary_scale = clip(sr_factor / max(econ_factor, 0.3), 0.4, 2.5)
  ```
  i.e., a batter striking well above league average, facing a bowler more economical than league average, gets *less* than 1.0× scaling (bowler's control suppresses it); a fast-scoring batter against a leaky bowler gets scaled up — clipped to a sane range `[0.4, 2.5]` so no extreme ratio can produce an unrealistic probability (e.g., a value near 0 or above 1).

- **Wicket probability** is scaled by the bowler's `wickets_per_match` ratio (clipped `[0.3, 2.5]`), then further adjusted by real **head-to-head dismissal history** between that exact batter/bowler pair, but only when there's a minimum sample (**≥6 balls** of real history) — and even then, it's **shrunk toward the phase baseline** rather than trusted outright (formula below).

**Why "Bayesian-flavored":** this per-ball adjustment is conceptually a simplified, interpretable stand-in for a **Bayesian posterior update** — the general statistical idea of starting from a *prior belief* (here, the phase-level empirical distribution, representing "what we'd expect before knowing anything about this specific matchup") and updating it with *evidence* (the specific batter/bowler's real head-to-head history), where the update's strength depends on how much evidence there actually is. It isn't a full, formally-derived Bayesian model with an explicit likelihood function and posterior distribution — it's a lighter-weight approximation of the same core idea, using an explicit shrinkage formula instead of full Bayesian inference machinery, because the shrinkage formula captures the behavior that actually matters (trust small samples less) without the added complexity/computation cost of a full Bayesian model.

**The shrinkage formula itself**, used throughout the project (`features/common.py::shrink`):

```
shrunk_estimate = (n · observed + k · prior) / (n + k)
```

where:
- `observed` = the specific, possibly-sparse estimate (e.g., this batter's dismissal rate against this exact bowler)
- `n` = how many real observations back that estimate (e.g., number of head-to-head balls)
- `prior` = the broader, more reliable fallback estimate (e.g., the phase-wide baseline dismissal rate)
- `k` = "prior strength," a tunable constant (`shrinkage_prior_matches = 8` in the model-training config; `winprob_shrinkage = 12.0` for the win-probability grid, see §4.4) — effectively "how many real observations would it take to trust the specific estimate as much as the prior."

**Worked numeric example.** Suppose a batter has faced a specific bowler `n = 2` times and been dismissed both times (`observed = 1.0`, i.e. 100% dismissal rate), while the phase-wide baseline dismissal rate is `prior = 0.06` (6%), and `k = 8`:

```
shrunk = (2 × 1.0 + 8 × 0.06) / (2 + 8) = (2.0 + 0.48) / 10 = 0.248
```

So instead of naively believing this batter has a "100% dismissal rate" against this bowler (an absurd claim from only 2 data points), the shrunk estimate is **24.8%** — elevated above the 6% baseline (because the sparse evidence does suggest *something*, and shouldn't be ignored entirely) but nowhere near the raw, tiny-sample 100%. As `n` grows (more real head-to-head balls accumulate), the formula automatically trusts the observed rate more and the prior less — with `n = 100` and the same 6% baseline, `k = 8` would barely move the estimate away from whatever the real 100-ball dismissal rate is.

This exact `(n·observed + k·prior)/(n+k)` formula is mathematically the same family as the classic **Bayesian Beta-Binomial conjugate update** (treating `prior` as a pseudo-count of `k` prior observations blended with `n` real ones) — which is precisely why it's described as "Bayesian-*flavored*": it produces the same qualitative and largely the same quantitative behavior as a formal Bayesian update, via a much simpler, directly-interpretable formula, without needing to carry a full probability distribution over the parameter (a proper Bayesian treatment would track a whole Beta distribution and update it; this tracks only its resulting mean).

### 4.4 The win-probability model — `EmpiricalWinProb`

**File:** `data-collection/criiq_data/winprob.py`

This is the model that both (a) directly powers "what's the win probability right now" displays in the simulator's charts, and (b) is the engine underneath every WPA calculation in §3.1 — every `delta_wp` starts from a lookup into this model.

**Binning (discretizing continuous match state into buckets):** rather than trying to model win probability as a smooth function of continuous score/overs/wickets (which would need a lot more data density to fit reliably), match state is bucketed:
- One over per bin for balls bowled/remaining (`_BALLS_BIN = 6`)
- Wickets clipped to `[0, 10]`
- For a chase (2nd innings): runs-required bucketed in bands of 5, capped at a 30-band index (`_RR_BIN = 5`, `_RR_CAP = 30`)
- For setting a total (1st innings): score bucketed in bands of 10 (`_SCORE_BIN = 10`)

Two keys result: `(balls_remaining//6, wickets, runs_required//5)` for chasing, `(balls_bowled//6, wickets, score//10)` for setting.

**Fitting — empirical win rate per bin, shrunk toward the overall prior:**
```
wp(bin) = (Σ y_bin + α · prior) / (count_bin + α)
```
where `y` is `1` if the batting side went on to win that match, `0` otherwise, `prior` is the raw overall win rate for chase/set situations (mean of the win/loss label across all data of that type), and `α = winprob_shrinkage = 12.0`. This is the exact same shrinkage family as §4.3, applied here to *bins of match states* instead of *batter-bowler pairs* — again, bins with few real historical observations get pulled strongly toward the sensible overall prior, while bins with abundant data are trusted almost entirely on their own empirical rate.

**Backoff for missing bins:** four grids are actually fit — a fine 3-dimensional grid and a coarser 2-dimensional grid, separately for chasing and setting. A lookup first tries the fine grid; if that exact bin has too little/no data, it backs off to the coarser grid; if even that's missing, it falls back to the raw prior. This guarantees a sensible answer always exists, even for rare match states (e.g., "9 wickets down needing 40 off 3 balls" — a state real data may barely cover).

**Scope:** one model is fit **per `(format, gender)`**, never blended — a men's T20I win-probability curve and a women's one are allowed (and expected) to differ, since real scoring rates/patterns differ enough between the two that pooling them would bias both.

**Evaluation methodology — held out by match, not by ball:** balls from the same match are never split across train/test (that would leak information, since consecutive balls in one match are highly correlated) — `zlib.crc32` hashes each match ID to deterministically assign roughly 20% of *matches* (`winprob_test_fraction = 0.2`) to the test set, whole matches at a time.

**Metrics — Brier score and log-loss**, both standard for evaluating probabilistic predictions:
```
Brier score = mean( (predicted_probability - actual_outcome)^2 )
Log-loss    = -mean( y·log(p) + (1-y)·log(1-p) )
```
Both are **lower-is-better** measures of how well-calibrated a probability estimate is (not just whether the predicted winner was right, but whether a "70% win probability" call actually wins about 70% of the time across many such calls). Real, confirmed results on the live database: **female Brier 0.1557 vs. a naive constant-prior baseline's 0.2447** (93,714 held-out test balls); **male Brier 0.1727 vs. baseline 0.25** (145,372 held-out test balls) — in both cases a meaningfully better (lower) score than just always guessing the overall average win rate, confirming the model is genuinely learning from match state, not just reproducing the base rate.

### 4.5 Rules-faithful simulation, not just plausible-looking

`engine.py` encodes the actual **Laws of Cricket**, not an approximation: a bowler capped at 4 overs and barred from bowling consecutive overs (Law 17.6 / ICC Playing Conditions 13.9.1), a free hit suppressing wicket probability entirely (only run-out-type dismissals are legally possible off a free hit), wides/no-balls replayed with a 1-run penalty, byes/leg-byes counted as a legal ball but never credited to the batter or debited to the bowler, and — because T20 internationals don't end in a draw — a tied second-innings score triggers one or more actual **Super Overs**, repeating on a further tie, up to a generous, essentially-never-reached cap purely to bound worst-case computation time rather than reflecting a real rule.

**Bowler auto-scheduling** (when no explicit rotation is supplied) prefers whichever available bowler has the best real, historical economy rank *for the current over's specific phase* — modeling a real captain saving their best death-overs bowler for the death overs, rather than a naive round-robin — but only when there's genuine squad depth beyond the bare 5 bowlers minimum needed to legally cover 20 overs; with exactly 5, there's no slack to be selective, and the engine correctly falls back to simple least-used-first scheduling to avoid risking a legal deadlock. A real verification example from the project: a simulated Australia rotation had its two new-ball bowlers open, its best two middle-overs-economy bowlers share almost the whole middle phase, and its best death-overs bowlers close it out — matching real-world captaincy patterns rather than an arbitrary spread.

---

## 5. Supporting mathematical/statistical concepts, collected in one place

These recur across almost every module above, so it's worth having them defined once, clearly, with the exact formula and a worked example each.

### 5.1 Shrinkage estimation

**Definition:** when a specific, narrow estimate is based on very little data, blend it toward a broader, more reliable estimate — trusting the specific estimate more as its sample size grows.

**Formula:** `shrunk = (n · observed + k · prior) / (n + k)`.

**Why it works (intuition, not just formula):** with very little data, "observed" is dominated by noise — 2 coin flips landing heads twice doesn't mean the coin is double-headed. Shrinkage is mathematically related to the classical **James-Stein estimator** result in statistics (a famous, historically counter-intuitive finding that blending multiple separate small-sample estimates toward a common average produces *more accurate* estimates on average than trusting each one in isolation, even though it feels like "diluting" real, specific data). Used here for: batter-vs-bowler dismissal rates (§4.3), venue/opponent form (§3.7), domestic form (§0.4), and win-probability bins (§4.4) — always the same shape of problem: "I have a specific but sparse number, and a broader but less specific number — combine them sensibly."

### 5.2 Empirical (non-parametric) probability distributions

**Definition:** using the real, observed frequency of each outcome directly as its probability, instead of assuming the outcomes follow some named mathematical distribution (Normal, Poisson, Binomial, etc.) and fitting only that distribution's parameters.

**When to prefer it:** when you have enough real data for the raw frequencies to be reliable, and no strong reason to believe outcomes follow a specific tidy mathematical shape. Cricket ball outcomes qualify on both counts — enough historical deliveries exist, and real scoring patterns (streaky six-hitting, phase-dependent risk-taking) don't cleanly match standard textbook distributions.

### 5.3 Winsorizing

**Definition:** clip extreme values to a chosen percentile bound (e.g., the 10th and 90th percentiles) before further use, rather than deleting them or leaving them untouched. Used only on *training* labels for the bowling/batting WPA models (§3.5) — evaluation is always against the real, unclipped values, so accuracy is measured honestly, but the model isn't trained to chase rare freak outliers (a hat-trick over) that would otherwise dominate its error signal disproportionately to how often they actually happen.

### 5.4 Percentile / standard-deviation-based scaling

**Definition:** calibrate a scoring bonus/penalty's scale against the *actual observed spread* (standard deviation) of the underlying real metric, rather than picking an arbitrary constant. Used for e.g. "how strong is this squad's death-bowling relative to a benchmark" (`team_need.py`) — calibrated so that "one standard deviation above the benchmark" reliably means "a real, noticeable strength" and "two standard deviations above" means "genuinely exceptional," regardless of which raw metric is being scored, since different metrics naturally have very different raw scales. A real documented bug: an early version's scale was roughly 6× too aggressive and hit its point cap for nearly every player in a pool regardless of actual relevance — caught by manually inspecting real output, not by a metric, and fixed by recalibrating against the metric's real standard deviation (≈0.065–0.078 for combined phase-WPA).

### 5.5 Ensembling (model averaging)

**Definition:** combine multiple independently-trained models' predictions (typically by averaging) rather than relying on a single model. If each model's errors are at least partly independent of the others', averaging cancels out some of each individual model's mistakes — the same statistical logic behind why an average of many people's independent estimates (the classic "guess the number of jellybeans in a jar" demonstration) tends to beat most individual guesses, sometimes called the "wisdom of crowds" effect. Used for the bowling-WPA `VotingRegressor` (§3.3/3.5), blending a boosted-tree model and a random forest that make somewhat different kinds of errors.

### 5.6 Brier score and log-loss (probability calibration metrics)

**Formulas** (repeated here for reference, from §4.4):
```
Brier score = mean( (p - y)^2 )
Log-loss    = -mean( y·log(p) + (1-y)·log(1-p) )
```
where `p` is a predicted probability (e.g., "70% chance the batting side wins") and `y ∈ {0,1}` is the actual outcome. Both measure not just whether a prediction "picked the right side," but whether the *stated confidence* was trustworthy — a model that says "70%" should be right about 70% of the time across many such calls, not just be directionally correct. Lower is better for both; both are standard metrics for evaluating any probabilistic classifier, not specific to cricket.

### 5.7 `merge_asof` — point-in-time joins across separate event streams

**Definition:** a "join" operation that, for each row in a primary table, finds the most recent matching row in a secondary table **at or before** that row's timestamp — rather than an exact-key join. Used to attach "most recent domestic form as of this international match's date" onto international training rows (§0.4/§3.7), because domestic and international matches are two genuinely separate event streams that can't be aggregated together with an ordinary `groupby`.

---

## 6. Summary — every choice, one line each

| Component | Technique | One-line justification |
|---|---|---|
| Data source | Cricsheet (ball-by-ball, T20I + 7 women's domestic T20 leagues) | Free, structured, legally scraped; ESPNcricinfo blocks scraping so it's used only as best-effort enrichment. |
| Domestic vs. international stats | Kept in separate tables, joined only via a shrunk feature | Prevents domestic-league scale/quality differences from corrupting international career averages. |
| XI selection | MILP (`scipy.optimize.milp`) | Objective and constraints are genuinely linear — solve exactly, don't approximate. |
| Bowling rotation | Genetic Algorithm + deterministic repair | Objective is a black-box simulator output; legality is sequence-dependent — GA search + repair-not-penalize handles both. |
| Batting order | Genetic Algorithm + order crossover (OX) | Same GA rationale; OX specifically preserves permutation validity, unlike naive crossover. |
| Batting/Bowling WPA prediction | Random Forest / HistGB + VotingRegressor ensemble, per-target-chosen | Tree ensembles are the standard strong choice for small tabular data; the specific model per target was chosen from real holdout comparisons, not assumed. |
| `importance_score` | Transparent, hand-specified, capped-component formula | A fully explainable, non-black-box complement to the learned WPA models. |
| Ball outcome modeling | Empirical (non-parametric) phase-level distributions + Bayesian-flavored shrinkage adjustment | Real historical frequency is more faithful than an assumed textbook distribution; shrinkage avoids overreacting to tiny-sample matchup history. |
| Win probability | Binned empirical model + shrinkage + coarse-grid backoff | Same shrinkage principle, applied to discretized match-state bins with graceful degradation for rare states. |
| Match outcome | Monte Carlo simulation | The system is too interaction-heavy for closed-form probability; sampling the process repeatedly (Law of Large Numbers) is the standard approach. |
| Feature engineering | Point-in-time reconstruction + shrinkage + `merge_asof` for cross-stream joins | Prevents data leakage (seeing the future) and prevents overconfidence from sparse subgroups. |
| Model/feature choice | Always validated by repeated (multi-seed, multi-split) real holdout backtests | Protects against "looks good on one lucky split" — the single most common way ML projects fool themselves. |
| Explaining a WPA prediction | SHAP (TreeExplainer + Permutation explainer, weighted-combined) | Exact, additive per-feature attribution for *this* prediction — matches the model family already chosen, unlike a global-only importance ranking. |
| Explaining a GA's chosen order/rotation | Baseline comparison + adjacent-swap sensitivity + heuristic contingency plan | A search result doesn't decompose into feature attributions like a regression does — "compared to what, and how fragile" is the right question for a chosen solution among many valid ones. |

---

## 7. Further reading map

- **MILP / integer programming:** any operations-research text's chapter on "0/1 knapsack" and "assignment problems" — XI selection is a close cousin of both.
- **Genetic algorithms:** the traveling salesman problem is the canonical example used to teach order crossover (OX) — the same technique used here for batting order.
- **Gradient boosting vs. random forests:** both are "ensembles of decision trees," differing in *how* the trees are combined — boosting trains trees sequentially to correct prior errors (reduces bias), random forest averages independently-trained trees (reduces variance).
- **Shrinkage estimation / Bayesian-flavored blending:** search "James-Stein estimator" for the original, mathematically surprising result that motivated this whole family of techniques; "Beta-Binomial conjugate prior" for the formal Bayesian version the shrinkage formula here approximates.
- **Monte Carlo methods:** any intro to "Monte Carlo simulation" in a stats or physics context — the same core idea (sample a random process many times, examine the resulting distribution) applied here to cricket instead of particles or option prices.
- **Brier score / log-loss:** standard topics in any "probabilistic forecasting" or "classifier calibration" reference — the same metrics used to evaluate weather forecasters' probability-of-rain calls.
- **SHAP / Shapley values:** the original game-theory concept (Lloyd Shapley, cooperative games — "how should a coalition's joint payoff be fairly split among its members") repurposed for ML feature attribution; Scott Lundberg's original SHAP paper ("A Unified Approach to Interpreting Model Predictions") is the standard reference for `TreeExplainer` and the Permutation explainer both used here.
- **Real-world validated accuracy** of everything described in this document — not just backtest metrics, but the actual Playing XI recommendation and match simulator tested against genuinely unseen real matches — is reported in `model-training/VALIDATION_REPORT.md`, §11 in particular.

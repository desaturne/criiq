# Criiq — Player Recommendation Engine (`criiq_models`)

The AI module: scores every eligible player for a given (team, opponent, venue)
context and proposes a balanced playing XI, with plain-language reasoning for
every pick. Reads `data-collection`'s SQLite DB
(`../data-collection/data/criiq.db`) **read-only** — this package owns no data
of its own beyond its trained model artifacts. Supports both **women's and
men's T20I** (`format=T20`, `gender=female`/`male`) as first-class, equally-
scored scopes — `gender` is a `--gender` flag/config setting throughout, never
hardcoded, and model artifacts are persisted per `(format, gender)` under
`artifacts/player_recommendation/{gender}_{format}/` so training one scope can
never overwrite another's models. `gender=female` is only the *default* when
`--gender` is omitted. Run `criiq_models.cli train --gender male` (and
`--gender female`) once each after any feature/data change — each scope's
models are trained and persisted independently.

## Setup

```bash
pip install -r requirements.txt
```

## Pipeline

```bash
python -m criiq_models.cli features                 # build + report the leakage-safe training table
python -m criiq_models.cli train                     # fit + persist the two WPA regressors
python -m criiq_models.cli backtest                  # temporal holdout calibration report
python -m criiq_models.cli rank-backtest             # learning-to-rank vs regression comparison
python -m criiq_models.cli teams                     # list known team names
python -m criiq_models.cli recommend --team India --opponent Australia [--venue "Lord's"] [--explain] [--pretty]
python -m criiq_models.cli explain --name "H Kaur" --opponent Australia
python -m criiq_models.cli analyze-xi --team India --opponent Australia --players "S Mandhana,H Kaur,..." [--pretty]

# every command above takes --gender male|female (default female) and --format T20
python -m criiq_models.cli recommend --team India --opponent Australia --gender male --pretty
```

`--venue` takes a ground **name**, fuzzy-matched against `venues.canonical_name`
(`venues.py`), not the raw `venue_id` slug it used to require. A name matching
more than one ground prints every candidate ("did you mean...") instead of
silently guessing one; a name matching nothing falls back to treating the
input as an already-resolved `venue_id` (backward-compatible with scripts
passing the slug directly).

`--pretty` (`recommend/render.py`) renders an actual team sheet instead of
dumping JSON, in two parts (implies `--explain`; nothing is computed
differently, only formatted and, for the shortlist, given individual
reasoning too):

1. **Roster, split into three role pools** (`selection/optimize.role_pools`) —
   batters / all-rounders / bowlers, each independently ranked by score — the
   same view a coach actually picks from, rather than one flat ranked list.
   `select_xi`'s MILP already enforces batting/bowling-capable minimums under
   the hood (an all-rounder counts toward both); this just makes that
   division visible instead of implicit. Each player carries their own
   plain-language reasoning (no slot/alternative framing — that only makes
   sense once the XI-constrained pick has actually happened). Tagged `[XI]`
   where they also made the final side. The plain-JSON form (no `--pretty`)
   carries the identical grouping under a `"pools"` key, alongside the
   flat `"pool"` list, for a frontend to read directly.
2. **Playing XI**, in actual batting order, with the existing
   slot-comparison reasoning ("picked ahead of X").

### Analyzing a coach's own hand-picked XI

`analyze-xi` (`selection/optimize.analyze_xi`) is the counterpart to
`recommend`: instead of finding the algorithm's best XI, it scores and checks
a **specific, already-chosen** one — the real-world case where a coach picks
from the roster themselves (form momentum a model can't see, a tactical
matchup call, team chemistry) rather than taking the AI's suggestion outright.
Reuses the identical scoring and constraints `select_xi` is held to, so the
two are directly comparable:

```bash
python -m criiq_models.cli analyze-xi --team India --opponent Australia \
    --players "S Mandhana,H Kaur,Shafali Verma,..." --pretty
# or --player-ids "id1,id2,..." if you already have them (e.g. from `recommend`'s pools)
```

Reports, per player, the same reasoning `recommend` gives; then a team-level
scorecard: total/average score, whether the pick satisfies the same
batting-capable/bowling-capable/keeper/opener minimums (the same soft
degradation `select_xi` applies when the whole pool can't support a
requirement — e.g. zero recorded keepers — so the comparison is fair, not a
stricter bar than the AI's own XI is held to); and a direct diff against the
provably-optimal XI (`comparison_to_optimal`): the score gap, and exactly
which players are in one XI but not the other. Verified live: swapping one
bowler for an extra specialist batter in a real India-vs-Australia XI still
satisfied every constraint (all-rounders covering the gap) but cost 1.8
points — the diff correctly named the exact swap (`N Shree Charani` out,
`AB Sharma` in) rather than just reporting the number.

The two lists are shown separately rather than one being a prefix of the
other, because the MILP-constrained XI genuinely isn't just the pool's top
11 by score — a keeper or opener the constraints require can rank well
outside the top 20 (see "Constrained XI" above) and still make the side,
while a higher-scoring specialist can miss out if their slot is needed
elsewhere; the shortlist honestly shows when that happens rather than
hiding it. Useful for demoing the engine directly rather than reading raw
JSON. The CLI also force-reconfigures stdout/stderr to UTF-8 on startup —
Windows consoles often default to a legacy codepage, which otherwise
renders the narrative sentences' em dashes as "�" (confirmed in both a
plain terminal and PowerShell).

`python -m pytest tests -q` runs the unit tests against a small in-memory
fixture DB (no dependency on the real database).

## Model comparison notebook

`model_comparison.ipynb` trains Linear Regression, Ridge, Random Forest,
`HistGradientBoostingRegressor` (the production choice), XGBoost and LightGBM on
the exact same leakage-safe training table and temporal holdout as `backtest`, to
check empirically whether the production model choice actually matters. Re-run it
(`jupyter nbconvert --to notebook --execute --inplace model_comparison.ipynb`, or
open it directly) after any change to `features/historical.py` or the training
window — the results are computed, not hardcoded, so a stale notebook is just a
snapshot of an earlier run, not a guarantee about the current pipeline.

`model_comparison_robust.ipynb` extends this with 3 temporal holdout fractions
x 5 seeds per stochastic model (not a single lucky split), the real production
model imported directly from `train.py` (no re-implementation risk), and all
three metrics (MAE/R2/corr) reported together rather than ranked by MAE alone —
MAE and correlation can disagree on this data (the mean-predictor baseline has
the *lowest* MAE for both targets; correlation is the metric that actually
matters for a ranking task like XI selection). Re-run after any feature
change, same as the notebook above; confirmed after adding the domestic-form
feature that the model choice per target is unchanged.

## How a player is scored

Every score is a transparent sum of parts (mirrors the
`importance_score`/`importance_components` pattern already used in
`data-collection/criiq_data/impact.py`) — nothing is a black-box number:

| Part | Source | What it rewards |
|---|---|---|
| `model_part` (0–45) | learned model predicting Win-Probability-Added, now including recent **domestic-league** form (or rule-based fallback below min sample size) | actual match-winning impact for *this* context — not just big-looking stats |
| `matchup_part` (±21) | batting: aggregate dismissal history vs this opponent's bowlers (±8) + a style-specific edge vs their pace/spin mix (±5); bowling: aggregate wicket-rate vs this opponent's specific batters (±8) | a favourable/unfavourable matchup, for both disciplines a player might have |
| `phase_fit_part` (0–8) | `player_phase` (in-team percentile/rank) | being a phase specialist (powerplay/middle/death) |
| `team_need_part` (0–5) | this pool's weakest phase vs a format-wide benchmark | filling *this specific team's* current gap |
| `standing_part` (0–20) | `player_impact.importance_score`, ICC rank | proven track record |
| `risk_part` (≤0) | `player_registry` | age advisory, inconsistent selection, recalled-from-inactive |

`recommend/explain.py` turns this into plain-language sentences (not
component-labelled jargon) and always includes a non-additive `inputs`
sub-dict with the raw numbers behind each part, so every sentence traces back
to a real computed value.

### Why Win-Probability-Added, not contribution-share

The engine originally regressed on `bat_contribution_pct`/`bowl_contribution_pct`
(team-run-share / wicket-share) — a real case this session had it ranking a
part-time all-rounder **above** a long-proven opener, because contribution-share
measures how big a player's numbers were, not whether they moved their team
toward winning. `data-collection/criiq_data/wpa.py` fixes this: every ball is
scored by the already-fitted win-probability model, and the swing is credited
to whoever was on strike/bowling — win-probability-*added*. Sanity check that
motivated the whole switch: Smriti Mandhana averages **+0.077** batting WPA
per match across 144 matches; the player who'd wrongly outranked her averaged
**-0.002** across 23. Two independent `HistGradientBoostingRegressor`s (batting
WPA, bowling WPA — not one blended label, so a specialist's zero on their other
discipline doesn't drag down the one they're good at) are trained on
`features/historical.py`'s point-in-time reconstruction (rolling form +
expanding career + opponent/venue-to-date, computed strictly *before* each
match's date). Below `min_matches_for_model` (default 10) career matches, the
model is skipped entirely in favour of a shrinkage-based baseline —
`components.model_applied`/`cold_start_reason` record this honestly.

A found-and-fixed bug worth knowing about: vs-opponent and venue features are
the sparsest in the model (often 0-2 matches), and a live-scoring query with
no venue specified used to produce `venue_matches=0` paired with a *missing*
mean — a combination that never occurs in training (every played match has a
real venue) and was confirmed to send predictions wildly out of distribution.
Both `features/historical.py` and `features/current.py` now shrink these
toward the career baseline (`features/common.shrink_series`/`shrink`), so
`venue_matches=0` degrades smoothly to "assume their career average" instead.

### Domestic form — "quiet internationally, in-form domestically" now counts

`domestic_form_batting_wpa`/`domestic_form_bowling_wpa` are two more
`MODEL_FEATURES`, sourced from data-collection's `player_domestic_form`
(recent domestic-league-only WPA, tagged separately from the
international-only `player_career`/`player_impact`/`player_phase_wpa` — see
that package's README). Leakage-safety needed a different technique than
every other feature here: an international training row isn't a member of
the domestic-only event stream being averaged, so the usual
`groupby().transform()` pattern doesn't apply — `features/historical.py`
bridges the two streams with `pd.merge_asof(direction="backward")`, giving
each international row "the most recent domestic form as of this date,"
international or not. At live-scoring time there's no leakage concern
(`features/current.py` just reads the already-current aggregate directly).

Shrunk toward the player's own international career WPA the same way
vs-opponent/venue records are, but with the *sample size fed to the shrink
capped* at `SETTINGS.domestic_form_max_effective_matches` (default 10) — so
no amount of domestic match volume can fully override the international
prior. The cap itself was picked from a real grid search (5/10/15/20 effective
matches, same temporal-holdout methodology as `model_comparison_robust.ipynb`)
once real domestic data existed, not guessed — honestly, the differences
across the grid were within noise at the current ~220-domestic-player data
scale (4th-5th decimal place on MAE/R2/corr), so 10 was kept as a reasonable
middle value, not because it measurably won. The feature still fixes
*eligibility* either way (see data-collection's README) — that part is
unaffected by the exact shrinkage cap.

Real example (`explain --player-id <GA Elwiss> --opponent Australia`): "Recent
domestic form (10 matches): shifting win probability by -4.6% per match with
the bat and +1.2% with the ball — factored into the model above, alongside 7
international career matches." — an honest, not-cherry-picked number (her
recent domestic batting form is actually negative here).

### Status is now shown, not just used to silently filter

`recommend/explain.py` used to only mention `player_registry.retirement_status`
inside the negative-risk branch (INCONSISTENT / recalled-INACTIVE) — an
ACTIVE player got no status sentence at all. Every explanation now ends with
an unconditional "Current status: ACTIVE — appeared inside active window."
(or whatever the registry's own `status_reason` says), reusing data already
flowing through `score.py`'s `ExtraContext` — no new computation.

### Player analysis in explain: archetype, batting profile, best phase, role options

data-collection computes a rich batting profile per player (`player_advanced`)
that never used to reach `recommend --explain`'s output — the data existed, it
just wasn't wired into this package's narrative. `features/current.py`'s
`ExtraContext` now reads the whole batting block (strike rate, boundary%, dot%,
sixes, six rate, per-phase splits) plus `bowling_style`/`batting_hand`/
`archetype`, and `explain.py` narrates them as short coach-facing sentences.
Real output for RM Ghosh (India, a finisher who rates low on the composite
score) now reads:

```text
Right-handed finisher, 23 years old.
Bowls right-arm medium.
With the bat, expect strike rate 145, 22% boundary balls, 37% dot balls, 45 career sixes (5.06 per 100 balls).
Highest impact in the death overs (16-20): strike rate 166, 26% boundaries there.
...
The batting profile above is strong, but this rating is driven by win-probability-added
(impact on results), not raw hitting, so a finisher with modest recent win-impact still
rates low here. Worth a manual look for that specific role.
```

That covers, directly from real per-player data: **what to expect** (strike
rate, boundary%, dot%, sixes), **their best overs / where the impact is** (the
phase with their highest strike rate, with that phase's SR and boundary%), and
an explicit **transparency note** for the recurring "she's our best finisher
but isn't recommended" case — the composite score is win-probability-added, not
raw hitting, so a big-hitting finisher with modest recent win-impact rates low,
and that's flagged rather than left as a silent contradiction.

**Specialist role options.** `recommend` (JSON `role_options`, and a
"SPECIALIST ROLE OPTIONS" block in `--pretty`) now also surfaces the best
available **finisher / power hitter / anchor** across the *whole* scored pool,
ranked by that role's defining metric (finisher by death-overs strike rate,
power hitter by six rate) rather than the composite score
(`selection/optimize.role_highlights`). This is the fix for the flagged case:
RM Ghosh (death SR 166) now shows as the side's best finisher even at 7.8/100
and outside the auto-XI, so "who's our best finisher" is always answerable,
separately from "who does the model rank highest overall".

The `archetype` classifier itself was also reworked (in data-collection): it is
now gender-relative (per-gender percentile bars, since men's/women's hitting
distributions differ sharply), six-rate-driven for power hitters, and gated on
a minimum sample so a 7-ball cameo can't be tagged a "finisher" — see that
package's README. (`aggressor` was renamed to **power hitter** along the way.)

**What's genuinely not available, and why it isn't faked**: "best shot" /
"worst shot" (or any shot-type breakdown) needs shot-coded ball-by-ball logs —
Cricsheet's deliveries have no shot-type, line/length, or foot-movement
columns at all, and ESPNcricinfo (the one source that has this, CricViz-coded)
blocks scraping (verified HTTP 403) — see data-collection's README, "What is
NOT obtainable (and is therefore not faked)". The genuine, defensible
substitutes already shipped are exactly what this section surfaces plus the
existing vs-pace/vs-spin and vs-RHB/vs-LHB splits (`style_matchup.py`) — *who*
a player is effective against, not *which shot* or *where on the pitch*.

### Per-target model selection — picked from real numbers, not assumed

`recommend/train.py` fits a different model family per target, chosen from
`model_comparison.ipynb`'s holdout results rather than defaulting both to the
"production" HistGradientBoostingRegressor: **`batting_wpa` uses a
regularized `RandomForestRegressor`** (`max_depth=10, min_samples_leaf=5` —
an unregularized forest overfits this noisy per-match target badly enough to
fall *below* the mean-predictor baseline, confirmed by actually running it),
which edges out HistGB on correlation and R2, at an effectively tied MAE.
**`bowling_wpa` uses a `VotingRegressor`** blending a depth-limited HistGB
with a regularized RandomForest — see the next section for why. `evaluate/
backtest.py` imports the same `_make_model()` factory `train.py` uses, so the
reported holdout numbers are always for the model actually shipped, not a
stand-in.

### Bowling model tuning — depth-limited + ensembled + target winsorized

Bowling-WPA is the weaker of the two targets (see Known Limitations), so its
model got a dedicated round of tuning, each step checked against the real
temporal holdout across **3 different holdout fractions (0.15/0.2/0.25) and
5 random seeds each** — not a single lucky split, since a one-off split can
make a change look better or worse than it really is:

1. **Shallower trees.** Unconstrained `HistGradientBoostingRegressor`
   (sklearn's default) memorizes per-match noise on a target this weak;
   capping `max_depth=2` raised mean correlation from ~0.088 to ~0.105 across
   all 3 splits, *and* cut run-to-run variance roughly in half (std ~0.005 ->
   ~0.002) — a shallower, more constrained model was both better on average
   and more stable.
2. **Target winsorizing.** A single freak over (a hat-trick, a 30-run over)
   swings one match's bowling WPA far more than a typical performance does.
   Clipping *training* labels only (never the holdout labels metrics are
   scored against) to their 10th-90th percentile added another consistent
   bump (~0.105 -> ~0.107-0.117 depending on split) by stopping the model
   from spending its limited capacity chasing those rare extremes. Batting
   got the same treatment with a milder 5th-95th clip (its signal is
   already a bit stronger, so it needs less protection) for a small,
   consistent gain there too.
3. **Ensembling.** Averaging the tuned HistGB with a separately-regularized
   `RandomForestRegressor` (`max_depth=6, min_samples_leaf=50`) via
   `sklearn.ensemble.VotingRegressor` added a further, consistent few points
   on top of either model alone (~0.107 -> ~0.110-0.118) — the standard
   "ensembling reduces variance" effect, and a clean drop-in since
   `VotingRegressor` behaves like any other single estimator everywhere else
   in the codebase (score.py, backtest.py never had to change).

Net effect on the real temporal holdout (`criiq_models.cli backtest`,
default 0.2 split): bowling-WPA correlation **0.103 -> 0.11**, batting-WPA
**0.134 -> 0.136**. Real, checked, but still modest in absolute terms — see
Known Limitations for why a much larger jump isn't realistic given how noisy
per-match WPA inherently is.

### Bowling-specific features — wicket-taking rate

`career_bowl_wickets_per_match`/`form_bowl_wickets_per_match`
(`features/historical.py`/`features/current.py`) reconstruct, point-in-time,
how often a player has actually taken wickets *on the matches they bowled in*
— masked by `balls_bowled > 0` first, because `player_match_impact.wickets`
is `0` (not `NULL`) for matches a specialist batter didn't bowl at all, and
without the mask the feature would just dilute toward zero for anyone who
mostly bats. Confirmed via real backtest to move bowling-WPA prediction
correlation from ≈0.09 to ≈0.10 — a modest, genuine gain, not a dramatic one
(see Known limitations below for the honest baseline it's still up against).
Phase-specific bowling specialization was considered and deliberately
**not** added as a model feature — `phase_fit_part` (see the scoring table
above) already captures that signal from `player_phase`, and adding a second,
overlapping representation would be feature bloat without new information.

### Bowling containment data — extracted, tried as model features, not adopted

Bowling had thinner per-match signal than batting (`bat_strike_rate`,
`bat_contribution_pct` vs. just `economy`/`bowl_contribution_pct`), so
`data-collection/criiq_data/stats.py`/`ml_features.py` were extended to
extract three more per-match bowling metrics straight from `deliveries`, now
stored on `player_match_impact`: **`bowl_dot_pct`** (% of legal balls with zero
runs conceded — pressure applied), **`bowl_boundary_pct`** (% of legal balls
that went for four or six — containment failure), and **`bowl_strike_rate`**
(balls per wicket, `NULL` rather than 0 in a wicketless spell). All three were
added as `career_`/`form_` model features and checked against the real
temporal holdout — **and every one of them made bowling-WPA prediction worse**
(correlation dropped from 0.103 to as low as 0.088 individually, 0.088
combined), confirmed by an ablation that isolated each feature one at a time.
They were removed from `MODEL_FEATURES` rather than kept "just in case" —
consistent with this project's rule of deciding by real backtest numbers, not
plausible-sounding feature engineering. The extraction itself was kept: `career_bowl_dot_pct`/`career_bowl_boundary_pct`
now surface as plain-language color in `/recommend --explain` ("their bowling
has a control-focused, pressure-building profile: 47% dot balls, 6% boundary
balls conceded") via `recommend/score.py`'s `inputs.bowl_dot_pct`/
`inputs.bowl_boundary_pct` — genuinely useful to a human reader, with none of
the overfitting risk of feeding it back into a prediction. `bowl_strike_rate`
is stored but not currently surfaced anywhere (kept for future analysis).

### Age as a model feature — tried, rejected, kept as narrative color

A fine-tuning pass explicitly asked to consider "age factor, active status,
ground performance, domestic performance" alongside the existing models.
Ground (`venue_*`) and domestic (`domestic_form_*`) performance were already
real model features (see the feature table above); active/retirement status
is deliberately a rule-based eligibility gate + score component
(`roster.py`, `score.py`'s `risk_part`), not a raw training feature — folding
today's registry snapshot into a *historical* training row would leak (it
isn't the player's status as of that past match), and the recency-weighted
`form_*`/`career_matches` features likely already carry most of the same
signal a coarser status flag would add.

Age was genuinely new and testable: `players.date_of_birth` (partial real
coverage — 55.8%/60.6% of women's/men's *training rows* respectively, since
enriched players tend to be the more-capped ones) makes a leakage-safe
`age_years` feature computable (age at each match's own date is an objective
fact, no leakage-safety design needed, unlike every other feature in
`historical.py`). Added, tested with the exact same rigor as every other
model decision here (3 holdout fractions x 5 seeds, both genders, the real
production architecture) — and rejected on the evidence:

| Gender / target | corr without age | corr with age |
|---|---|---|
| female / batting_wpa | 0.12076 | 0.12107 (noise) |
| female / bowling_wpa | 0.07815 | 0.07810 (noise) |
| male / batting_wpa | 0.08625 | 0.08496 (**worse**) |
| male / bowling_wpa | 0.06500 | 0.06413 (**worse**) |

MAE identical to 4 decimals in every case. Not added to `MODEL_FEATURES` —
same "decide by the real backtest, not a plausible-sounding feature" rule
the bowling containment features below were rejected under. Still computed
at live-scoring time and shown as descriptive-only color in `explain`
output ("Left-handed balanced, 30 years old.").

### External research: Wikipedia bowling-style/batting-hand at scale

`data-collection/criiq_data/styles.py`'s `enrich_from_wikipedia()` already
existed (Wikidata sitelink → Wikipedia cricketer-infobox parsing, free and
legal — ESPNcricinfo itself blocks scraping) but had only ever been run for
a handful of players. Running it unrestricted found real coverage was
strikingly thin: of the DB's 1,739 distinct female T20 bowlers, only 127
(7.3%) had a resolved `bowling_style`, and only 8 players *in the entire
database* had `batting_hand` set. Running the enrichment at full scale
(`criiq_data.cli styles --wiki`, no `--limit`) processed 7,218 candidates in
under 2 minutes and filled 2,269 new bowling styles and 2,582 new batting
hands — bowling-style coverage among real female T20 bowlers alone jumped
from 127 to 568 (7.3% → 32.7%). `player_advanced` was rebuilt afterward
(`criiq_data.cli advanced`) so the newly-covered players' vs-pace/vs-spin and
vs-batting-hand splits actually populate — spot-checked against real
bowlers, e.g. Sophie Ecclestone's now-real vs-RHB/vs-LHB average split
(15.2 vs 22.1) matches the well-known cricketing fact that a left-arm
finger-spinner is typically more dangerous to right-handers.

Tried, checked, **not adopted** as a direct model feature: a coarse
`bowl_style_bucket` (pace/spin/unknown) categorical was added to
`MODEL_FEATURES` for `bowling_wpa` and tested the same rigorous way as every
other change here (3 holdout fractions × 5 seeds) — it made **no measurable
difference** (0.1074 vs 0.1072, 0.1166 vs 0.1167, 0.1068 vs 0.1068 — all
within noise). Once the model already has a bowler's own historical
economy/wicket-rate, knowing they're "pace" or "spin" in the abstract adds
nothing further. Not shipped as a model feature.

**What the expanded coverage did genuinely enable** (both already-existing,
previously coverage-starved systems, not the regression target):

- `features/style_matchup.py`'s existing batter-vs-attack style edge now has
  real pace/spin data for far more opponents' bowling attacks, not just the
  18 nations `role_finalize.py` separately hand-researched squad roles for.
- **A new, symmetric bowling-side matchup signal** (`recommend/score.py`) —
  see next section, the direct payoff of collecting this data.

### Bowler-side matchup — a real gap this research uncovered and closed

Investigating what the new coverage could unlock surfaced a structural gap:
`matchup_part`'s aggregate signal (`dismissal_matchup` scoped by
`batter_id`+`bowler_team`) is fundamentally a *batting* signal — how well
*this player bats* against the opponent's bowlers. A specialist bowler, who
rarely faces enough balls themself to generate a meaningful reading there,
got essentially **no matchup-specific credit at all**, no matter how well
they've actually bowled against this specific opponent's specific batters.

`dismissal_matchup` has no `batting_team` column, but the same real, rich
per-pair history already exists on the *bowling* side (`bowler_id`) — it
just needed opponent-scoping through roster membership (`roster.team_pool`,
same lookup `opponent_bowling_mix` already uses) instead of a stored team
column. `features/current.py`'s `build_extra_context` now also aggregates
`dismissal_matchup` rows for `bowler_id=player_id` where `batter_id` is in
the opponent's *current* roster, and `recommend/score.py` turns that into a
`bowl_matchup_part` (±8, same cap as the batting aggregate) — a bowler's
wicket-rate against this opponent's actual batters, shrunk toward and
compared against their career wicket-rate-per-ball, with the opposite polarity
from the batting side (higher-than-career is *good* for a bowler). The scale
constant (175, vs. the batting side's 120) was calibrated against the real
distribution of career bowling wicket-rate (std ≈0.019) vs. batting
dismissal-rate (std ≈0.028) — proportionally matched, not copied blindly.
Confirmed on the real DB: a specialist bowler who's taken wickets at nearly
3x their career rate against an opponent's specific batters now shows
`+8.0 pts` and a real explain sentence, where before they'd have shown
nothing on this axis at all.

**A real performance bug found while verifying this**: profiling a full
`recommend` call revealed `roster.team_pool` (which includes an expensive
cross-gender-identifier scan over the whole match history) was being
recomputed from scratch *once per player scored* by the pre-existing
`style_matchup_edge`/`opponent_bowling_mix` — 0.6s × 77 players ≈ most of an
84-second `score_many` call, dwarfing actual model-prediction time (~18s).
Neither depends on which player is being scored, so `RecommendationScorer`
now caches the opponent's roster once per opponent and threads it through
both call sites — a full `recommend --explain` for a real team went from
**78s to 23s** (3.4x), a genuine fix, not something introduced by the new
bowler-matchup feature (which reuses the same cache).

### Learning-to-rank — tried, checked against real numbers, not adopted

`evaluate/rank_backtest.py` fits an `LGBMRanker` (lambdarank, grouped by
match) on the same leakage-safe features and compares its ranking quality
against simply ranking by the two WPA regressors' combined prediction, on
the same temporal holdout as `backtest`. Real result:
`python -m criiq_models.cli rank-backtest` — the regression-based ranking
**wins on both metrics** (top-11 hit rate 0.626 vs 0.579, Spearman rank
correlation 0.28 vs 0.116). The dedicated ranker is not wired into
`select_xi` — the theoretical case for learning-to-rank (it directly
optimizes what selection actually needs) didn't survive contact with this
particular dataset, likely because collapsing batting+bowling into one
combined, coarsely-graded relevance label throws away the role-specific
signal the two separate regressors preserve. Kept as a documented, run-able
comparison rather than silently discarded — re-run it if the feature set or
label design changes materially.

### Style-specific matchup

`matchup_part` has two components: the pre-existing aggregate dismissal
history vs this opponent's specific bowlers, plus a newer style-specific edge
(`features/style_matchup.py`) — the opponent's actual current pace/spin mix
(`player_styles.bowling_style`) weighted against the batter's own vs-pace/vs-spin
record (`player_advanced.profile_json`). Both halves of this signal exist
because of work done this session: bowling style for 13 major nations' current
bowlers was backfilled from Wikipedia squad data already fetched for
`role_finalize.py` (previously discarded), and `player_advanced`'s
vs-bowling-type split only populates once enough bowlers have a resolved
style. It's a secondary, backup signal (±5, smaller than the aggregate ±8) —
coverage is still partial, and style alone is coarser than specific-bowler
history when that's available.

### Synergy-aware team need

A player scored alone can't know "this pool is thin on death bowling" — only
the pool as a whole does. `recommend/team_need.py` identifies the *single*
phase where this specific recommendation's candidate pool falls furthest
below a format-wide benchmark (`player_phase_wpa`), then rewards whoever is
genuinely strong there — never a penalty for not being the answer. Calibrated
against the real distribution (combined phase-WPA has a standard deviation of
~0.065-0.078): a one-std-dev surplus reads as a noticeable strength, a
two-std-dev surplus (genuinely exceptional) hits the small cap. The first
version used a scale 6x too aggressive and hit the cap for nearly every
player in the pool regardless of relevance — caught by eyeballing real output,
not by a metric.

### Constrained XI

`selection/optimize.py` picks the XI as a small 0/1 linear program
(`scipy.optimize.milp`) maximizing total score subject to exactly 11 players,
≥5 batting-capable, ≥5 bowling-capable, ≥2 openers (by actual historical
batting position, not guesswork), and — where the pool has any `is_keeper`
data — ≥1 wicket-keeper. The MILP runs over the *entire* candidate pool, not
the top-`pool_size` display slice: a keeper's or opener's raw score is often
below a squad's best all-rounders, so truncating before optimizing would
silently drop the constraint (a real bug found and fixed this session).

The selected XI is presented like an actual team sheet, not sorted by raw
score: the two best-scoring openers lock slots 1-2 (a third strong opener
competes on pure merit for the rest of the order, exactly like a real team
bats a surplus opener further down), the rest of the batting order ranks by
score, and specialist bowlers trail at the tail. `--explain` also names who
each XI member was picked over for their specific slot.

### A found-and-fixed eligibility bug: decade-old players in current squads

`roster.team_pool`'s `INACTIVE` exclusion (a player absent 3+ years,
`data-collection`'s `player_registry.retirement_status`) has always
deferred to `recall_flag==0`, meaning `INACTIVE & recall_flag==1` stays
eligible. Checked live while demoing the engine: "RK Parwin", last
appearance for India in **2012**, was still showing up in a 2026 India
recommendation. Root cause was upstream in `data-collection/registry.py`'s
`recall_flag` computation, not here (see that package's README for the full
story) — fixed there, and confirmed on rebuild: **zero** players with a
last real appearance before 2023 remain in any of the 90 known teams'
current pools. Nothing in this package needed to change; `roster.py`'s
exclusion logic was always correct, it was just being fed a broken input.

## Known limitations (honestly reported)

- **Bowling-WPA prediction is weak, batting-WPA only slightly less so.**
  Temporal-holdout backtest: batting WPA barely beats a mean-predictor
  baseline (MAE 0.082 vs 0.081, corr ≈ 0.136, top-quartile hit-rate ≈ 32% vs a
  ~25% random baseline); bowling WPA is similarly marginal (MAE 0.069 vs
  0.068, corr ≈ 0.11, hit-rate ≈ 36%) even after wicket-taking-rate features,
  a better-suited batting model, and a dedicated round of bowling-model
  tuning (depth-limited + ensembled + target-winsorized — see above) — all
  real, checked improvements (bowling correlation moved ≈0.09 -> 0.103 -> 0.11
  across this session), none individually dramatic. Per-match WPA is
  inherently high-variance (one dropped catch, one hat-trick, swings it
  hugely) — the engine leans on career-to-date/form aggregation (which
  averages out that noise) rather than per-match precision to still produce
  a sensible ranking; see the Mandhana-vs-Hemalatha sanity check above for
  why that aggregation still works even though single-match MAE is
  unimpressive. A materially larger jump would most likely need either a
  fundamentally richer bowling signal than ball-by-ball data alone provides
  (pitch/conditions data, true delivery type instead of coarse pace/spin, a
  bowler's specific plan for a specific batter) or accepting that a chunk of
  per-match bowling variance is genuinely unpredictable from history (a
  dropped catch off their bowling isn't *their* signal at all). Run
  `criiq_models.cli backtest` after any change to see current numbers.
- **Wicket-keeper detection covers 18 women's T20I nations' current squads —
  zero men's nations yet.** (Wikipedia squad-page role text, merged by
  `key_cricinfo` — see data-collection's `role_finalize.py`): the original 13
  major women's nations plus the United Arab Emirates, Namibia, Nepal,
  Netherlands, and Hong Kong, added by real match-volume ranking among
  previously-uncovered teams (110, 99, 95, 94, and 93 matches respectively in
  the current DB). This research was only ever done for women's squads —
  `player_role_final.is_keeper` is `0`/unset for every men's player in the
  live DB (confirmed by direct query), so `recommend`/`analyze-xi` for any
  men's team currently fall back to no keeper constraint entirely (the same
  graceful degradation — `min(settings.min_keepers, available_keepers)` in
  `selection/optimize.py` — already used for uncovered women's teams, not a
  crash or a wrong pick, just no keeper preference enforced). Closing this
  for men's squads needs the same one-time research-and-merge pass
  (`role_finalize --load-external`) this bullet describes for women's, not
  any code change. Still not the full ~7000-player pool either way —
  recommending for a team outside whatever coverage exists falls back to no
  keeper constraint (rather than guessing) until its squad is researched and
  merged the same way. A handful of names didn't confidently resolve even
  within the 18 covered women's nations (e.g. two Hong Kong players surnamed
  "Chan" with no matching initial, a Nepal squad name spelled differently in
  Wikipedia vs. the DB) — surname+initial matching correctly declined to
  guess rather than risk a wrong identity link. **Bowling-style detection is
  broader** — unlike wicket-keeper status, it comes from each player's own
  Wikipedia infobox (not a squad-page lookup scoped to specific nations), so
  running it unrestricted covers any player with an English Wikipedia
  article: 568 of 1,739 real female T20 bowlers (32.7%, up from 127/7.3%
  before this was run at scale) — see "External research" above. Confirmed
  this isn't a women's-only side effect: a live-DB check of men's T20 bowlers
  (≥60 career balls bowled) shows comparable real coverage, 868/2,038 (42.6%)
  — bowling-style enrichment was never gender-restricted, only wicket-keeper
  detection (a squad-page lookup, above) was.
- **`player_registry.nationality` is entirely empty** for T20 in the live DB.
  `roster.py` derives "current team" from actual match appearances
  (`match_players` + `matches`) instead — the team of a player's most recent
  appearance.
- **~~A ~32-identifier cross-gender collision exists in the underlying
  data~~ — fixed at the root.** A handful of Cricsheet's own registry
  identifiers are confirmed reused across two genuinely different real
  people — one male, one female — sharing an ambiguous short display name
  (this is Cricsheet's own data quirk, not a bug in this codebase's
  matching). `roster.py` used to just exclude these ~32 identifiers from
  recommendation pools entirely as a containment fix. The real fix now lives
  in data-collection (`identity.py`'s `player_id_for(identifier, gender)` +
  a `UNIQUE(cricsheet_identifier, gender)` schema migration — see that
  package's README for the full story): each colliding identifier now mints
  two distinct, stable player_ids, so the previously-excluded players are
  correctly *included* again with clean, un-blended stats, rather than
  hidden. `roster.py`'s `_player_id_map` mirrors data-collection's resolver
  (kept local, not imported — this package never imports data-collection's
  code, only reads its DB). Confirmed on the real DB: e.g. "K Joshi", a
  currently-active Nepal player previously invisible to every recommend
  call, now correctly appears with her own real record.
- **Men's T20I is now a fully trained, verified second scope, not just a
  theoretical config change.** data-collection already ingested full men's
  T20I match data alongside women's, and by the time this was actually
  turned on, every table in the pipeline (`player_career`, `player_impact`,
  `player_by_venue`, `player_match_wpa`, `player_registry`, ...) already had
  real men's rows sitting in it — 4,449 distinct men's T20 players vs 2,549
  women's, confirmed by direct query. Two real bugs were found and fixed
  while wiring this up, both worth knowing about if you're extending to a
  third scope later:
  - **Model artifacts weren't actually scoped by `(format, gender)`.**
    `train.py` wrote every scope's models to the same flat filenames
    (`model_batting_wpa.joblib`, ...); training a second gender would have
    silently overwritten the first's models with no error, and
    `RecommendationScorer.__init__` was calling the no-argument
    `load_models()`/`load_metadata()` even though it already carried its own
    `self.fmt`/`self.gender` — so a scorer built for one scope could
    silently score real players against a model trained on the other scope.
    Fixed by routing every persist/load path through a
    `_artifacts_dir(fmt, gender)` helper
    (`artifacts/player_recommendation/{gender}_{format}/`), and by actually
    passing `fmt`/`gender` through in `score.py`, `cli.py`, and
    `evaluate/rank_backtest.py`. Both scopes' models are now trained and
    verified independently present on disk.
  - **`recommend/explain.py`'s narrative sentences hardcoded "she"/"her"**
    throughout ("she's expected to shift her team's win probability...").
    Harmless while the pool was women's-only; a real bug the moment men's
    players flow through the identical code path. No per-player personal
    pronoun is ever stored (only the cricket-format `gender` field, a
    different thing), so the fix is neutral phrasing for every player
    ("they're expected to shift their team's...") rather than a second
    he/him branch keyed off that field — see `test_explain_uses_no_gendered_pronouns`.
  Verified end-to-end on real data post-fix: `recommend --team India
  --opponent Australia --gender male --pretty` correctly scores and explains
  real current players (Ishan Kishan, SA Yadav, JJ Bumrah, ...) with neutral
  narrative text and a correct status line for each (e.g. V Kohli correctly
  resolves to `RETIRED_FORMAT` via a manual override and is correctly
  excluded from the eligible pool, the same eligibility boundary already
  verified for women's). Registry classification itself needed **no** code
  change for men — `player_registry`'s ACTIVE/INCONSISTENT/INACTIVE logic
  (see "A found-and-fixed eligibility bug" above) already processes every
  `(identifier, gender)` pair in one pass; spot-checked on real men's data
  (long-retired legends like SR Tendulkar and GD McGrath correctly
  `INACTIVE`, current top-ranked players correctly `ACTIVE` via
  `icc_ranked`) with no gender-specific special-casing needed. The one
  still-open gap is wicket-keeper coverage (see above) — a data-research
  gap, not a code one.
- **~~Team-need benchmarks mix genders~~ — fixed.** `recommend/team_need.py`'s
  format-wide phase benchmark used to average `player_phase_wpa` across every
  player regardless of gender — a men's pool's "is this team weak at death
  bowling" question was being answered against a benchmark blended with
  women's data (and vice versa), even though the candidate pool itself was
  already correctly gender-scoped via `roster.team_pool`. Real playing styles
  and typical phase-WPA magnitudes differ enough between genders that this
  was a genuine bug, not just an imprecise reference point: real benchmarks
  now measurably differ by gender (e.g. death-overs benchmark -0.002 for men
  vs +0.003 for women, confirmed on live data). Fixed by scoping the
  benchmark query to the pool's own gender via each player's real match
  participation (`player_match_wpa` join `matches.gender` — `player_phase_wpa`
  has no gender column of its own, and `players.gender` is only ever set for
  the ~32 identifiers split by the cross-gender-collision fix below, NULL for
  everyone else, so it can't be used directly here).

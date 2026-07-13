# Criiq — Player Recommendation Engine (`criiq_models`)

The AI module: scores every eligible player for a given (team, opponent, venue)
context and proposes a balanced playing XI, with plain-language reasoning for
every pick. Reads `data-collection`'s SQLite DB
(`../data-collection/data/criiq.db`) **read-only** — this package owns no data
of its own beyond its trained model artifacts. Scope for now: **women's T20I**
(`format=T20, gender=female`), kept as config rather than hardcoded so
extending to other format/gender scopes later is a settings change.

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
python -m criiq_models.cli recommend --team India --opponent Australia [--venue <id>] [--explain] [--pretty]
python -m criiq_models.cli explain --name "H Kaur" --opponent Australia
```

`--pretty` (`recommend/render.py`) renders an actual team sheet instead of
dumping JSON, in two parts (implies `--explain`; nothing is computed
differently, only formatted and, for the shortlist, given individual
reasoning too):

1. **Top `pool_size` (20) recommended players**, ranked by raw score, each
   with her own plain-language reasoning (no slot/alternative framing —
   that only makes sense once the XI-constrained pick has actually
   happened). Tagged `[XI]` where she also made the final side.
2. **Playing XI**, in actual batting order, with the existing
   slot-comparison reasoning ("picked ahead of X").

The two lists are shown separately rather than one being a prefix of the
other, because the MILP-constrained XI genuinely isn't just the pool's top
11 by score — a keeper or opener the constraints require can rank well
outside the top 20 (see "Constrained XI" above) and still make the side,
while a higher-scoring specialist can miss out if her slot is needed
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

## How a player is scored

Every score is a transparent sum of parts (mirrors the
`importance_score`/`importance_components` pattern already used in
`data-collection/criiq_data/impact.py`) — nothing is a black-box number:

| Part | Source | What it rewards |
|---|---|---|
| `model_part` (0–45) | learned model predicting Win-Probability-Added (or rule-based fallback below min sample size) | actual match-winning impact for *this* context — not just big-looking stats |
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
measures how big a player's numbers were, not whether they moved her team
toward winning. `data-collection/criiq_data/wpa.py` fixes this: every ball is
scored by the already-fitted win-probability model, and the swing is credited
to whoever was on strike/bowling — win-probability-*added*. Sanity check that
motivated the whole switch: Smriti Mandhana averages **+0.077** batting WPA
per match across 144 matches; the player who'd wrongly outranked her averaged
**-0.002** across 23. Two independent `HistGradientBoostingRegressor`s (batting
WPA, bowling WPA — not one blended label, so a specialist's zero on her other
discipline doesn't drag down the one she's good at) are trained on
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
`venue_matches=0` degrades smoothly to "assume her career average" instead.

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
how often a player has actually taken wickets *on the matches she bowled in*
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
now surface as plain-language color in `/recommend --explain` ("her bowling
has a control-focused, pressure-building profile: 47% dot balls, 6% boundary
balls conceded") via `recommend/score.py`'s `inputs.bowl_dot_pct`/
`inputs.bowl_boundary_pct` — genuinely useful to a human reader, with none of
the overfitting risk of feeding it back into a prediction. `bowl_strike_rate`
is stored but not currently surfaced anywhere (kept for future analysis).

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
economy/wicket-rate, knowing she's "pace" or "spin" in the abstract adds
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
rarely faces enough balls herself to generate a meaningful reading there,
got essentially **no matchup-specific credit at all**, no matter how well
she's actually bowled against this specific opponent's specific batters.

`dismissal_matchup` has no `batting_team` column, but the same real, rich
per-pair history already exists on the *bowling* side (`bowler_id`) — it
just needed opponent-scoping through roster membership (`roster.team_pool`,
same lookup `opponent_bowling_mix` already uses) instead of a stored team
column. `features/current.py`'s `build_extra_context` now also aggregates
`dismissal_matchup` rows for `bowler_id=player_id` where `batter_id` is in
the opponent's *current* roster, and `recommend/score.py` turns that into a
`bowl_matchup_part` (±8, same cap as the batting aggregate) — a bowler's
wicket-rate against this opponent's actual batters, shrunk toward and
compared against her career wicket-rate-per-ball, with the opposite polarity
from the batting side (higher-than-career is *good* for a bowler). The scale
constant (175, vs. the batting side's 120) was calibrated against the real
distribution of career bowling wicket-rate (std ≈0.019) vs. batting
dismissal-rate (std ≈0.028) — proportionally matched, not copied blindly.
Confirmed on the real DB: a specialist bowler who's taken wickets at nearly
3x her career rate against an opponent's specific batters now shows
`+8.0 pts` and a real explain sentence, where before she'd have shown
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
each XI member was picked over for her specific slot.

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
  dropped catch off her bowling isn't *her* signal at all). Run
  `criiq_models.cli backtest` after any change to see current numbers.
- **Wicket-keeper detection covers 18 women's T20I nations' current squads**
  (Wikipedia squad-page role text, merged by `key_cricinfo` — see
  data-collection's `role_finalize.py`): the original 13 major nations plus
  the United Arab Emirates, Namibia, Nepal, Netherlands, and Hong Kong, added
  by real match-volume ranking among previously-uncovered teams (110, 99, 95,
  94, and 93 matches respectively in the current DB). Still not the full
  ~7000-player pool — recommending for a team outside this coverage falls
  back to no keeper constraint (rather than guessing) until its squad is
  researched and merged the same way. A handful of names didn't confidently
  resolve even within these 18 (e.g. two Hong Kong players surnamed "Chan"
  with no matching initial, a Nepal squad name spelled differently in
  Wikipedia vs. the DB) — surname+initial matching correctly declined to
  guess rather than risk a wrong identity link. **Bowling-style detection is
  broader** — unlike wicket-keeper status, it comes from each player's own
  Wikipedia infobox (not a squad-page lookup scoped to 18 nations), so
  running it unrestricted covers any player with an English Wikipedia
  article: 568 of 1,739 real female T20 bowlers (32.7%, up from 127/7.3%
  before this was run at scale) — see "External research" above.
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
- **This is also what makes adding men's T20I later a config change, not a
  rewrite.** data-collection already ingests full men's T20I match data
  alongside women's (3,393 vs 2,035 matches) — every table in this pipeline
  is already scoped by `gender=SETTINGS.gender`, a setting, not a hardcoded
  literal. The one thing that would have made extending to men's genuinely
  unsafe — player identity silently colliding across genders — is now fixed
  at the source, so scoring men's T20I later needs no identity-layer work,
  just pointing `SETTINGS.gender` at `"male"` (and, before doing that,
  re-running `criiq_models.cli backtest`/`train` against that scope's own
  data — the model artifacts here are trained on and tuned for women's T20I
  specifically, not automatically valid for men's).
- **Team-need benchmarks mix genders** (computed across the whole format,
  like several other data-collection derived tables already do) even though
  the candidate pool itself is correctly gender-scoped — affects only the
  reference point strength is compared against, not who's eligible.

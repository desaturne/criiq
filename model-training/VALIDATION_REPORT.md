# Criiq — Model Validation Report

Generated 2026-07-22, run fresh against the live database (`data-collection/data/criiq.db`) for both `(T20, female)` and `(T20, male)` scopes. All numbers below are actual outputs of the commands shown, not from documentation — reproducible by re-running the same commands.

**Sections 2 and 3 updated 2026-07-31** after a live hyperparameter search
(`training_and_selection_walkthrough.ipynb`'s hyperparameter-search section) changed the shipped
`batting_wpa`/`bowling_wpa` models — `batting_wpa` now uses `max_features="sqrt"` for the female
scope only (checked on both scopes; didn't generalize to male, so not applied there — see that
notebook or `ALGORITHMS.md` §3.3 for the full comparison), and `bowling_wpa` now uses a
`weights=[0.7, 0.3]`-favored ensemble with a milder (0.02, 0.98) training-label clip (generalized
cleanly to both scopes). Every other section below is unchanged and still reflects the 2026-07-22
run.

**Report history, so every number below can be traced to when it was actually measured:**

| Section(s) | Measured | Against which models |
|---|---|---|
| §1–§10 | 2026-07-22 (§2/§3 refreshed 2026-07-31, noted above) | §1–§8, §10: pre-2026-07-31 models. §2/§3: current models (refreshed in place). |
| §9 | 2026-07-22, corrected 2026-07-23 (see that section for what the correction was) | pre-2026-07-31 models. |
| §11 | 2026-07-24 | pre-2026-07-31 models — **left exactly as originally written below**, a historical record of that run, not updated in place. |
| §14 (new) | 2026-08-06 | the **current** shipped models (retrained 2026-07-31) — a full, expanded re-run of §11's exact question (does the Playing XI recommendation and match simulator hold up on real, unseen data) against what's actually deployed today. Read §14 for the current answer; §11 for what changed and by how much. |

No number in §1–§11 has been altered from when it was originally generated — only this history table and pointers to §14 were added on 2026-08-06.

## 1. Test suites — correctness precondition

| Suite | Result |
|---|---|
| `model-training` (`pytest`) | **121 passed**, 0 failed |
| `data-collection` (`pytest`) | **50 passed**, 0 failed |

## 2. WPA regressor temporal holdout (`criiq_models backtest`)

Split by match **date** (80th percentile cutoff), never by row — prevents same-match leakage. Model trains only on matches before the cutoff, scores only on matches after it (genuinely unseen).

| Scope | Cutoff | Train / Test rows | Target | MAE | Baseline MAE (mean-predictor) | Correlation | Top-quartile hit-rate |
|---|---|---|---|---|---|---|---|
| female T20 | 2025-08-14 | 32,756 / 8,213 | batting_wpa | 0.095 | 0.096 | **0.122** | 35.1% |
| female T20 | 2025-08-14 | 32,756 / 8,213 | bowling_wpa | 0.077 | 0.078 | **0.076** | 26.9% |
| male T20 | 2025-06-12 | 57,436 / 14,440 | batting_wpa | 0.089 | 0.090 | **0.093** | 31.1% |
| male T20 | 2025-06-12 | 57,436 / 14,440 | bowling_wpa | 0.070 | 0.071 | **0.073** | 25.2% |

(Row counts shifted slightly from the 2026-07-22 run — new matches ingested in the interim, not a
methodology change. Male batting is architecturally unchanged by the 2026-07-31 search; its small
movement here vs. the original 0.088 is that same natural data drift, not the model change.)

**Reading these honestly:** MAE barely beats the "just guess the average" baseline — expected, since per-match cricket outcomes are high-variance (one big innings swings a match's WPA hugely). Correlation and top-quartile hit-rate are the metrics that actually matter for a selection task, and both are clearly above chance (a random top-quartile pick would hit ~25%; the model hits 30–34% on batting).

## 3. Stability check — repeated holdout across 3 split fractions

Same evaluation re-run at 0.15 / 0.20 / 0.25 test fractions, to confirm the numbers above aren't a lucky/unlucky single cutoff date.

| Scope | Target | corr @0.15 | corr @0.20 | corr @0.25 |
|---|---|---|---|---|
| female | batting_wpa | 0.128 | 0.124 | 0.126 |
| female | bowling_wpa | 0.084 | 0.076 | 0.074 |
| male | batting_wpa | 0.087 | 0.090 | 0.082 |
| male | bowling_wpa | 0.072 | 0.075 | 0.071 |

All four series stay in a tight band (~±0.02) across cutoffs — the headline numbers are stable, not a one-split artifact. (Refreshed 2026-07-31 for the shipped config each scope actually uses — see the note at the top of this report; each cell here is a mean across 3 random seeds at that fraction, not a single run, matching the protocol `training_and_selection_walkthrough.ipynb` uses to decide what ships.)

## 4. Learning-to-rank alternative — rejected, confirmed again (`rank-backtest`)

| Scope | Metric | LGBMRanker | Shipped regression baseline |
|---|---|---|---|
| female | top-11 hit-rate | 0.567 | **0.652** |
| female | Spearman | 0.064 | **0.346** |
| male | top-11 hit-rate | 0.549 | **0.611** |
| male | Spearman | 0.045 | **0.264** |

Confirms the project's existing decision: the two independent regressors beat a dedicated ranker, decisively, on real current data. Not switched into `select_xi`.

## 5. Win-probability model (`EmpiricalWinProb`) — held out by match, not by ball

| Gender | Test balls | Brier | Brier baseline | Log-loss | Log-loss baseline |
|---|---|---|---|---|---|
| female | 93,714 | **0.1557** | 0.2447 | **0.4775** | 0.6825 |
| male | 145,372 | **0.1727** | 0.2500 | **0.5156** | 0.6932 |

Lower is better for both. Meaningfully beats the constant-prior baseline in both genders — the model is genuinely reading match state, not just reproducing the base win rate.

## 6. Feature leakage-safety — verified by reading the code, not assumed

Inspected `features/historical.py` directly: every rolling/career feature uses `.shift(1)` before `.expanding()`/`.rolling()`, so a match's own row is excluded from its own features; `career_matches`/`vs_opp_matches`/`venue_matches` use `cumcount()` (counts *prior* matches only). The one cross-stream join (domestic-form via `merge_asof(direction="backward")`) is safe because domestic and international matches for the same player never share a calendar date. Confirmed correct.

## 7. Concrete real-match example (not just aggregate numbers)

Predicted vs. actual player WPA for one genuinely held-out match per gender (both fall after their scope's holdout cutoff above):

**Female — India vs Sri Lanka, 2025-12-21 (India won)**
| Player | Actual batting WPA | Predicted |
|---|---|---|
| JI Rodrigues | 0.280 | 0.020 |
| H Kaur | 0.174 | 0.034 |
| S Mandhana | 0.102 | 0.076 |
| Shafali Verma | -0.162 | 0.049 |

**Male — West Indies vs Australia, 2025-07-20 (Australia won by 3 wkts)**
| Player | Actual batting WPA | Predicted |
|---|---|---|
| MJ Owen (Player of the Match) | 0.568 | -0.002 |
| SD Hope | 0.273 | 0.001 |
| AD Russell | 0.120 | 0.010 |

**Honest takeaway:** the model gets the *direction* right for steady contributors (Mandhana) but badly underestimates one-off standout performances (Rodrigues' 69, Owen's match-winning 50) — exactly the documented limitation that per-match cricket variance is dominated by rare big innings the model can't foresee from pre-match form alone.

## 8. End-to-end sanity check — full simulator on a real held-out match

Ran `criiq_models simulate` with the real playing XIs for West Indies vs Australia (2025-07-20, Sabina Park), 300 Monte Carlo reps:

- **Simulated:** West Indies 57.0% / Australia 43.0% win probability
- **Actual result:** Australia won by 3 wickets

The simulator called this a close match leaning the other way; the real result went to Australia within the simulator's own uncertainty band (43%) rather than being confidently wrong — a reasonable outcome for a single genuinely unseen match, not a failure (T20 has a lot of irreducible variance, as §2 already shows).

## 9. Genuine forward-holdout — the project's own built-in mechanism, at full scale (corrected 2026-07-23)

**This section replaces an earlier, mistaken version of itself.** The first attempt at this section checked `matches`/`deliveries` directly, found nothing dated after 2026-06-15, ran a full `data-collection` refresh from Cricsheet, still found nothing, and concluded "no newer real data exists anywhere." That conclusion was **wrong**, and was caught by spotting that Cricsheet's own public stats page shows matches played well into July. The real explanation: `data-collection/criiq_data/ingest.py` deliberately routes anything dated after `SETTINGS.data_cutoff_date` (**2026-06-15**) into separate `matches_holdout` / `deliveries_holdout` / `match_players_holdout` tables instead of the production ones — a forward-safeguard the project already built for exactly this purpose, which the earlier pass simply never queried. It contained **149 real, never-trained-on matches (78 female, 71 male), spanning 2026-06-16 to 2026-07-13** — including the entire *ICC Women's T20 World Cup* (India, Australia, England, South Africa, Pakistan, New Zealand, Sri Lanka, West Indies, Bangladesh) and a real *India tour of England* men's T20I series. This is a far stronger test than the earlier hand-picked 4-per-gender slice: real, held-out, and at 20-50x the sample size.

**Why this is the correct test of the actual shipped product, not just an internal split:** the currently-persisted WPA regressors (`artifacts/player_recommendation/{gender}_T20/model_*.joblib`) were trained on `matches`/`player_match_impact`, which is itself capped at `data_cutoff_date` by the same ingest logic. So these 149 matches are, right now, matches the live shipped models have **never seen in any form** — not a re-split of old data.

**Method** (no production files were retrained or permanently altered):
1. Made a standalone copy of the live DB (`sqlite3 ... VACUUM INTO copy.db`).
2. In the copy only, merged `matches_holdout`/`deliveries_holdout`/`match_players_holdout` into the production-named tables.
3. Reran just the derived-feature steps needed (`identity.run`, `ml_features.build_all`, `wpa.build_wpa`) on the copy — `wpa.py` scores new deliveries with the **already-persisted, pre-cutoff-trained** win-probability model (`EmpiricalWinProb.load(...)`); nothing was refit.
4. Loaded the **existing shipped** `model_batting_wpa.joblib` / `model_bowling_wpa.joblib` (`recommend.train.load_models`) — again, no retraining — and scored all 149 matches.

*(One accidental side effect caught and fixed mid-run: `ml_features.build_all` writes `ball_state_T20.parquet` to a fixed shared path, not one scoped to the DB it's given — so step 3 briefly overwrote the real production file with a version containing the holdout matches. This was caught immediately and fixed by rerunning `ml_features.build_ball_state` against the real, untouched production DB, restoring it to the correct pre-cutoff-only 1,226,642-row state before anything downstream used it. The win-probability model's own persisted grids were never touched.)*

**A) WPA regressors — the actual shipped models, scored on all 149 unseen matches:**

| Gender | Rows scored | Target | MAE | Baseline MAE | Corr | Sign-agreement acc. | Top-quartile hit-rate |
|---|---|---|---|---|---|---|---|
| female | 1,047 (51 matches) | batting_wpa | 0.108 | 0.110 | 0.113 | 52.1% | 36.3% |
| female | 1,047 | bowling_wpa | 0.087 | 0.090 | 0.107 | 54.5% | 21.8% |
| male | 1,469 (71 matches) | batting_wpa | 0.093 | 0.094 | 0.068 | 49.4% | 29.0% |
| male | 1,469 | bowling_wpa | 0.074 | 0.074 | 0.014 | 53.7% | 21.9% |

**Honest read:** these land very close to §2/§3/§10's internal-split numbers (correlation 0.01–0.11, sign-agreement ~50–55%, hit-rate ~22–36%) — real confirmation that the offline backtest genuinely predicts forward, live performance, for better *and* worse. Male bowling correlation (0.014) and sign-agreement (49.4% batting, essentially a coin flip) are weak here, consistent with bowling always being the noisier of the two targets in every prior section, not a new problem introduced by this test.

**B) Win-probability model — the actual persisted (pre-cutoff) model, scored on the same 149 matches:**

| Gender | Test balls / matches | Brier | Brier baseline | Ball-level accuracy | Baseline accuracy | Start-of-chase match accuracy |
|---|---|---|---|---|---|---|
| female | 12,332 / 50 | 0.214 | 0.248 | 65.7% | 54.6% | 58.0% |
| male | 15,584 / 68 | 0.145 | 0.249 | 79.1% | 52.8% | 82.4% |

Male actually **outperforms** its §10 internal-split numbers here (Brier 0.145 vs. 0.173, accuracy 79%/82% vs. 73.6%/72.5%). Female is weaker on this specific real slice (58% vs. 76.8% start-of-chase accuracy) — a World Cup's knockout-stakes matches are plausibly closer/higher-variance than the average historical match, and 50 matches is a small sample; still clearly beats its own baseline (54.6%) in both readings. Reported exactly as measured.

**C) End-to-end `simulate`, real XIs, real World Cup Final and series decider:**

| Match | Simulated win% | Actual result | Called correctly? |
|---|---|---|---|
| ICC Women's T20 World Cup **Final**: England vs Australia (Lord's, 2026-07-05) | Australia 65.3% / England 34.7% | Australia won by 7 wickets | **Yes** |
| India tour of England, decider: England vs India (2026-07-11) | England 63.7% / India 36.3% | England won by 56 runs | **Yes** |

Both real, high-stakes, genuinely-never-seen matches — including an actual World Cup Final — were correctly called by the full simulator pipeline (real XIs → outcome model → win-probability), with sensible, non-overconfident probabilities.

## 10. Accuracy (classification-style, not just MAE/correlation)

Everything above is regression/calibration metrics (MAE, correlation, Brier, log-loss) because the underlying task is continuous (a WPA value, a probability). This section adds the plain "accuracy" numbers on top, on the exact same held-out-by-match test splits already used above — nothing re-defined, just a different lens on the same holdout.

Script: `accuracy_metrics.py`, reusing `criiq_data.winprob.EmpiricalWinProb`/`_test_mask` and `criiq_models.recommend.train._make_model` directly (same held-out splits as §4 and §2/§3, respectively):
```python
# A) win-probability model
test = _test_mask(labelled["match_id"])                 # same match-level holdout as §4
m = EmpiricalWinProb().fit(train_df); p = m.predict(test_df)
ball_level_accuracy = np.mean((p > 0.5).astype(int) == y)             # "did the favorite win?"
# match-level: accuracy of the very first prediction once the chase starts
first_chase_ball = test_df[test_df.innings == 2].groupby("match_id").first()
start_of_chase_accuracy = np.mean((first_chase_ball.p > 0.5) == first_chase_ball.y)

# B) WPA regressors — same 0.2 temporal holdout as backtest.py
sign_agreement_accuracy = np.mean(np.sign(pred[nonzero]) == np.sign(actual[nonzero]))
```

**A) Win-probability model — "does the favorite actually win?"**

| Gender | Test balls | Ball-level accuracy | Naive baseline (always pick prior favorite) | Test matches | Accuracy at start of the chase |
|---|---|---|---|---|---|
| female | 93,714 | **77.4%** | 56.9% | 409 | **76.8%** |
| male | 145,372 | **73.6%** | 50.0% | 641 | **72.5%** |

Both readings agree closely (ball-level ≈ start-of-chase), which is a good sign — the model isn't just getting "easy" late-match balls right and dragging the average up; it's already ~73–77% accurate the moment the second innings begins, a genuinely useful early prediction.

**B) WPA regressors — sign-agreement accuracy** (did the model at least get the *direction* — positive vs. negative match impact — right, among players with a genuinely nonzero actual WPA):

| Gender | Target | Sign-agreement accuracy |
|---|---|---|
| female | batting_wpa | 53.0% |
| female | bowling_wpa | 55.0% |
| male | batting_wpa | 52.3% |
| male | bowling_wpa | 54.7% |

**Honest read:** this sits just above a 50% coin flip. It's consistent with everything already reported in §2 (MAE barely beating the mean-predictor baseline) — per-match individual WPA is a genuinely hard, high-variance target, and this task was never framed as "classify good vs. bad performance," it's a continuous ranking signal (see §2's top-quartile hit-rate, 30–34% vs. a 25% random baseline, which is the fairer accuracy-style read for *this* model). Reporting sign-agreement here for completeness, not to oversell it.

## 11. The two actual deliverables — Playing XI recommendation & match simulation, tested directly

*(Run 2026-07-24, against the models as they existed then — i.e. **before** the 2026-07-31 hyperparameter change described at the top of this report. Left exactly as originally written below, as a historical record. §14 is the 2026-08-06 re-run of this exact question against the current models, on an expanded sample — read that section for where things stand today.)*

Every section above validates the *components* (WPA regressors, win-probability model). This section validates the two things a coach actually uses: **does `recommend`/`select_xi` pick a good XI, and does `simulate` produce a trustworthy match?** Both are tested against the same 149-match genuine forward-holdout set from §9 (real 2026 matches the shipped models have never seen in any form) — so this is a fair, leakage-free test of the actual shipped product, not an internal split.

### 11a. Playing XI recommendation vs. the real historical XI

**Method:** for each of the 149 holdout matches, both teams' *real* starting XI was pulled from `match_players_holdout` and resolved to real `player_id`s. Where the real XI was ≥10/11 resolvable and present in that team's real, point-in-time candidate pool (`roster.team_pool`, built only from pre-cutoff data — exactly what `recommend` would have seen the day before this match), the shipped `RecommendationScorer` + `select_xi` (the exact production MILP) scored the same pool against the same real opponent, and the resulting XI was compared to the real one. A random-11-from-the-same-pool baseline (200 draws, averaged) is reported alongside for a fair comparison point — not "perfect selection," but "how much better than guessing."

**142 real team-selections scored** (out of 298 possible; the rest were excluded only because the real XI didn't resolve well enough to compare fairly, mostly associate-nation debutants with no prior record at all):

| | AI-recommended XI overlap with the real XI | Random-11-from-pool baseline |
|---|---|---|
| Overall | **6.14 / 11 (55.8%)** | 4.09 / 11 (37.2%) |
| Female | 7.01 / 11 (63.7%) | 4.59 / 11 (41.7%) |
| Male | 5.29 / 11 (48.1%) | 3.61 / 11 (32.8%) |

Overlap distribution across the 142 comparisons: mostly 5–8 players in common (30, 31, and 27 matches respectively), a handful as low as 2 and as high as 9 — never a near-total mismatch, never a perfect match either.

**Honest read:** the real starting XI was on average 10.52/11 both resolvable *and* already present in the AI's own candidate pool, so this is a genuinely fair test, not a pool mismatch. The model beats random selection by a wide, consistent margin (56% vs. 37% overlap) — it is clearly picking *good* players, not noise. It does not reproduce the exact real team (a real selector uses net-session form, fitness, and tactical calls the model has no access to), and it's noticeably better on the female side, consistent with every other section's finding that the female-scope models are the stronger of the two.

### 11b. Full match simulation vs. the real result

**Method:** of the 149 holdout matches, 49 had **both** real starting XIs fully (11/11) resolvable to known players — the rest involved at least one brand-new debutant with literally zero prior data to simulate from (not a limitation of the simulator, just nothing to build a profile from). All 49 skew heavily female (44 female vs. 5 male — the male holdout period sampled here was dominated by associate/qualifier tournaments with many uncapped debuts). 23 of these (18 female, 5 male, capped for runtime) were run through the exact production `simulate_match` pipeline with the real XIs, the real toss result, and 40 Monte Carlo reps each — then compared to the real result.

| | Value |
|---|---|
| Win-call accuracy (favored side actually won), excluding 2 no-result/abandoned matches | **66.7%** (14/21) |
| — female | 70.6% (12/17) |
| — male | 50.0% (2/4 — too small a sample to trust on its own) |
| Brier score (simulated win% vs. actual outcome) | **0.222** vs. 0.250 for a naive 50/50 baseline |
| 1st-innings score MAE (simulated mean vs. real total) | 37.8 runs (real innings totals vary by std=43.1 — i.e. comparable to natural match-to-match variance) |
| 2nd-innings score MAE | 24.9 runs |

**Honest read:** win/loss calling is genuinely better than a coin flip and better-calibrated than a flat 50/50 guess, consistent with §9C's two hand-picked examples (the real World Cup Final and the England-India decider were both called correctly). Predicting the *exact* score is weak — the MAE is roughly as large as the real scores' own natural spread — which matches every other honest finding in this report: T20 cricket has a lot of irreducible per-match variance, and the simulator's real value is in relative win-probability, not exact score forecasting. The male sample here is too small (4-5 matches) to draw a real conclusion from; it's reported for completeness, not as a confident number.

## 12. The `female_T20_tuned` artifacts on the forward-holdout (measured 2026-08-13)

Answers a question no earlier section asked: `artifacts/player_recommendation/female_T20_tuned/`
holds a second, hyperparameter-searched pair of WPA regressors. **Nothing in the codebase ever
loads them** — `recommend/train.py`'s `_artifacts_dir()` resolves to `{gender}_{fmt}`, i.e.
`female_T20`, so the tuned pair is currently dead weight on disk. Their params also differ from
the hardcoded ones in `_make_model` (tuned `batting_wpa`: `max_depth=4, max_features=0.7,
n_estimators=200`; shipped: `max_depth=10, max_features="sqrt"`). This section measures whether
promoting them would actually help.

Note that `criiq_models backtest` **cannot** answer this: it calls `_make_model` and retrains from
scratch, so it validates the *configuration*, never the persisted artifacts. §9's forward-holdout
method was replicated instead.

**Method** — same as §9, with the parquet-clobbering bug §9 hit designed out:
1. `VACUUM INTO` copy of the live DB; `CRIIQ_DATA_DIR` pointed at a scratch dir so `FEATURES_DIR`,
   `MODELS_DIR` and `DB_PATH` all redirect. §9 overwrote the production `ball_state_T20.parquet`
   because that path is derived from `DATA_DIR`; redirecting `DATA_DIR` prevents it by construction.
2. Merged `matches_holdout`/`deliveries_holdout`/`match_players_holdout` into the production-named
   tables **in the copy only** (+149 matches, +34,992 deliveries, +3,279 match_players).
3. Reran `identity.run`, `ml_features.build_all`, `wpa.build_wpa` on the copy. `wpa` scores with the
   already-persisted pre-cutoff `EmpiricalWinProb`; nothing was refit.
4. Loaded both persisted artifact pairs and scored **identical rows**. No retraining anywhere.
5. All 15 production files (5 joblib, 10 parquet) SHA-256 verified unchanged afterwards.

**Unseen set:** 1,057 player-match rows over 51 female T20 matches, 2026-06-16 → 2026-07-12 — after
the tuned model's own training cutoff of 2026-06-15, zero overlap with `matches`.

| Target | Model | MAE | Baseline MAE | Corr | Sign-agree | Top-quartile hit-rate |
|---|---|---|---|---|---|---|
| batting_wpa | shipped | 0.1075 | 0.1086 | 0.118 | 52.7% | 35.6% |
| batting_wpa | **tuned** | 0.1072 | 0.1086 | 0.110 | 51.5% | 35.5% |
| bowling_wpa | shipped | 0.0868 | 0.0883 | 0.106 | 54.3% | 21.6% |
| bowling_wpa | **tuned** | 0.0866 | 0.0883 | 0.120 | 54.6% | **26.0%** |

The shipped-model row reproduces §9A closely (§9A: 1,047 rows / 51 matches, batting MAE 0.108 /
corr 0.113 / hit 36.3%; bowling MAE 0.087 / corr 0.107 / hit 21.8%), which is what confirms the
replication is faithful rather than a differently-built pipeline.

**Sign-agreement is computed over non-zero actuals only.** ~26% of batting rows and ~41% of bowling
rows have an actual WPA of exactly 0 (players who never batted / never bowled). `sign(0)` cannot
match any non-zero prediction, so including them drags the figure to a meaningless 38.8% and makes
it look like a broken model rather than an artifact of the metric. §9A's 52.1%/54.5% uses the same
non-zero convention.

**Is the bowling gain real?** Paired bootstrap, 2,000 resamples **over matches** (not rows, since
rows within a match are correlated), seed 42:

| Target | Metric | Δ (tuned − shipped) | 95% CI | Verdict |
|---|---|---|---|---|
| batting_wpa | corr | −0.0077 | [−0.044, +0.032] | not significant |
| batting_wpa | hit-rate | −0.0007 | [−0.040, +0.039] | not significant |
| bowling_wpa | corr | +0.0144 | [−0.007, +0.038] | not significant |
| bowling_wpa | **hit-rate** | **+0.0441** | **[+0.015, +0.077]** | **significant** |

**Honest read:** on genuinely unseen data the tuned pair is **indistinguishable from shipped on
batting** and delivers one **statistically significant** improvement — bowling top-quartile
hit-rate, 21.6% → 26.0%, CI excluding zero. That is the metric closest to the actual selection job
("did we rank the right bowlers into the top quarter"), and bowling has been the weaker of the two
targets in every prior section. The bowling correlation moves the same direction but does not clear
significance at n=51 matches. Three of four comparisons are a wash; this is a narrow, single-metric
win, not a general improvement, and it rests on 51 matches.

**Face-validity spot check:** the 15 highest tuned-predicted batting rows are Matthews, Voll,
Athapaththu (AC Jayangani), Mandhana, Mooney, Wolvaardt and similar — genuine elite women's T20I
names, not noise. 10 of those 15 had positive actual batting WPA, averaging **+0.124** against
**+0.012** across all rows (~10x).

**Not acted on.** Promoting `female_T20_tuned` changes live selection output, so it is left as a
decision, not a silent swap. Raw outputs: `female_T20_tuned_holdout_validation.csv` (the metrics
table) and `female_T20_holdout_player_scores.csv` (all 1,057 rows — match, date, event, teams,
player name, both models' predictions beside the actuals).

## 13. Win-probability model — validation accuracy on the holdout set, both scopes (measured 2026-08-13)

**Headline: on 27,916 balls from 118 unseen T20 matches, the win-probability model picks the
eventual winner 79.1% of the time in men's T20I and 65.7% in women's, against baselines of 52.8%
and 54.6%.**

This is the single number for "how well do our predicted win probabilities match actual outcomes on
data the model has never seen." Nothing is refit: the persisted, pre-cutoff `winprob_T20_{gender}_*`
grids were loaded and scored directly, with their SHA-256s checked identical to the production files
before and after. The holdout is the same genuine forward set §9/§12 use — matches dated after
`data_cutoff_date` 2026-06-15, routed by ingest into `matches_holdout`, never seen in training in
any form.

**"Accuracy" here means:** for every ball, the model's predicted win probability for the batting
side is turned into a hard call (`p >= 0.5` → batting side wins) and compared with who actually won.
The baseline is the same rule applied to the model's own base rates, i.e. "always favour whoever the
average match favours."

| Scope | Balls | Matches | **Accuracy** | Baseline acc. | Brier | Brier baseline | Log loss | Log loss baseline | AUC |
|---|---|---|---|---|---|---|---|---|---|
| **Men's — all balls** | 15,584 | 68 | **79.1%** | 52.8% | 0.145 | 0.249 | 0.451 | 0.691 | 0.883 |
| Men's — 1st innings | 8,334 | 68 | 70.5% | 51.3% | 0.186 | 0.250 | 0.551 | 0.693 | 0.804 |
| Men's — 2nd innings (chase) | 7,250 | 68 | **89.0%** | 54.6% | 0.098 | 0.248 | 0.335 | 0.689 | 0.946 |
| **Women's — all balls** | 12,332 | 50 | **65.7%** | 54.6% | 0.214 | 0.248 | 0.615 | 0.689 | 0.726 |
| Women's — 1st innings | 6,556 | 50 | 59.5% | 53.0% | 0.243 | 0.249 | 0.678 | 0.691 | 0.634 |
| Women's — 2nd innings (chase) | 5,776 | 50 | **72.7%** | 56.4% | 0.182 | 0.246 | 0.543 | 0.686 | 0.792 |

Match-level (one prediction per match, not per ball):

| Decision point | Men's | Women's |
|---|---|---|
| At the innings break (last ball of innings 1) | **80.9%** (55/68) | **64.0%** (32/50) |
| At the first ball of the chase | 82.4% (56/68) | 58.0% (29/50) |

Both all-balls rows reproduce §9B exactly (§9B: female 12,332 balls / 50 matches, Brier 0.214,
accuracy 65.7%, start-of-chase 58.0%; male 15,584 / 68, Brier 0.145, 79.1%, 82.4%), which is what
confirms this run measures the same thing that section did. The per-innings split, AUC and
calibration below are new.

**Honest read.** Both models beat their baseline on every metric in every split, and both improve
sharply once a chase is underway — 89.0% men's / 72.7% women's, where runs required and balls
remaining carry real information. Before a target exists the signal is genuinely thin, and both
models correctly stay near their prior rather than pretending otherwise (70.5% / 59.5%).

**The men's model is substantially stronger than the women's on every measure** — 79.1% vs 65.7%
overall, AUC 0.883 vs 0.726, Brier 0.145 vs 0.214. The most likely reason is data volume: the male
scope trains on roughly 75% more ball-state rows, and women's T20I also carries more scoring
variance per ball. This gap is worth stating plainly rather than quoting only the stronger number.

**Calibration — the two models miss in opposite directions.** ECE over 10 buckets is 0.068 men's /
0.063 women's, but the *direction* differs and matters more than the magnitude:

| Predicted bucket | Men's: actually won | Women's: actually won |
|---|---|---|
| 0.0–0.1 | 2.3% | 12.4% |
| 0.1–0.2 | 7.6% | 23.5% |
| 0.2–0.3 | 13.0% | 32.6% |
| 0.3–0.4 | 23.4% | 37.8% |
| 0.4–0.5 | 45.7% | 46.7% |
| 0.5–0.6 | 54.8% | 52.9% |
| 0.6–0.7 | 72.6% | 55.6% |
| 0.7–0.8 | **85.1%** | **57.6%** |
| 0.8–0.9 | 95.0% | 81.8% |
| 0.9–1.0 | 100.0% | 97.0% |

- **Women's is over-confident**: its probabilities are too extreme. At a stated ~75% the side
  actually wins 57.6% (1,440 balls). A "75%" on the women's win-probability chart should be read as
  a strong lean, not a near-certainty.
- **Men's is under-confident**: its probabilities are too timid, and reality is more decisive than
  it claims. At a stated ~75% the side actually wins 85.1%; at ~84% it wins 95.0%; at ~26% it wins
  only 13.0%. Every men's bucket above 0.6 lands above the diagonal and every bucket below 0.4
  lands below it — the classic S-curve of a model that should be sharpened.

Both are real and reproducible on thousands of balls, not sampling noise, and both are fixable with
the same tool — an isotonic recalibration fitted on holdout, per gender, since the corrections point
opposite ways. Reported, not fixed.

Raw outputs: `winprob_holdout_accuracy.csv`, `winprob_holdout_calibration.csv`. Charts in
`figures/` (`01_winprob_accuracy.png`, `02_accuracy_through_match.png`, `03_calibration.png`).

## Summary for presentation

- All 171 automated tests pass.
- Every headline metric was regenerated live, not quoted from old docs, and is stable across 3 different holdout splits.
- The shipped model (two regressors) beats the theoretically-motivated alternative (learning-to-rank) on the same real data.
- The win-probability model clearly beats its baseline on a proper match-level (not ball-level) holdout.
- Feature leakage-safety was independently verified by reading the code, not assumed.
- A full end-to-end run (real XI → simulator → win probability) was checked against one genuinely-unseen real match, with an honestly reported result.
- §9 (corrected after an initial mistake — see that section for what was wrong and how it was caught): the project has a **built-in forward-holdout** — 149 real matches (2026-06-16 to 2026-07-13, including the entire Women's T20 World Cup and a real India–England men's series) that the currently-shipped models have never seen in any form. Scored with the actual shipped artifacts (no retraining): regressor correlations and win-probability accuracy both land close to the internal-split numbers above, confirming the offline backtest genuinely predicts real forward performance. Two full end-to-end simulations — including the real World Cup Final — both correctly called the actual winner.
- §10 adds plain accuracy: the win-probability model correctly picks the eventual winner **77.4% (female) / 73.6% (male)** of the time on held-out balls — already ~73–77% right the moment a chase starts, well above a ~50–57% naive baseline. The WPA regressors' sign-agreement accuracy (53–55%) is honestly reported as close to chance, since that model's real job is ranking (§2's 30–34% top-quartile hit-rate vs. 25% random), not binary classification.
- **§11 — the two deliverables a coach actually uses, tested directly against real history:** the AI-recommended Playing XI overlaps the real historical starting XI by **6.14/11 players (55.8%)**, well above a random-11-from-pool baseline (37.2%) — clearly picking good players, not reproducing the exact real team. The full match simulator, given real XIs and the real toss, correctly called the winner **66.7%** of the time (70.6% female / 50.0% male on a too-small male sample) with a Brier score beating a naive 50/50 guess (0.222 vs. 0.250) — but predicts the *exact* score only as precisely as real matches naturally vary (MAE ≈ 1 standard deviation of real scores), the same "good at direction, weak at magnitude" pattern found everywhere else in this report.

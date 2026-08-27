# CRIIQ

CRIIQ is a data-driven team selection and analytics tool for cricket coaches and selectors, covering both women's and men's T20I. Given a team, an opponent, and a venue, it proposes a balanced Playing XI with plain-language reasoning for every pick, runs a ball-by-ball Monte Carlo simulation of the resulting match, and optimizes batting order and bowling rotation with two genetic algorithms — all backed by models trained on real Cricsheet ball-by-ball history, not hand-tuned heuristics.

It grew out of a final-year project and is built as three independently deployable pieces sharing one analytics database: a React dashboard for coaches, a FastAPI backend, and a Python model/simulation package that the backend calls out to as a subprocess.

## What it does

- **Playing XI recommendation** — scores every eligible player for a specific (team, opponent, venue) matchup and selects the constrained best 11 with a MILP solver, including a head-to-head matrix against the named opposition XI and, for lopsided matchups, a rotation XI resting the top performers.
- **Analyze your own XI** — scores a coach's hand-picked 11 against the same rules the recommender uses, and shows exactly which swaps would close the gap to the optimal side.
- **Match simulation** — a ball-by-ball Monte Carlo engine (Law-compliant overs, no-ball/free-hit handling, Super Overs) that plays out a hypothetical match between two named XIs and reports scorecards, win-probability timeline, and key moments.
- **Lineup optimization** — two genetic algorithms search for the batting order and bowler-to-over rotation that perform best against a specific opponent, with an explainability layer comparing each result to a naive baseline.
- **Player analytics** — career, form, phase splits, venue and opponent history, dismissal matchups, and per-prediction SHAP attribution for every player in the database.

Every recommendation traces back to a transparent, additive score (model prediction, matchup history, phase fit, standing, risk) rather than a black-box number — see `model-training/ALGORITHMS.md` for the full formulation.

## Architecture

```
frontend/ (React + Vite)  --HTTP/JSON-->  backend/ (FastAPI)  --subprocess-->  model-training/ (criiq_models CLI)
                                                |                                       |
                                                +---------------- read-only ------------+
                                                                   |
                                                        data-collection/data/criiq.db
```

The backend never imports the model package directly — it shells out to `python -m criiq_models.cli ...` in that package's own virtual environment and reads its JSON output. This keeps the ML dependency stack (scikit-learn, shap, scipy) out of the backend's environment and means a crash inside a simulation or a genetic-algorithm run can't take the API server down with it.

`criiq.db` is built entirely offline by the `data-collection` pipeline from Cricsheet ball-by-ball data; both the backend and `model-training` only ever read it.

## Repository layout

| Directory | Contents |
|---|---|
| `frontend/` | React + TypeScript coach dashboard and admin console |
| `backend/` | FastAPI service — auth, squads, matches, and the bridge into `model-training` |
| `model-training/` | The recommendation engine, simulator, and genetic-algorithm optimizers (`criiq_models`) |
| `data-collection/` | The pipeline that builds `criiq.db` from Cricsheet (and optional ESPNcricinfo enrichment) |
| `rulebook-cricket.md` | The cricket rules the match simulator is checked against |
| `WORKING.md` | End-to-end trace of every user-facing feature across all three layers |

Each package has its own README with setup instructions specific to it.

## Getting started

### With Docker

```bash
cp .env.example .env   # set a real JWT_SECRET before this leaves localhost
docker compose up --build
```

This builds and starts the backend (`localhost:8000`) and frontend (`localhost:5173`). It expects `data-collection/data/criiq.db` and `model-training/artifacts/` to already exist locally — they're mounted in, not baked into the images. To build `criiq.db` from scratch:

```bash
docker compose run --rm data-collection refresh
```

### Running each package locally

```bash
# 1. Build the analytics database (one-time, ~2 minutes)
cd data-collection && pip install -r requirements.txt && python run.py refresh

# 2. Train the models (each gender scope trains independently)
cd ../model-training && pip install -r requirements.txt
python -m criiq_models.cli train --gender female
python -m criiq_models.cli train --gender male

# 3. Run the backend
cd ../backend && pip install -r requirements.txt && uvicorn main:app --reload

# 4. Run the frontend
cd ../frontend && npm install && npm run dev
```

Interactive API docs are served at `http://localhost:8000/docs` once the backend is running.

## Does it actually work

Tested against real, held-out 2026 matches the models never trained on (`model-training/VALIDATION_REPORT.md`, section 11):

- The recommended Playing XI overlaps the real historical starting XI **55.8%** of the time, against a **37.2%** random baseline.
- Given real starting XIs and the real toss result, the match simulator calls the winner correctly **66.7%** of the time, with a Brier score of **0.222** against a **0.250** naive baseline.

Neither result reproduces reality exactly, and both are documented with full methodology, sample sizes, and honest caveats in that report rather than presented as a finished product.

## Further documentation

| Document | Covers |
|---|---|
| `WORKING.md` | What code actually runs, end to end, when a user does X |
| `model-training/ALGORITHMS.md` | The math: the MILP, the two genetic algorithms, WPA regression, Monte Carlo simulation, SHAP |
| `model-training/CODE_WALKTHROUGH.md` | File-by-file reference for `model-training/criiq_models/` |
| `data-collection/CODE_WALKTHROUGH.md` | File-by-file reference for `data-collection/criiq_data/` |
| `model-training/VALIDATION_REPORT.md` | Accuracy against real historical matches |
| `data-collection/dataset_analysis.ipynb` | Shape, size, and outlier analysis of the underlying dataset |

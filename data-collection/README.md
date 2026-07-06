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
| `player_registry` | eligibility per player/format: retirement/activity status, recall flag, age advisory, career phase, ICC rank |
| `icc_rankings` | ICC player rank + rating per format/discipline (loaded from a CSV) |
| `player_career` | full career batting (avg/SR/HS/50s/100s) **and** bowling (overs/wickets/economy/avg/SR/best) per player/format |
| `player_cards` | dashboard-ready cards: career totals, latest score, form/RFI, team impact, H2H |
| `player_advanced` | derived strengths: phase splits, control/aggression, archetype, bowling usage, vs-pace/spin, vs-LHB/RHB |
| `player_vs_opponent` | full batting+bowling record vs **each opponent** + W/L + Player-of-the-Match |
| `player_impact` | match-impact & importance: contribution share, partnership-breaking, top-order scalps, win contribution, PotM, setting-vs-chasing, importance score |
| `player_phase` | phase split (PP/middle/death) batting+bowling with **rank within own team** |
| `player_by_venue` | batting+bowling performance **at each ground** |
| `dismissal_matchup` | batter-vs-bowler dismissals — **bogey bowler** (overall + per opponent) and favourite victims |
| `match_features` | **win/loss prediction** training table: leakage-safe pre-match form, H2H, toss + label |
| `player_match_impact` | per-player per-match contribution + result label |
| `ball_state` (parquet, `data/features/`) | per-ball in-game state + outcome label for **live win-probability** models |
| `player_styles` | bowling style / batting hand / role + provenance |
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
python -m criiq_data.cli rankings --scaffold    # write ICC rankings CSV template
python -m criiq_data.cli rankings               # load data/rankings/icc_rankings.csv

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
python -m criiq_data.cli ml                      # win/loss + ball-state + per-match impact (model-ready)
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

The phase/control/aggression metrics above are the genuine, defensible
equivalents derived from ball-by-ball. If a board supplies a proprietary feed,
it can be wired into a dedicated table without touching the derived profile.

### Retirement, age & ICC rank

The registry no longer marks everyone `UNKNOWN`. Status is inferred from activity:

- **ACTIVE** — present in an ICC ranking, or appeared within ~18 months
- **INACTIVE** — no appearance for 3+ years (likely retired/dropped)
- **UNKNOWN** — in between, no positive signal

Age advisory and career phase are role-specific (fast bowler threshold 38, others
40; phase bands per role). Age comes from the Wikidata DOB seed (partial coverage),
so phase/advisory populate only where DOB is known.

**ICC rank** is a strong active signal (retired players drop off ICC lists). Live
ICC rankings load from a tenant-authenticated feed that isn't openly accessible, so
rank is a **pluggable CSV**: `rankings --scaffold` writes `data/rankings/icc_rankings.csv`
(columns: format, gender, discipline, rank, rating, player_name, key_cricinfo); fill
it (ICC lists are only the top ~100 per category) and `rankings` loads it. Ranked
players are then marked ACTIVE and carry their rank/rating.

## Player styles workflow (for the vs-pace/spin & LHB/RHB splits)

Bowling style and batting hand are **not** in Cricsheet, and ESPNcricinfo blocks
scraping. Wikidata (via the ESPNcricinfo-id property) supplies **nationality**
and **partial role** but not style/hand. So:

1. `styles --seed` — pulls role/nationality from Wikidata (free, legal, partial).
2. `styles --scaffold` — writes `data/styles/player_styles.csv` pre-filled with
   `key_cricinfo` + name for every player; fill `bowling_style`, `batting_hand`,
   `playing_role` (the active pool is a few hundred rows).
3. `styles --load` (also run automatically by `refresh`) — merges the CSV; then
   `advanced` recomputes and the vs-pace/spin + vs-RHB/LHB splits populate.

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

// Adapters from the backend's raw JSON shapes (see ../../../backend/players.py,
// matches.py, and the data-collection card/career/phase builders) onto the
// frontend's existing `Player`/`Match` types (types/index.ts), so every page
// and component keeps rendering the exact same shape it always has.

import { Match, Player, PlayerStatus } from "../types/index";

const PALETTE = ["#60A5FA", "#34D399", "#F59E0B", "#EC4899", "#A78BFA", "#FB923C", "#2DD4BF", "#818CF8", "#F87171", "#86EFAC"];

export function colorFor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  return PALETTE[hash % PALETTE.length];
}

export function initialsFor(name: string): string {
  return name.trim().split(/\s+/).map(w => w[0]).join("").toUpperCase().slice(0, 3) || "?";
}

function normalizeHand(raw?: string | null): "Right" | "Left" {
  if (raw && /left|lhb/i.test(raw)) return "Left";
  return "Right";
}

const ROLE_DISPLAY: Record<string, string> = {
  batter: "Batsman", batsman: "Batsman", bowler: "Bowler",
  "all-rounder": "All-rounder", allrounder: "All-rounder",
  wicketkeeper: "Wicket-keeper", "wicket-keeper": "Wicket-keeper",
};

function displayRole(raw?: string | null): string {
  if (!raw) return "Batsman";
  return ROLE_DISPLAY[raw.toLowerCase()] ?? raw;
}

function isBattingRole(role: string): boolean {
  return role === "Batsman" || role === "Wicket-keeper";
}

function clamp01to100(n: number | null | undefined, fallback = 50): number {
  if (n === null || n === undefined || Number.isNaN(n)) return fallback;
  return Math.max(0, Math.min(100, Math.round(n)));
}

/** GET /players list item -> Player. Leaner than the detail response (no
 * phase/vs-opponent breakdown — only /players/{id} and /players/{id}/vs/
 * {opponent} compute those), but career is the same real card_json.career
 * nested shape the detail endpoint returns, so PlayerCard's Stats expander
 * shows real matches/runs/avg/SR (or wkts/econ/best), not zeroes. */
export function mapApiPlayerListItem(api: any): Player {
  const role = displayRole(api.role);
  const last5: number[] = Array.isArray(api.last5_scores) ? api.last5_scores : [];
  const career = api.career || {};
  const bat = career.batting || {};
  const bowl = career.bowling || {};
  return {
    id: String(api.id), name: api.name, role, archetype: role,
    battingHand: normalizeHand(api.batting_hand), bowlingStyle: api.bowling_style || "—",
    status: (api.status as PlayerStatus) || "UNKNOWN", team: api.country || "—",
    initials: initialsFor(api.name), color: colorFor(String(api.id)),
    isBatsman: isBattingRole(role),
    recentForm: last5, recentSR: [],
    // Not available from the list endpoint (only single-player detail/vs
    // endpoints compute these) — neutral defaults, not fabricated numbers.
    vsOpponent: 0, vsInsight: "Open the player profile for a full breakdown.",
    powerplay: 0, middle: 0, death: 0,
    career: {
      matches: bat.innings ?? bowl.innings ?? 0,
      innings: bat.innings ?? 0, runs: bat.runs, avg: bat.average, sr: bat.strike_rate,
      fifties: bat.fifties, hundreds: bat.hundreds,
      wickets: bowl.wickets, economy: bowl.economy, bowlingAvg: bowl.average, best: bowl.best_bowling,
    },
    score: clamp01to100(api.form_score, 0),
    breakdown: { form: clamp01to100(api.form_score, 0), vsOpponent: 0, venueFit: 0, matchupAdvantage: 0 },
    position: api.position || "—", isKeeper: !!api.is_keeper,
  };
}

/** GET /players/{id} -> Player. Full card: identity, career, phase splits,
 * archetype and importance score are all real backend-computed fields. */
export function mapApiPlayerDetail(api: any): Player {
  const identity = api.identity || {};
  const role = displayRole(identity.role);
  // Both trimmed to the same last-5 window as api.recent_matches (real
  // per-match player_match_impact rows, oldest -> newest) so recentForm[i]
  // and recentSR[i] describe the same match.
  const lastInnings: number[] = (api.form?.last_innings || []).slice(-5);
  const recentMatches: any[] = api.recent_matches || [];
  const career = api.career || {};
  const bat = career.batting || {};
  const bowl = career.bowling || {};

  const phaseValue = (phase: string): number => {
    const row = (api.phases || []).find((p: any) => p.phase === phase);
    if (!row) return 0;
    // bat_team_percentile is the only 0-100 ranking column the pipeline
    // produces; bowling-only players fall back to an economy-based estimate.
    if (row.bat_team_percentile != null) return clamp01to100(row.bat_team_percentile);
    if (row.bowl_economy != null) return clamp01to100(100 - row.bowl_economy * 10);
    return 0;
  };

  return {
    id: String(api.id), name: identity.name || "Unknown player", role, archetype: api.archetype || role,
    battingHand: normalizeHand(identity.batting_hand), bowlingStyle: identity.bowling_style || "—",
    status: (api.status?.retirement_status as PlayerStatus) || "UNKNOWN",
    team: identity.nationality || "—",
    initials: initialsFor(identity.name || "?"), color: colorFor(String(api.id)),
    isBatsman: isBattingRole(role),
    recentForm: lastInnings,
    recentSR: recentMatches.map((m: any) => (isBattingRole(role) ? m.bat_strike_rate : m.economy) ?? 0),
    // vs-opponent is a separate endpoint (GET /players/{id}/vs/{opponent});
    // this default is replaced once that call resolves.
    vsOpponent: 0, vsInsight: (api.strengths_summary || [])[0] || "No scouting note yet.",
    powerplay: phaseValue("powerplay"), middle: phaseValue("middle"), death: phaseValue("death"),
    career: {
      matches: api.impact?.matches ?? bat.innings ?? bowl.innings ?? 0,
      innings: bat.innings ?? 0, runs: bat.runs, avg: bat.average, sr: bat.strike_rate,
      fifties: bat.fifties, hundreds: bat.hundreds,
      wickets: bowl.wickets, economy: bowl.economy, bowlingAvg: bowl.average, best: bowl.best_bowling,
    },
    score: clamp01to100(api.importance_score, 50),
    breakdown: {
      form: clamp01to100(api.form_percentile, 50), vsOpponent: 0,
      venueFit: 0, matchupAdvantage: clamp01to100(api.importance_score, 50),
    },
    position: api.position || "—", isKeeper: !!api.is_keeper,
  };
}

/** GET /players/{id}/vs/{opponent} (player_vs_opponent table row) -> patches
 * the vsOpponent/vsInsight fields of an already-mapped Player. There's no
 * single "rating" column, so vsOpponent is derived from win_pct (falling
 * back to batting average against a generic 35-run benchmark). */
export function applyVsOpponent(player: Player, api: any, opponent: string): Player {
  const vsOpponent = api.win_pct != null
    ? clamp01to100(api.win_pct * 100)
    : api.bat_average != null
      ? clamp01to100((api.bat_average / 35) * 100)
      : player.vsOpponent;

  const parts: string[] = [];
  if (api.matches) parts.push(`${api.matches} matches vs ${opponent}`);
  if (api.runs != null) parts.push(`${api.runs} runs at avg ${api.bat_average ?? "—"} (SR ${api.bat_strike_rate ?? "—"})`);
  if (api.wickets != null) parts.push(`${api.wickets} wickets at econ ${api.economy ?? "—"}`);
  const vsInsight = parts.length ? parts.join(". ") + "." : player.vsInsight;

  return { ...player, vsOpponent, vsInsight };
}

const fmtDate = (iso: string): string => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
};

const toFormArray = (last5: string): ("W" | "L")[] =>
  last5.split("").filter(c => c === "W" || c === "L") as ("W" | "L")[];

/** Both /matches list entries and /matches/{id} detail map through here. */
export function mapApiMatch(api: any): Match {
  const status: Match["status"] =
    api.status === "upcoming" ? "Upcoming" : api.status === "completed" || api.result ? "Completed" : "Upcoming";
  return {
    id: String(api.id ?? api.match_id), team1: api.team1, team2: api.team2,
    venue: api.venue || api.venue_raw || "TBC", date: fmtDate(api.date), time: "TBC",
    format: api.format || "T20I", status, result: api.result || undefined,
    opponentForm: toFormArray(api.team2_last5 || api.team1_last5 || ""),
    gender: api.gender === "male" ? "male" : "female",
  };
}

import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useLocation } from "react-router";
import { PlayCircle, Wind, ListOrdered, RefreshCw, Search, Check } from "lucide-react";
import * as api from "../lib/api";
import { mapApiPlayerListItem } from "../lib/mappers";
import { Player } from "../types/index";
import { WinProbChart } from "../components/match/WinProbChart";
import { Scorecard } from "../components/match/Scorecard";

const TEAM_OPTS = ["India", "Australia", "England", "South Africa", "New Zealand", "Pakistan"];

export interface SimulatorPrefill {
  team1: string; team2: string; team1PlayerIds: string[]; team2PlayerIds: string[]; gender: "female" | "male";
}

// Each XI picker must show that specific team's (and gender's) real roster,
// not one shared unfiltered list -- reusing a single global player fetch
// across every picker (the previous version of this page) meant "India XI"
// and "Australia XI" showed the exact same players regardless of team.
function useTeamRoster(team: string, gender: "female" | "male") {
  const [players, setPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.listPlayers({ country: team, gender, limit: 100 })
      .then(res => { if (!cancelled) setPlayers(res.players.map(mapApiPlayerListItem)); })
      .catch(() => { if (!cancelled) setPlayers([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [team, gender]);
  return { players, loading };
}

// XIs are tracked by real player_id (never by display name) -- names can be
// genuinely ambiguous (two different real players sharing a short name,
// e.g. "A Reddy"), which the model correctly refuses to guess and surfaced
// as a hard "matches multiple players" error when this page sent names.
function XIPicker({ label, players, loading, selectedIds, onChange, onUseRecommended, recommendedLoading }: {
  label: string; players: Player[]; loading: boolean; selectedIds: string[]; onChange: (ids: string[]) => void;
  onUseRecommended?: () => void; recommendedLoading?: boolean;
}) {
  const [search, setSearch] = useState("");
  const filtered = players.filter(p => p.name.toLowerCase().includes(search.toLowerCase()));
  // Each picker auto-fills the AI's recommended XI, so it sits at 11/11 by
  // default. Adding a 12th is (correctly) refused, but silently -- surface
  // that state so a manual "tap to add" click doesn't look like a dead list.
  const atCap = selectedIds.length >= 11;
  const toggle = (id: string) => {
    if (selectedIds.includes(id)) onChange(selectedIds.filter(x => x !== id));
    else if (selectedIds.length < 11) onChange([...selectedIds, id]);
  };
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-1">
        <h4 className="text-[13px] font-semibold text-foreground">{label}</h4>
        <span className={`text-[11px] font-medium ${selectedIds.length === 11 ? "text-[#AAFF57]" : "text-muted-foreground"}`}>{selectedIds.length}/11</span>
      </div>
      <div className="flex items-center gap-3 mb-2">
        {onUseRecommended && (
          <button onClick={onUseRecommended} disabled={recommendedLoading}
            className="text-[10px] text-[#AAFF57] hover:underline disabled:opacity-50 disabled:no-underline">
            {recommendedLoading ? "Scoring squad vs this opponent… (~15-20s)" : "↺ Reset to AI's recommended XI"}
          </button>
        )}
        {selectedIds.length > 0 && (
          <button onClick={() => onChange([])}
            className="text-[10px] text-muted-foreground hover:text-foreground hover:underline">
            ✕ Clear XI (pick your own)
          </button>
        )}
      </div>
      {atCap && (
        <p className="text-[10px] text-amber-400 mb-2">XI full (11/11) — tap a highlighted player to remove one before adding another.</p>
      )}
      <div className="relative mb-2">
        <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search players…"
          className="w-full pl-7 pr-2 py-1.5 text-[12px] bg-secondary border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40 text-foreground placeholder:text-muted-foreground" />
      </div>
      <div className="max-h-48 overflow-auto space-y-1 pr-1">
        {loading ? (
          <p className="text-[11px] text-muted-foreground text-center py-3">Loading roster…</p>
        ) : filtered.map(p => {
          const isSel = selectedIds.includes(p.id);
          return (
            <button key={p.id} onClick={() => toggle(p.id)} disabled={atCap && !isSel}
              className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left transition-colors ${isSel ? "bg-[#AAFF57]/10 border border-[#AAFF57]/30" : atCap ? "border border-transparent opacity-40 cursor-not-allowed" : "hover:bg-secondary border border-transparent"}`}>
              <div className="w-5 h-5 rounded-full flex items-center justify-center text-[8px] font-bold flex-shrink-0" style={{ backgroundColor: p.color + "33", color: p.color }}>{p.initials}</div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="text-[12px] text-foreground truncate">{p.name}</span>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded-full flex-shrink-0 ${p.status === "ACTIVE" ? "bg-[#5FA800]/15 text-[#5FA800]" : p.status === "INCONSISTENT" ? "bg-amber-500/15 text-amber-400" : "bg-secondary text-muted-foreground"}`}>
                    {p.status}
                  </span>
                </div>
                <span className="text-[10px] text-muted-foreground">{p.position}</span>
              </div>
              {isSel && <Check size={12} className="text-[#AAFF57] flex-shrink-0" />}
            </button>
          );
        })}
        {!loading && filtered.length === 0 && <p className="text-[11px] text-muted-foreground text-center py-3">No players found for this team</p>}
      </div>
    </div>
  );
}

// The AI's own constrained-optimal XI for `team` vs `opponent` (the same
// `select_xi` MILP `recommend` uses -- see model-training/simulation_demo.
// ipynb's "Build two Playing XIs -- the model's own optimal recommendation
// by default" cell) -- used to pre-fill a picker instead of leaving it empty
// and forcing a manual 11-player pick every time a team is chosen.
// Scoring a team's full pool against a specific opponent is real model work
// (~15-20s measured) -- cache by (team, opponent, gender) at module scope so
// switching back to a combo already computed this session is instant instead
// of re-running the same scoring pass.
const recommendedXICache = new Map<string, string[]>();

function useRecommendedXI(team: string, opponent: string, gender: "female" | "male") {
  const cacheKey = `${team}|${opponent}|${gender}`;
  const [ids, setIds] = useState<string[]>(() => recommendedXICache.get(cacheKey) ?? []);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!team || !opponent || team === opponent) { setIds([]); return; }
    const cached = recommendedXICache.get(cacheKey);
    if (cached) { setIds(cached); return; }
    let cancelled = false;
    setLoading(true);
    api.recommendations({ team, opponent, gender })
      .then(res => {
        const xiIds = res.recommendations.filter(r => r.in_xi).map(r => r.player_id);
        recommendedXICache.set(cacheKey, xiIds);
        if (!cancelled) setIds(xiIds);
      })
      .catch(() => { if (!cancelled) setIds([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [team, opponent, gender]); // eslint-disable-line react-hooks/exhaustive-deps
  return { ids, loading };
}

function TeamPicker({ value, onChange, opts, label }: { value: string; onChange: (v: string) => void; opts: string[]; label: string }) {
  return (
    <div className="flex-1 space-y-1">
      <label className="text-[11px] text-muted-foreground">{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)}
        className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
        {opts.map(o => <option key={o}>{o}</option>)}
      </select>
    </div>
  );
}

function SimulateTab({ gender, prefill }: { gender: "female" | "male"; prefill?: SimulatorPrefill }) {
  const [team1, setTeam1] = useState(prefill?.team1 ?? "India");
  const [team2, setTeam2] = useState(prefill?.team2 ?? "Australia");
  const [team1Players, setTeam1Players] = useState<string[]>(prefill?.team1PlayerIds ?? []);
  const [team2Players, setTeam2Players] = useState<string[]>(prefill?.team2PlayerIds ?? []);
  const team1Roster = useTeamRoster(team1, gender);
  const team2Roster = useTeamRoster(team2, gender);
  // Default each side to the AI's own recommended XI (mirrors simulation_demo
  // .ipynb's "the model's own optimal recommendation by default") instead of
  // an empty picker that forces a manual 22-player selection every time.
  const recommended1 = useRecommendedXI(team1, team2, gender);
  const recommended2 = useRecommendedXI(team2, team1, gender);
  // Skip the very first auto-fill when a prefill already set up an exact XI
  // (from "Simulate This XI" on Recommendations) -- otherwise it would be
  // immediately overwritten by this hook re-deriving the same recommendation.
  const [skipAutoFill1, setSkipAutoFill1] = useState(!!prefill);
  const [skipAutoFill2, setSkipAutoFill2] = useState(!!prefill);
  useEffect(() => {
    if (skipAutoFill1) { setSkipAutoFill1(false); return; }
    if (recommended1.ids.length === 11) setTeam1Players(recommended1.ids);
  }, [recommended1.ids]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (skipAutoFill2) { setSkipAutoFill2(false); return; }
    if (recommended2.ids.length === 11) setTeam2Players(recommended2.ids);
  }, [recommended2.ids]); // eslint-disable-line react-hooks/exhaustive-deps
  const [nSims, setNSims] = useState(20);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);

  const run = async () => {
    setLoading(true); setError(null);
    try {
      const res = await api.simulateMatch({
        team1, team2, team1_player_ids: team1Players, team2_player_ids: team2Players,
        toss_winner: team1, n_simulations: nSims, gender,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Simulation failed");
    } finally {
      setLoading(false);
    }
  };

  const canRun = team1Players.length === 11 && team2Players.length === 11 && !loading;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div className="space-y-3">
        <div className="flex gap-3">
          <TeamPicker label="Team 1 (bats first, wins toss)" value={team1} onChange={setTeam1} opts={TEAM_OPTS.filter(o => o !== team2)} />
          <TeamPicker label="Team 2" value={team2} onChange={setTeam2} opts={TEAM_OPTS.filter(o => o !== team1)} />
        </div>
        <XIPicker label={`${team1} XI`} players={team1Roster.players} loading={team1Roster.loading} selectedIds={team1Players} onChange={setTeam1Players}
          onUseRecommended={() => setTeam1Players(recommended1.ids)} recommendedLoading={recommended1.loading} />
        <XIPicker label={`${team2} XI`} players={team2Roster.players} loading={team2Roster.loading} selectedIds={team2Players} onChange={setTeam2Players}
          onUseRecommended={() => setTeam2Players(recommended2.ids)} recommendedLoading={recommended2.loading} />
        <div className="flex items-center gap-3">
          <div className="space-y-1 flex-1">
            <label className="text-[11px] text-muted-foreground">Simulations</label>
            <input type="number" min={1} max={200} value={nSims} onChange={e => setNSims(Number(e.target.value))}
              className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40" />
          </div>
          <button onClick={run} disabled={!canRun}
            className="mt-4 py-2.5 px-5 bg-[#AAFF57] text-[#0D0D06] font-semibold text-sm rounded-lg hover:opacity-90 active:scale-[0.98] transition-all flex items-center gap-2 disabled:opacity-40">
            {loading ? <><RefreshCw size={14} className="animate-spin" /> Simulating…</> : <><PlayCircle size={14} /> Run Simulation</>}
          </button>
        </div>
        {error && <p className="text-[12px] text-red-400">{error}</p>}
      </div>

      <div className="space-y-3">
        {!result && !loading && (
          <div className="h-64 flex flex-col items-center justify-center text-center bg-card border border-dashed border-border rounded-xl">
            <PlayCircle size={28} className="text-muted-foreground mb-3 opacity-40" />
            <p className="text-sm text-muted-foreground">Pick both XIs (11 each) and run a simulation</p>
          </div>
        )}
        {result && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-3">
            <div className="bg-card border border-border rounded-xl p-4">
              <p className="text-[11px] text-muted-foreground mb-2">{result.n_simulations} simulation(s)</p>
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm text-foreground">{result.first_innings?.team}</span>
                <span className="font-mono text-sm font-semibold text-foreground">{result.first_innings?.score}/{result.first_innings?.wickets}</span>
              </div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-foreground">{result.second_innings?.team}</span>
                <span className="font-mono text-sm font-semibold text-foreground">{result.second_innings?.score}/{result.second_innings?.wickets}</span>
              </div>
              <div className="pt-2 border-t border-border text-[13px] font-semibold text-[#AAFF57]">Winner: {result.winner}</div>
              {result.win_probability_pct && (
                <div className="mt-2 flex gap-3 text-[11px] text-muted-foreground">
                  {Object.entries(result.win_probability_pct).map(([k, v]) => <span key={k}>{k}: {v as number}%</span>)}
                </div>
              )}
            </div>

            {result.win_prob_timeline?.length > 0 && (
              <WinProbChart timeline={result.win_prob_timeline} team1={team1} team2={team2} />
            )}

            {result.first_innings_scorecard && result.second_innings_scorecard && (
              <Scorecard result={result} />
            )}

            {result.key_moments?.length > 0 && (
              <div className="bg-card border border-border rounded-xl p-4">
                <h4 className="text-[12px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">Key Moments</h4>
                <div className="space-y-1.5 max-h-56 overflow-auto pr-1">
                  {result.key_moments.map((m: any, i: number) => (
                    <div key={i} className="text-[12px] text-foreground flex gap-2">
                      <span className="font-mono text-muted-foreground flex-shrink-0">{m.over}.{m.ball}</span>
                      <span>{m.description}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </motion.div>
        )}
      </div>
    </div>
  );
}

function OptimizeBowlingTab({ gender }: { gender: "female" | "male" }) {
  const [bowlingTeam, setBowlingTeam] = useState("India");
  const [battingTeam, setBattingTeam] = useState("Australia");
  const [bowlingPlayers, setBowlingPlayers] = useState<string[]>([]);
  const [battingPlayers, setBattingPlayers] = useState<string[]>([]);
  const bowlingRoster = useTeamRoster(bowlingTeam, gender);
  const battingRoster = useTeamRoster(battingTeam, gender);
  const recommendedBowling = useRecommendedXI(bowlingTeam, battingTeam, gender);
  const recommendedBatting = useRecommendedXI(battingTeam, bowlingTeam, gender);
  useEffect(() => { if (recommendedBowling.ids.length === 11) setBowlingPlayers(recommendedBowling.ids); }, [recommendedBowling.ids]);
  useEffect(() => { if (recommendedBatting.ids.length === 11) setBattingPlayers(recommendedBatting.ids); }, [recommendedBatting.ids]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);

  const run = async () => {
    setLoading(true); setError(null);
    try {
      const res = await api.optimizeBowling({ bowling_team: bowlingTeam, batting_team: battingTeam, bowling_player_ids: bowlingPlayers, batting_player_ids: battingPlayers, gender });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Optimization failed");
    } finally {
      setLoading(false);
    }
  };
  const canRun = bowlingPlayers.length === 11 && battingPlayers.length === 11 && !loading;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div className="space-y-3">
        <div className="flex gap-3">
          <TeamPicker label="Bowling team" value={bowlingTeam} onChange={setBowlingTeam} opts={TEAM_OPTS.filter(o => o !== battingTeam)} />
          <TeamPicker label="Opposition (batting)" value={battingTeam} onChange={setBattingTeam} opts={TEAM_OPTS.filter(o => o !== bowlingTeam)} />
        </div>
        <XIPicker label={`${bowlingTeam} XI (bowling)`} players={bowlingRoster.players} loading={bowlingRoster.loading} selectedIds={bowlingPlayers} onChange={setBowlingPlayers}
          onUseRecommended={() => setBowlingPlayers(recommendedBowling.ids)} recommendedLoading={recommendedBowling.loading} />
        <XIPicker label={`${battingTeam} XI (batting)`} players={battingRoster.players} loading={battingRoster.loading} selectedIds={battingPlayers} onChange={setBattingPlayers}
          onUseRecommended={() => setBattingPlayers(recommendedBatting.ids)} recommendedLoading={recommendedBatting.loading} />
        <button onClick={run} disabled={!canRun}
          className="py-2.5 px-5 bg-[#AAFF57] text-[#0D0D06] font-semibold text-sm rounded-lg hover:opacity-90 active:scale-[0.98] transition-all flex items-center gap-2 disabled:opacity-40">
          {loading ? <><RefreshCw size={14} className="animate-spin" /> Optimizing…</> : <><Wind size={14} /> Optimize Rotation</>}
        </button>
        {error && <p className="text-[12px] text-red-400">{error}</p>}
      </div>
      <div>
        {!result && !loading && (
          <div className="h-64 flex flex-col items-center justify-center text-center bg-card border border-dashed border-border rounded-xl">
            <Wind size={28} className="text-muted-foreground mb-3 opacity-40" />
            <p className="text-sm text-muted-foreground">Pick both XIs and search for the best bowling rotation</p>
          </div>
        )}
        {result && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-card border border-border rounded-xl p-4">
            <p className="text-[12px] text-muted-foreground mb-3">Expected runs conceded: <span className="font-mono text-foreground">{result.expected_runs_conceded}</span></p>
            <div className="space-y-1 max-h-72 overflow-auto pr-1">
              {result.rotation?.map((r: any) => (
                <div key={r.over} className="flex items-center justify-between text-[12px] px-2 py-1.5 rounded-lg bg-secondary/30">
                  <span className="text-muted-foreground">Over {r.over}</span>
                  <span className="text-foreground font-medium">{r.name}</span>
                </div>
              ))}
            </div>
            <BowlingRotationReasoning result={result} />
          </motion.div>
        )}
      </div>
    </div>
  );
}

// Renders the CLI's --explain payload: runs saved vs. a naive rotation, per-bowler phase fit.
function BowlingRotationReasoning({ result }: { result: any }) {
  const explanation = result.explanation;
  if (!explanation) return null;
  const nameById: Record<string, string> = Object.fromEntries(
    (result.overs_per_bowler ?? []).map((b: any) => [b.player_id, b.name])
  );
  return (
    <div className="mt-3 pt-3 border-t border-border/60 space-y-2">
      <p className="text-[12px] text-muted-foreground font-medium">Why this rotation</p>
      <p className="text-[11px] text-muted-foreground leading-relaxed">
        Vs a naive even split across the pool (ignoring phase fit): expected{" "}
        <strong className="text-foreground">{explanation.baseline_runs_conceded}</strong> runs conceded
        (<strong className={explanation.improvement_over_baseline >= 0 ? "text-[#AAFF57]" : "text-red-400"}>
          {explanation.improvement_over_baseline.toFixed(2)}
        </strong> runs {explanation.improvement_over_baseline >= 0 ? "saved" : "cost"} by this rotation).
      </p>
      <div className="space-y-1.5">
        {explanation.bowlers.map((b: any) => {
          const phaseDesc = Object.entries(b.phase_overs).map(([phase, n]) => `${n} ${phase}`).join(", ");
          const rankBits = Object.entries(b.phase_rank).map(([phase, info]: [string, any]) =>
            `${phase} economy rank ${info.rank}${info.size ? ` of ${info.size}` : ""}`);
          return (
            <p key={b.player_id} className="text-[11px] text-muted-foreground leading-relaxed">
              <span className="text-foreground font-medium">{nameById[b.player_id] ?? b.player_id}</span>: {b.overs} over(s) — {phaseDesc}
              {rankBits.length > 0 && <span className="text-muted-foreground/80"> (career-wide, among everyone who's played for this team: {rankBits.join("; ")})</span>}
            </p>
          );
        })}
      </div>
    </div>
  );
}

function OptimizeBattingTab({ gender }: { gender: "female" | "male" }) {
  const [battingTeam, setBattingTeam] = useState("India");
  const [bowlingTeam, setBowlingTeam] = useState("Australia");
  const [battingPlayers, setBattingPlayers] = useState<string[]>([]);
  const [bowlingPlayers, setBowlingPlayers] = useState<string[]>([]);
  const battingRoster = useTeamRoster(battingTeam, gender);
  const bowlingRoster = useTeamRoster(bowlingTeam, gender);
  const recommendedBatting = useRecommendedXI(battingTeam, bowlingTeam, gender);
  const recommendedBowling = useRecommendedXI(bowlingTeam, battingTeam, gender);
  useEffect(() => { if (recommendedBatting.ids.length === 11) setBattingPlayers(recommendedBatting.ids); }, [recommendedBatting.ids]);
  useEffect(() => { if (recommendedBowling.ids.length === 11) setBowlingPlayers(recommendedBowling.ids); }, [recommendedBowling.ids]);
  const [target, setTarget] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);

  const run = async () => {
    setLoading(true); setError(null);
    try {
      const res = await api.optimizeBatting({
        batting_team: battingTeam, bowling_team: bowlingTeam, batting_player_ids: battingPlayers, bowling_player_ids: bowlingPlayers,
        target: target ? Number(target) : undefined, gender,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Optimization failed");
    } finally {
      setLoading(false);
    }
  };
  const canRun = battingPlayers.length === 11 && bowlingPlayers.length === 11 && !loading;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div className="space-y-3">
        <div className="flex gap-3">
          <TeamPicker label="Batting team" value={battingTeam} onChange={setBattingTeam} opts={TEAM_OPTS.filter(o => o !== bowlingTeam)} />
          <TeamPicker label="Opposition (bowling)" value={bowlingTeam} onChange={setBowlingTeam} opts={TEAM_OPTS.filter(o => o !== battingTeam)} />
        </div>
        <XIPicker label={`${battingTeam} XI (batting)`} players={battingRoster.players} loading={battingRoster.loading} selectedIds={battingPlayers} onChange={setBattingPlayers}
          onUseRecommended={() => setBattingPlayers(recommendedBatting.ids)} recommendedLoading={recommendedBatting.loading} />
        <XIPicker label={`${bowlingTeam} XI (bowling)`} players={bowlingRoster.players} loading={bowlingRoster.loading} selectedIds={bowlingPlayers} onChange={setBowlingPlayers}
          onUseRecommended={() => setBowlingPlayers(recommendedBowling.ids)} recommendedLoading={recommendedBowling.loading} />
        <div className="space-y-1">
          <label className="text-[11px] text-muted-foreground">Chase target (optional — maximizes win probability instead of raw score)</label>
          <input type="number" value={target} onChange={e => setTarget(e.target.value)} placeholder="e.g. 162"
            className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40" />
        </div>
        <button onClick={run} disabled={!canRun}
          className="py-2.5 px-5 bg-[#AAFF57] text-[#0D0D06] font-semibold text-sm rounded-lg hover:opacity-90 active:scale-[0.98] transition-all flex items-center gap-2 disabled:opacity-40">
          {loading ? <><RefreshCw size={14} className="animate-spin" /> Optimizing…</> : <><ListOrdered size={14} /> Optimize Batting Order</>}
        </button>
        {error && <p className="text-[12px] text-red-400">{error}</p>}
      </div>
      <div>
        {!result && !loading && (
          <div className="h-64 flex flex-col items-center justify-center text-center bg-card border border-dashed border-border rounded-xl">
            <ListOrdered size={28} className="text-muted-foreground mb-3 opacity-40" />
            <p className="text-sm text-muted-foreground">Pick both XIs and search for the best batting order</p>
          </div>
        )}
        {result && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-card border border-border rounded-xl p-4">
            <p className="text-[12px] text-muted-foreground mb-3">
              {result.metric_name === "win_probability" ? "Win probability" : "Expected score"}: <span className="font-mono text-foreground">{result.metric_value}</span>
            </p>
            <div className="space-y-1 max-h-72 overflow-auto pr-1">
              {result.batting_order?.map((b: any) => (
                <div key={b.position} className="flex items-center gap-2 text-[12px] px-2 py-1.5 rounded-lg bg-secondary/30">
                  <span className="font-mono text-muted-foreground w-5 text-right">{b.position}</span>
                  <span className="text-foreground font-medium">{b.name}</span>
                </div>
              ))}
            </div>
            <BattingOrderReasoning result={result} />
          </motion.div>
        )}
      </div>
    </div>
  );
}

// Renders lineup_explain.py's --explain payload: baseline comparison, swap sensitivity, contingencies.
function BattingOrderReasoning({ result }: { result: any }) {
  const explanation = result.explanation;
  if (!explanation) return null;
  const nameById: Record<string, string> = Object.fromEntries(
    (result.batting_order ?? []).map((b: any) => [b.player_id, b.name])
  );
  const name = (pid: string) => nameById[pid] ?? pid;
  const metricLabel = result.metric_name === "win_probability" ? "win probability" : "expected score";
  const swap = explanation.most_costly_adjacent_swap;
  const { early_collapse, quick_chase } = explanation.contingency ?? {};

  return (
    <div className="mt-3 pt-3 border-t border-border/60 space-y-3">
      <div>
        <p className="text-[12px] text-muted-foreground font-medium mb-1">Why this order</p>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Vs a naive strike-rate-sorted order ({explanation.baseline_description}): baseline {metricLabel}{" "}
          <strong className="text-foreground">{explanation.baseline_metric}</strong>{" "}
          (<strong className={explanation.improvement_over_baseline >= 0 ? "text-[#AAFF57]" : "text-red-400"}>
            {explanation.improvement_over_baseline >= 0 ? "+" : ""}{explanation.improvement_over_baseline}
          </strong> {metricLabel} {explanation.improvement_over_baseline >= 0 ? "gained" : "lost"} by this order).
        </p>
        {swap && (
          <p className="text-[11px] text-muted-foreground leading-relaxed mt-1.5">
            Most order-sensitive pair: swapping positions {swap.positions[0]} and {swap.positions[1]}{" "}
            (<span className="text-foreground">{name(swap.player_ids[0])}</span> / <span className="text-foreground">{name(swap.player_ids[1])}</span>) would change {metricLabel} by{" "}
            <strong className={swap.delta >= 0 ? "text-[#AAFF57]" : "text-red-400"}>{swap.delta >= 0 ? "+" : ""}{swap.delta}</strong>.
          </p>
        )}
      </div>

      {(early_collapse || quick_chase) && (
        <div>
          <p className="text-[12px] text-muted-foreground font-medium mb-1">In-match contingencies</p>
          <div className="space-y-2">
            {early_collapse && (
              <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
                <p className="text-[11px] font-semibold text-amber-400 mb-0.5">
                  Early collapse — send in {name(early_collapse.player_id)}
                </p>
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  Natural position {early_collapse.natural_position}
                  {early_collapse.strike_rate != null && <> · strike rate {early_collapse.strike_rate}</>}. {early_collapse.reason}
                </p>
              </div>
            )}
            {quick_chase && (
              <div className="bg-[#AAFF57]/10 border border-[#AAFF57]/25 rounded-lg px-3 py-2">
                <p className="text-[11px] font-semibold text-[#AAFF57] mb-0.5">
                  Quick run chase — promote {name(quick_chase.player_id)}
                </p>
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  Natural position {quick_chase.natural_position}
                  {quick_chase.chasing_strike_rate != null && <> · chasing strike rate {quick_chase.chasing_strike_rate}</>}. {quick_chase.reason}
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function SimulationPage() {
  const location = useLocation();
  // A coach arriving from "Simulate This XI" on Recommendations brings a
  // pre-built pair of XIs via router state, applied once on mount. Router
  // state (not query params) here since it needs to carry full player-id
  // arrays that don't belong in a URL.
  //
  // Not calling navigate() again afterwards to "clean up" the state: a
  // same-pathname navigate() -- even a `replace` -- triggers a full
  // unmount/remount of this component (Root's Outlet, wrapped in
  // AnimatePresence, tears the route element down and rebuilds it), which
  // would wipe prefill/prefillKey right back to their initial values a
  // render after they were set.
  const [prefill, setPrefill] = useState<SimulatorPrefill | undefined>(() => (location.state as SimulatorPrefill) ?? undefined);
  const [prefillKey, setPrefillKey] = useState(0);
  useEffect(() => {
    if (location.state) {
      setPrefill(location.state as SimulatorPrefill);
      setPrefillKey(k => k + 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state]);

  const [tab, setTab] = useState<"simulate" | "optimize-bowling" | "optimize-batting">("simulate");
  const [gender, setGender] = useState<"female" | "male">(prefill?.gender ?? "female");
  // Keep the Women/Men toggle in sync with a freshly-arrived prefill too --
  // otherwise a match-detail "Simulate Match" for a men's match would still
  // fetch women's rosters if the toggle was last left on "Women".
  useEffect(() => {
    if (prefill) setGender(prefill.gender);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill]);

  const tabs = useMemo(() => ([
    { id: "simulate" as const, label: "Simulate Match", icon: PlayCircle },
    { id: "optimize-bowling" as const, label: "Optimize Bowling", icon: Wind },
    { id: "optimize-batting" as const, label: "Optimize Batting", icon: ListOrdered },
  ]), []);

  return (
    <div className="p-5 max-w-screen-xl mx-auto">
      <div className="flex items-center justify-between mb-5 flex-wrap gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold text-foreground">Simulator</h1>
          <p className="text-sm text-muted-foreground mt-0.5">Ball-by-ball match simulation and in-match GA optimizers</p>
        </div>
        <div className="flex rounded-lg border border-border overflow-hidden">
          {(["female", "male"] as const).map(g => (
            <button key={g} onClick={() => setGender(g)}
              className={`px-3 py-1.5 text-sm font-medium transition-colors ${gender === g ? "bg-[#AAFF57] text-[#0D0D06]" : "bg-secondary text-muted-foreground hover:text-foreground"}`}>
              {g === "female" ? "Women" : "Men"}
            </button>
          ))}
        </div>
      </div>

      {prefill && (
        <div className="mb-4 text-[12px] text-[#AAFF57] bg-[#AAFF57]/10 border border-[#AAFF57]/30 rounded-lg px-3 py-2">
          Pre-filled both XIs from the AI's recommendations for {prefill.team1} vs {prefill.team2} — adjust and run, or pick new teams below.
        </div>
      )}

      <div className="flex gap-2 mb-5 border-b border-border">
        {tabs.map(t => {
          const Icon = t.icon;
          return (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 px-3 py-2.5 text-[13px] border-b-2 transition-colors ${tab === t.id ? "border-[#AAFF57] text-foreground font-medium" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
              <Icon size={13} /> {t.label}
            </button>
          );
        })}
      </div>

      <AnimatePresence mode="wait">
        <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
          {tab === "simulate" && <SimulateTab key={prefillKey} gender={gender} prefill={tab === "simulate" ? prefill : undefined} />}
          {tab === "optimize-bowling" && <OptimizeBowlingTab gender={gender} />}
          {tab === "optimize-batting" && <OptimizeBattingTab gender={gender} />}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

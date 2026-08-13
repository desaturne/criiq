import { useMemo, useState } from "react";
import { useEffect } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useNavigate } from "react-router";
import { Zap, ChevronDown, RefreshCw, CheckCircle2, AlertTriangle, PlayCircle, Sparkles } from "lucide-react";
import { RadialGauge } from "../components/common/RadialGauge";
import { SelectionControl } from "../components/common/SelectionControl";
import { TeamSelect } from "../components/common/TeamSelect";
import { VenueSelect } from "../components/common/VenueSelect";
import { SquadStrengthModal } from "../components/squad/SquadStrengthModal";
import * as api from "../lib/api";
import { colorFor, initialsFor } from "../lib/mappers";
import { SimulatorPrefill } from "./SimulationPage";
import { useApp } from "../context/AppContext";
import { SelectionState } from "../types/index";

// Squad/Bench Strength display: rescales the real 0-100 score onto a 30-100 range.
const SQUAD_STRENGTH_BASE = 30;
const rescaleStrength = (rawScore: number) => SQUAD_STRENGTH_BASE + rawScore * (100 - SQUAD_STRENGTH_BASE) / 100;

interface Recommendation { rank: number; player_id: string; player_name: string; role: string; score: number; reasons: string[]; in_xi: boolean; }

// Bolds the numeric/percentage tokens in a reasoning sentence (e.g. "+5.8%",
// "144 career matches", "-0.2 pts") so the concrete data point in each bullet
// stands out instead of reading as one flat sentence.
const NUMBER_TOKEN_SPLIT = /([+-]?\d+(?:\.\d+)?%?)/g;
const NUMBER_TOKEN_MATCH = /^[+-]?\d+(?:\.\d+)?%?$/;
function Highlighted({ text }: { text: string }) {
  const parts = text.split(NUMBER_TOKEN_SPLIT);
  return (
    <>
      {parts.map((part, i) =>
        NUMBER_TOKEN_MATCH.test(part)
          ? <strong key={i} className="text-foreground font-semibold">{part}</strong>
          : <span key={i}>{part}</span>
      )}
    </>
  );
}

const SHAP_TARGET_LABELS: Record<string, string> = { batting_wpa: "Batting impact", bowling_wpa: "Bowling impact" };

// A diverging bar anchored at a shared zero baseline (center) -- magnitude
// grows outward either side, color marks the sign, and the value is repeated
// as a signed number so the sign is never color-only.
function ShapBar({ feature, value, maxAbs }: { feature: string; value: number; maxAbs: number }) {
  const pct = maxAbs > 0 ? Math.min(100, (Math.abs(value) / maxAbs) * 100) : 0;
  const positive = value >= 0;
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className="w-32 flex-shrink-0 truncate text-muted-foreground">{feature.replace(/_/g, " ")}</span>
      <div className="flex-1 flex items-center h-3">
        <div className="w-1/2 flex justify-end">
          {!positive && <div className="h-2 bg-red-400/70 rounded-l-sm" style={{ width: `${pct}%` }} />}
        </div>
        <div className="w-px h-3 bg-border flex-shrink-0" />
        <div className="w-1/2 flex justify-start">
          {positive && <div className="h-2 bg-[#AAFF57]/70 rounded-r-sm" style={{ width: `${pct}%` }} />}
        </div>
      </div>
      <span className="w-16 flex-shrink-0 text-right text-muted-foreground" style={{ fontVariantNumeric: "tabular-nums" }}>
        {positive ? "+" : ""}{(value * 100).toFixed(2)}%
      </span>
    </div>
  );
}

// Renders whichever of batting_wpa/bowling_wpa SHAP actually explained --
// a pure bowler's batting model (or vice versa) commonly comes back
// {"error": "..."} for lack of a background sample, so those are skipped
// rather than shown as a broken section; the plain-language reasons above
// already cover the "why" for a player SHAP can't explain at all.
function ShapSection({ result }: { result: api.ShapExplainResult | "loading" | "error" | undefined }) {
  if (!result) return null;
  if (result === "loading") return <p className="text-[11px] text-muted-foreground mt-3">Loading feature impact…</p>;
  if (result === "error" || !result.shap || "error" in result.shap) return null;
  const targets = Object.entries(result.shap).filter(([, t]) => t && !t.error && t.top_contributions?.length);
  if (!targets.length) return null;
  return (
    <div className="mt-3 pt-3 border-t border-border/60 space-y-3">
      <p className="text-[12px] text-muted-foreground font-medium">Feature impact (model contribution)</p>
      {targets.map(([key, target]) => {
        const contributions = target.top_contributions!;
        const maxAbs = Math.max(...contributions.map(c => Math.abs(c.value)), 1e-9);
        return (
          <div key={key}>
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground/70 mb-1">{SHAP_TARGET_LABELS[key] || key}</p>
            <div className="space-y-1">
              {contributions.map(c => <ShapBar key={c.feature} feature={c.feature} value={c.value} maxAbs={maxAbs} />)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function RecommendationsPage() {
  const navigate = useNavigate();
  const { user } = useApp();
  const [generated, setGenerated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [team, setTeam] = useState(user?.country || "India");
  const [opponent, setOpponent] = useState("Australia");
  const [venue, setVenue] = useState("");
  const [format, setFormat] = useState("T20I");
  const [gender, setGender] = useState<"female" | "male">("female");
  const [simulating, setSimulating] = useState(false);
  // Shared with the Squads page (keyed by player_id) so a pick made here shows
  // up in the squad's Playing XI. Local component state would strand it here.
  const { selections, setSelections } = useApp();
  const [confirming, setConfirming] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  // Keyed by player_id (not player_name -- names can collide) and fetched
  // lazily on first expand, since it's a separate per-player model call.
  const [shapById, setShapById] = useState<Record<string, api.ShapExplainResult | "loading" | "error">>({});
  const [ranked, setRanked] = useState<Recommendation[]>([]);
  const [opponentXi, setOpponentXi] = useState<{ player_id: string; player_name: string; role: string; score: number }[] | null>(null);
  const [showOpponentXi, setShowOpponentXi] = useState(false);
  // Feeds the "who to target" summary in the Squad Strength modal below.
  const [headToHead, setHeadToHead] = useState<api.HeadToHeadTeam | null>(null);
  const [showSquadAnalysis, setShowSquadAnalysis] = useState(false);
  // The opposition XI the coach names. Our XI is picked to counter exactly
  // these players, so it is an input to the engine, not an output of it.
  const [oppRoster, setOppRoster] = useState<{ id: string; name: string; role: string }[]>([]);
  const [oppRosterLoading, setOppRosterLoading] = useState(false);
  const [oppXiIds, setOppXiIds] = useState<string[]>([]);
  const [autoPicking, setAutoPicking] = useState(false);
  const [counteredXi, setCounteredXi] = useState(false);
  const XI_SIZE = 11;
  const oppXiComplete = oppXiIds.length === XI_SIZE;
  const selectedCount = Object.values(selections).filter(s => s === "select").length;
  // Snapshot of whichever params actually produced `ranked` -- compared
  // against the live dropdowns below so changing Team/Opponent/Venue/Format
  // after generating shows an explicit "stale, regenerate" notice instead of
  // silently leaving old results on screen with no indication they're outdated.
  const [generatedParams, setGeneratedParams] = useState<{ team: string; opponent: string; venue: string; format: string; gender: string; opponentXiKey: string } | null>(null);
  // Editing the opposition XI after generating invalidates the result just as
  // much as changing the venue does -- the XI is a model input, not a filter.
  const liveOpponentXiKey = oppXiIds.length === XI_SIZE ? [...oppXiIds].sort().join(",") : "";
  const stale = generated && generatedParams !== null &&
    (generatedParams.team !== team || generatedParams.opponent !== opponent ||
     generatedParams.venue !== venue || generatedParams.format !== format ||
     generatedParams.gender !== gender || generatedParams.opponentXiKey !== liveOpponentXiKey);
  // Whoever's currently marked "Select" (not the AI's fixed XI), so toggling Select/Reserve/Exclude moves squadStrength below.
  const selectedXi = useMemo(() => ranked.filter(r => selections[r.player_id] === "select"), [ranked, selections]);
  const squadStrength = useMemo(() => {
    if (!selectedXi.length) return 0;
    return rescaleStrength(selectedXi.reduce((s, r) => s + r.score, 0) / selectedXi.length);
  }, [selectedXi]);
  // Same average, over whoever the coach has marked "Reserve" instead of the
  // AI's constrained XI -- how deep the depth actually is, not just the 11.
  const benchPlayers = useMemo(() => ranked.filter(r => selections[r.player_id] === "reserve"), [ranked, selections]);
  const benchStrength = useMemo(() => {
    if (!benchPlayers.length) return 0;
    return rescaleStrength(benchPlayers.reduce((s, r) => s + r.score, 0) / benchPlayers.length);
  }, [benchPlayers]);

  // A coach selects for their own side and nobody else's, so Team is pinned to
  // the country on their profile (chosen at sign-up) and is not editable here.
  // Only the Opponent is free -- they can be analysed against any team. The
  // Simulator is the page for arbitrary team-vs-team matchups; this one is
  // "who should *I* pick", which is meaningless for a squad that isn't theirs.
  const teamLocked = !!user?.country;

  useEffect(() => {
    if (user?.country) setTeam(user.country);
  }, [user?.country]);

  // ...which means the coach can no longer resolve a same-team matchup by
  // changing Team. An Indian coach lands on the "Australia" default fine, but
  // an Australian coach would open on Australia vs Australia, so move the
  // opponent off their own side instead.
  useEffect(() => {
    if (team && opponent === team) setOpponent(team === "Australia" ? "India" : "Australia");
  }, [team, opponent]);

  // The opposition's selectable roster, to pick their XI from. Reloads on
  // opponent/gender change, and clears the previous XI -- those ids belong to
  // a different squad and must not silently carry over.
  useEffect(() => {
    let cancelled = false;
    setOppRosterLoading(true);
    setOppXiIds([]);
    api.listPlayers({ country: opponent, gender, limit: 100 })
      .then(res => {
        if (cancelled) return;
        setOppRoster(res.players.map((p: any) => ({ id: p.id, name: p.name, role: p.role })));
      })
      .catch(() => { if (!cancelled) setOppRoster([]); })
      .finally(() => { if (!cancelled) setOppRosterLoading(false); });
    return () => { cancelled = true; };
  }, [opponent, gender]);

  const toggleOppPlayer = (id: string) => setOppXiIds(prev =>
    prev.includes(id) ? prev.filter(x => x !== id)
      : prev.length < XI_SIZE ? [...prev, id] : prev
  );

  // Fills the opposition XI with the engine's own prediction of who they'll
  // field, as a starting point the coach can then edit.
  const handleAutoPickOpponent = async () => {
    setAutoPicking(true);
    setError(null);
    try {
      const res = await api.recommendations({ team: opponent, opponent: team, venue, format, gender });
      const ids = res.recommendations.filter(r => r.in_xi).map(r => r.player_id);
      const known = new Set(oppRoster.map(p => p.id));
      setOppXiIds(ids.filter(id => known.has(id)).slice(0, XI_SIZE));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't auto-pick the opposition XI");
    } finally {
      setAutoPicking(false);
    }
  };

  // Fully replaces selections with just this pool's picks -- selections isn't scoped per matchup, so a merge would let a stale pick (even a previously saved squad for a different opponent) persist across sessions.
  const applyAiXiToSelections = (pool: Recommendation[]) => {
    const next: Record<string, SelectionState> = {};
    pool.forEach(r => { next[r.player_id] = r.in_xi ? "select" : "undecided"; });
    setSelections(next);
  };
  const resetToAiXi = () => applyAiXiToSelections(ranked);

  const handleGenerate = async () => {
    setLoading(true);
    setError(null);
    try {
      // The button below is only enabled once the opposition XI is fully
      // named, so this always has a complete XI to counter -- no
      // auto-predicted-opponent fallback anymore (the coach names it or
      // doesn't generate at all).
      const recRes = await api.recommendations({ team, opponent, venue, format, gender, opponent_player_ids: oppXiIds });
      setRanked(recRes.recommendations);
      // `selections` is shared across pages and never tied to a specific
      // matchup -- without this, a manual Select/Reserve/Exclude toggle made
      // for a *previous* opponent (or team/venue/format) silently keeps
      // showing as selected against this new one, since the player_ids
      // usually overlap heavily (same team's roster either way). Every fresh
      // generation starts from the AI's own pick for THIS matchup instead.
      applyAiXiToSelections(recRes.recommendations);
      setOpponentXi(recRes.opponent_xi);
      setHeadToHead(recRes.head_to_head);
      setCounteredXi(recRes.countered_opponent_xi);
      setGeneratedParams({ team, opponent, venue, format, gender, opponentXiKey: oppXiComplete ? [...oppXiIds].sort().join(",") : "" });
      setGenerated(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't generate recommendations");
    } finally {
      setLoading(false);
    }
  };

  // "Simulate This XI" -- the coach's constrained 11 is already known
  // (`ranked`'s in_xi players); also fetch the opponent's own recommended XI
  // (a second /recommendations call with team/opponent swapped) so both
  // sides of the Simulator arrive pre-filled instead of forcing a manual
  // 22-player pick.
  const handleSimulateXI = async () => {
    setSimulating(true);
    setError(null);
    try {
      const team1PlayerIds = ranked.filter(r => r.in_xi).map(r => r.player_id);
      // If the coach named the opposition XI, simulate against that exact XI
      // -- re-predicting one here would simulate a different match than the
      // one the recommendation was built for.
      let team2PlayerIds: string[];
      if (oppXiComplete) {
        team2PlayerIds = oppXiIds;
      } else {
        const oppRes = await api.recommendations({ team: opponent, opponent: team, venue, format, gender });
        team2PlayerIds = oppRes.recommendations.filter(r => r.in_xi).map(r => r.player_id);
      }
      const prefill: SimulatorPrefill = { team1: team, team2: opponent, team1PlayerIds, team2PlayerIds, gender };
      navigate("/simulator", { state: prefill });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't prepare the opponent's XI for simulation");
    } finally {
      setSimulating(false);
    }
  };

  // "Confirm Selection" -- persist whatever the coach has picked as the Playing
  // XI (plus reserves/excluded) to the backend for the next fixture, then hand
  // off to the Squads page, which reads the same shared `selections` and opens
  // straight onto the XI panel.
  const handleConfirm = async () => {
    const idsFor = (state: SelectionState) =>
      Object.entries(selections).filter(([, s]) => s === state).map(([id]) => id);
    const xi = idsFor("select");
    if (xi.length === 0) return;
    if (xi.length > 11) {
      setError(`You've selected ${xi.length} players — a Playing XI can have at most 11. Remove ${xi.length - 11}.`);
      return;
    }
    setConfirming(true);
    setError(null);
    try {
      const matches = await api.listMatches();
      const matchId = matches.upcoming[0]?.id;
      if (matchId) {
        await api.saveSelection(matchId, { xi, extra: idsFor("reserve"), excluded: idsFor("exclude") });
      }
      navigate("/build-xi", { state: { openSquad: true } });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save the selection");
    } finally {
      setConfirming(false);
    }
  };

  // Group the ranked pool into role buckets, mirroring the CLI's role_pools
  // (batters / all-rounders / bowlers, each already score-ordered because
  // `ranked` is score-ranked), plus a catch-all "Others" for anything the
  // model couldn't classify. Same players — just the coach's mental grouping.
  const topScore = ranked.length ? Math.max(...ranked.map(r => r.score), 1) : 1;
  const POOL_DEFS: { key: string; label: string; match: (role: string) => boolean }[] = [
    { key: "batters",      label: "Batters",      match: r => r === "batter" },
    { key: "all_rounders", label: "All-rounders", match: r => r === "all-rounder" },
    { key: "bowlers",      label: "Bowlers",      match: r => r === "bowler" },
    { key: "others",       label: "Others",       match: r => !["batter", "all-rounder", "bowler"].includes(r) },
  ];

  // Fetches SHAP for a card the first time it's expanded; subsequent
  // toggles reuse the cached result instead of re-hitting the model.
  const handleExplainToggle = (rec: Recommendation) => {
    const next = expandedId === rec.player_name ? null : rec.player_name;
    setExpandedId(next);
    if (next && !shapById[rec.player_id]) {
      setShapById(prev => ({ ...prev, [rec.player_id]: "loading" }));
      api.explainPlayer(rec.player_id, { opponent, venue, format, gender })
        .then(res => setShapById(prev => ({ ...prev, [rec.player_id]: res })))
        .catch(() => setShapById(prev => ({ ...prev, [rec.player_id]: "error" })));
    }
  };

  const renderCard = (rec: Recommendation, i: number) => {
    const color = colorFor(rec.player_name);
    const relative = rec.score / topScore;
    const gaugeColor = relative >= 0.75 ? "#AAFF57" : relative >= 0.4 ? "#60A5FA" : "#FB923C";
    return (
      <motion.div key={rec.rank} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.03 }}
        className="bg-card border border-border rounded-xl overflow-hidden">
        <div className="p-3 flex items-center gap-3">
          <span className="font-mono text-[11px] text-muted-foreground w-5 text-right flex-shrink-0">#{rec.rank}</span>
          <div className="w-8 h-8 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0" style={{ backgroundColor: color + "33", color }}>{initialsFor(rec.player_name)}</div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="text-[13px] font-semibold text-foreground truncate">{rec.player_name}</span>
              {rec.in_xi && (
                <span className="flex items-center gap-0.5 text-[9px] font-medium text-[#AAFF57] bg-[#AAFF57]/10 border border-[#AAFF57]/30 rounded-full px-1.5 py-0.5 flex-shrink-0">
                  <CheckCircle2 size={9} /> In XI
                </span>
              )}
            </div>
            <div className="text-[10px] text-muted-foreground capitalize">{rec.role}</div>
          </div>
          <RadialGauge value={rec.score} decimals={1} size={44} strokeWidth={3.5} color={gaugeColor} />
          <button onClick={() => handleExplainToggle(rec)} className="text-[11px] text-muted-foreground hover:text-foreground flex items-center gap-0.5 px-2">
            Explain <ChevronDown size={10} className={`transition-transform ${expandedId === rec.player_name ? "rotate-180" : ""}`} />
          </button>
          <SelectionControl state={selections[rec.player_id] || "undecided"} onChange={s => setSelections(prev => ({ ...prev, [rec.player_id]: s }))} />
        </div>
        <AnimatePresence>
          {expandedId === rec.player_name && (
            <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden border-t border-border">
              <div className="p-4 bg-secondary/30">
                <p className="text-[12px] text-muted-foreground mb-2 font-medium">Why this recommendation</p>
                <ul className="space-y-1.5">
                  {rec.reasons.map((r, ri) => (
                    <li key={ri} className="text-[12px] text-muted-foreground leading-relaxed flex gap-2">
                      <span className="text-[#AAFF57] flex-shrink-0">•</span>
                      <span><Highlighted text={r} /></span>
                    </li>
                  ))}
                </ul>
                <ShapSection result={shapById[rec.player_id]} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    );
  };

  return (
    <div className="p-5 max-w-screen-xl mx-auto">
      <div className="mb-5">
        <h1 className="font-display text-2xl font-bold text-foreground">AI Recommendations</h1>
        <p className="text-sm text-muted-foreground mt-0.5">Data-driven team selection engine</p>
      </div>

      <div className="space-y-5">
        {/* Setup row: match parameters and the opposition XI side by side, so
            both inputs are visible at once while the coach sets the matchup
            up. The ranked output runs full-width underneath. */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
          <div className="bg-card border border-border rounded-xl p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-display text-base font-semibold text-foreground">Match Parameters</h3>
              <div className="flex rounded-lg border border-border overflow-hidden">
                {(["female", "male"] as const).map(g => (
                  <button key={g} onClick={() => setGender(g)}
                    className={`px-2.5 py-1 text-[12px] font-medium transition-colors ${gender === g ? "bg-[#AAFF57] text-[#0D0D06]" : "bg-secondary text-muted-foreground hover:text-foreground"}`}>
                    {g === "female" ? "Women" : "Men"}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-3">
              <TeamSelect label="Your team" value={team} onChange={setTeam} gender={gender} against={opponent} disabled={teamLocked} />
              <TeamSelect label="Opponent" value={opponent} onChange={setOpponent} gender={gender} against={team} exclude={team} />
              <VenueSelect value={venue} onChange={setVenue} team1={team} team2={opponent} />
              {/* T20I is the only supported format */}
              <div className="space-y-1">
                <label className="text-[12px] text-muted-foreground">Format</label>
                <button type="button" disabled
                  className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2 text-foreground text-left cursor-default">
                  {format}
                </button>
              </div>
            </div>
          </div>

          {/* Opposition XI — the coach names the 11 they're up against, and
              our XI is picked to counter exactly those players (real
              player-vs-player matchup data, not just team-level averages). */}
          <div className="bg-card border border-border rounded-xl p-5">
            <div className="flex items-center justify-between mb-1">
              <h3 className="font-display text-base font-semibold text-foreground">Opposition XI</h3>
              <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${oppXiComplete ? "bg-[#AAFF57]/15 text-[#AAFF57]" : "bg-secondary text-muted-foreground"}`}>
                {oppXiIds.length}/{XI_SIZE}
              </span>
            </div>
            <p className="text-[12px] text-muted-foreground mb-3">
              Pick the {XI_SIZE} {opponent} players you expect to face. Your XI is then chosen to counter them directly.
            </p>

            <button onClick={handleAutoPickOpponent} disabled={autoPicking || oppRosterLoading || !oppRoster.length}
              className="w-full mb-3 py-2 border border-border text-[12px] font-medium rounded-lg text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-all flex items-center justify-center gap-1.5 disabled:opacity-50">
              {autoPicking
                ? <><RefreshCw size={12} className="animate-spin" /> Predicting…</>
                : <><Sparkles size={12} /> Auto-pick their likely XI</>}
            </button>

            {oppRosterLoading ? (
              <div className="py-6 text-center text-[12px] text-muted-foreground">Loading {opponent} squad…</div>
            ) : !oppRoster.length ? (
              <div className="py-6 text-center text-[12px] text-muted-foreground">No selectable {opponent} players found.</div>
            ) : (
              <div className="max-h-64 overflow-auto -mx-1 px-1 space-y-1">
                {oppRoster.map(p => {
                  const picked = oppXiIds.includes(p.id);
                  const full = !picked && oppXiIds.length >= XI_SIZE;
                  return (
                    <button key={p.id} onClick={() => toggleOppPlayer(p.id)} disabled={full}
                      className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left transition-colors border ${
                        picked ? "bg-[#AAFF57]/10 border-[#AAFF57]/30" : "border-transparent hover:bg-secondary"
                      } ${full ? "opacity-40 cursor-not-allowed" : ""}`}>
                      <span className={`w-3.5 h-3.5 rounded flex-shrink-0 flex items-center justify-center border ${
                        picked ? "bg-[#AAFF57] border-[#AAFF57]" : "border-border"
                      }`}>
                        {picked && <CheckCircle2 size={10} className="text-[#0D0D06]" />}
                      </span>
                      <span className="text-[12px] text-foreground truncate flex-1">{p.name}</span>
                      <span className="text-[10px] text-muted-foreground flex-shrink-0">{p.role}</span>
                    </button>
                  );
                })}
              </div>
            )}

            {stale && (
              <div className="mt-3 flex items-start gap-2 text-[12px] text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
                <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" />
                <span>Match parameters or the opposition XI changed since these results were generated — click Generate Recommendation to refresh.</span>
              </div>
            )}
            {!oppXiComplete && (
              <p className="mt-3 text-[11px] text-muted-foreground">
                Name all {XI_SIZE} opposition players (or use Auto-pick above) to enable Generate Recommendation.
              </p>
            )}
            <button onClick={handleGenerate} disabled={loading || !oppXiComplete}
              className="w-full mt-3 py-2.5 bg-[#AAFF57] text-[#0D0D06] font-semibold text-sm rounded-lg hover:opacity-90 active:scale-[0.98] transition-all flex items-center justify-center gap-2 disabled:opacity-60">
              {loading ? <><RefreshCw size={14} className="animate-spin" /> Analysing…</> : <><Zap size={14} /> Generate Recommendation</>}
            </button>
          </div>

        </div>

        {/* Squad strength — real average score of the AI's constrained XI
            within this pool (genuinely varies with team/opponent/venue,
            unlike a pre-match "win probability": criiq_models' win-prob
            model is a pure ball-by-ball game-state lookup with no team
            identity input at all, so it can't answer "who's favoured"
            before any XI exists — that only becomes a real number once two
            full XIs are simulated on the Simulator page). Laid out as a
            full-width strip between the setup row and the ranked output. */}
        {generated && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
            className="bg-card border border-border rounded-xl p-5 flex flex-col lg:flex-row lg:items-center gap-5">
            {/* Opens win rate / who-to-target / batting order analysis for the AI's XI. */}
            <button onClick={() => setShowSquadAnalysis(true)} disabled={!oppXiComplete}
              className="flex items-center gap-4 text-left rounded-xl -m-1.5 p-1.5 transition-colors hover:bg-secondary/50 disabled:hover:bg-transparent disabled:cursor-default group">
              <RadialGauge value={squadStrength} decimals={1} size={84} strokeWidth={6} color="#AAFF57" label="Score" />
              <div className="min-w-0">
                <h3 className="font-display text-base font-semibold text-foreground flex items-center gap-1.5">
                  Squad Strength
                  {oppXiComplete && <span className="text-[10px] font-normal text-[#AAFF57] opacity-0 group-hover:opacity-100 transition-opacity">Tap to analyze →</span>}
                </h3>
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  {selectedXi.length > 0 ? `Avg score of your ${selectedXi.length}-player XI, this matchup` : "Avg score of your selected XI, this matchup"}
                </p>
                <p className="text-[12px] text-muted-foreground mt-1.5">
                  {selectedCount === 0
                    ? "Tap Select on players below to build your own XI"
                    : `${selectedCount}/11 selected${selectedCount > 11 ? " — remove " + (selectedCount - 11) : ""}`}
                </p>
              </div>
            </button>
            {/* Bench strength — same average, over whoever's marked Reserve
                instead of the AI's XI. Only shown once there's a bench to
                measure; otherwise it's a 0 gauge with nothing behind it. */}
            {benchPlayers.length > 0 && (
              <div className="flex items-center gap-4">
                <RadialGauge value={benchStrength} decimals={1} size={64} strokeWidth={5} color="#60A5FA" label="Score" />
                <div className="min-w-0">
                  <h3 className="font-display text-sm font-semibold text-foreground">Bench Strength</h3>
                  <p className="text-[11px] text-muted-foreground mt-0.5">Avg score of the {benchPlayers.length} player{benchPlayers.length === 1 ? "" : "s"} marked Reserve</p>
                </div>
              </div>
            )}
            <div className="flex flex-col sm:flex-row gap-2 w-full lg:w-auto lg:ml-auto">
              <button onClick={resetToAiXi}
                className="py-2 px-4 border border-[#AAFF57]/40 text-[#AAFF57] text-[12px] rounded-lg hover:bg-[#AAFF57]/10 active:scale-[0.98] transition-all flex items-center justify-center gap-1.5 whitespace-nowrap">
                <Sparkles size={13} /> Reset to AI's recommended XI
              </button>
              {selectedCount > 0 && (
                <button onClick={handleConfirm} disabled={confirming || selectedCount > 11}
                  className="py-2.5 px-4 bg-[#5FA800] text-white font-semibold text-[13px] rounded-lg hover:opacity-90 active:scale-[0.98] transition-all flex items-center justify-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap">
                  {confirming
                    ? <><RefreshCw size={14} className="animate-spin" /> Saving…</>
                    : <><CheckCircle2 size={14} /> Confirm Selection ({selectedCount}/11) → Squad</>}
                </button>
              )}
              <button onClick={handleSimulateXI} disabled={simulating}
                className="py-2 px-4 border border-border text-foreground text-[12px] rounded-lg hover:border-[#AAFF57]/40 hover:text-[#AAFF57] transition-all flex items-center justify-center gap-1.5 disabled:opacity-60 whitespace-nowrap">
                {simulating
                  ? <><RefreshCw size={13} className="animate-spin" /> Preparing both XIs…</>
                  : <><PlayCircle size={13} /> Simulate this XI</>}
              </button>
            </div>
          </motion.div>
        )}

        {/* Results — full width, below the setup row */}
        <div>
          <AnimatePresence mode="wait">
            {!generated && !loading && !error && (
              <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-64 flex flex-col items-center justify-center text-center bg-card border border-dashed border-border rounded-xl">
                <Zap size={32} className="text-muted-foreground mb-3 opacity-40" />
                <p className="text-muted-foreground text-sm">Configure match parameters and generate recommendations</p>
              </motion.div>
            )}
            {loading && (
              <motion.div key="loading" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-64 flex flex-col items-center justify-center text-center bg-card border border-border rounded-xl">
                <RefreshCw size={24} className="text-[#AAFF57] animate-spin mb-3" />
                <p className="text-muted-foreground text-sm">Analysing player data, form, and matchup factors…</p>
              </motion.div>
            )}
            {!loading && error && (
              <motion.div key="error" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-64 flex flex-col items-center justify-center text-center bg-card border border-border rounded-xl">
                <p className="text-red-400 text-sm">{error}</p>
              </motion.div>
            )}
            {generated && (
              <motion.div key="results" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-2">
                <div className="flex items-center justify-between mb-3">
                  <p className="text-[13px] text-muted-foreground">Top {ranked.length} for <strong className="text-foreground">vs {opponent}</strong> at <strong className="text-foreground">{venue}</strong>, grouped by role — <span className="text-[#AAFF57]">green tag</span> marks the AI's constrained 11-player XI</p>
                  <span className="text-[12px] font-medium text-[#AAFF57]">{selectedCount}/11 selected</span>
                </div>
                {/* Makes it explicit whether this XI was actually countered
                    against the named opposition (player-vs-player matchup
                    data) or picked from form/team-level records alone. */}
                <div className={`mb-3 flex items-start gap-2 text-[12px] rounded-lg px-3 py-2 border ${
                  counteredXi
                    ? "text-[#AAFF57] bg-[#AAFF57]/10 border-[#AAFF57]/25"
                    : "text-muted-foreground bg-secondary border-border"
                }`}>
                  {counteredXi ? <CheckCircle2 size={13} className="flex-shrink-0 mt-0.5" /> : <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" />}
                  <span>
                    {counteredXi
                      ? <>Countered against the named {opponent} XI — picks use real player-vs-player matchup records.</>
                      : <>No opposition XI was named, so this XI is based on form and team-level records only.</>}
                  </span>
                </div>
                {opponentXi && (
                  <div className="bg-card border border-border rounded-xl overflow-hidden mb-3">
                    <button onClick={() => setShowOpponentXi(v => !v)}
                      className="w-full p-3 flex items-center justify-between text-[12px] text-muted-foreground hover:text-foreground">
                      <span>vs probable {opponent} XI ({opponentXi.length})</span>
                      <ChevronDown size={12} className={`transition-transform ${showOpponentXi ? "rotate-180" : ""}`} />
                    </button>
                    <AnimatePresence>
                      {showOpponentXi && (
                        <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden border-t border-border">
                          <ul className="p-3 space-y-1 text-[12px] text-muted-foreground">
                            {opponentXi.map(p => (
                              <li key={p.player_id} className="flex justify-between">
                                <span className="text-foreground">{p.player_name}</span>
                                <span className="capitalize">{p.role} · {p.score.toFixed(1)}</span>
                              </li>
                            ))}
                          </ul>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                )}
                {POOL_DEFS.map(pool => {
                  const members = ranked.filter(r => pool.match(r.role));
                  if (!members.length) return null;
                  const inXi = members.filter(m => m.in_xi).length;
                  return (
                    <div key={pool.key} className="space-y-2">
                      <div className="flex items-center gap-2 mt-4 first:mt-0">
                        <h4 className="text-[12px] font-bold uppercase tracking-wider text-foreground">{pool.label}</h4>
                        <span className="text-[11px] text-muted-foreground">({members.length})</span>
                        <div className="flex-1 h-px bg-border" />
                        {inXi > 0 && <span className="text-[10px] text-[#AAFF57]">{inXi} in XI</span>}
                      </div>
                      {/* Two columns from xl up: the output is full-width now
                          that the inputs sit above it, and a single column of
                          these cards stretches badly on a wide screen. Each
                          card expands independently, so a grid is safe. */}
                      <div className="grid grid-cols-1 xl:grid-cols-2 gap-2 items-start">
                        {members.map((rec, i) => renderCard(rec, i))}
                      </div>
                    </div>
                  );
                })}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      {showSquadAnalysis && oppXiComplete && (
        <SquadStrengthModal
          team={team} opponent={opponent} venue={venue} format={format} gender={gender}
          squadStrength={squadStrength} opponentPlayerIds={oppXiIds} headToHead={headToHead}
          ourXi={ranked.filter(r => r.in_xi).map(r => ({
            player_id: r.player_id, player_name: r.player_name, role: r.role, score: r.score, reasons: r.reasons,
          }))}
          onClose={() => setShowSquadAnalysis(false)}
        />
      )}
    </div>
  );
}

import { useMemo, useState } from "react";
import { useEffect } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useNavigate } from "react-router";
import { Zap, ChevronDown, RefreshCw, CheckCircle2, AlertTriangle, PlayCircle, Sparkles } from "lucide-react";
import { RadialGauge } from "../components/common/RadialGauge";
import { SelectionControl } from "../components/common/SelectionControl";
import * as api from "../lib/api";
import { colorFor, initialsFor } from "../lib/mappers";
import { SimulatorPrefill } from "./SimulationPage";
import { useApp } from "../context/AppContext";
import { SelectionState } from "../types/index";

const COUNTRY_OPTIONS = ["India", "Australia", "England", "South Africa", "New Zealand", "Pakistan"];

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

export function RecommendationsPage() {
  const navigate = useNavigate();
  const { user } = useApp();
  const [generated, setGenerated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [team, setTeam] = useState(user?.country || "India");
  const [opponent, setOpponent] = useState("Australia");
  const [venue, setVenue] = useState("Melbourne Cricket Ground");
  const [format, setFormat] = useState("T20I");
  const [gender, setGender] = useState<"female" | "male">("female");
  const [simulating, setSimulating] = useState(false);
  // Shared with the Squads page (keyed by player_id) so a pick made here shows
  // up in the squad's Playing XI. Local component state would strand it here.
  const { selections, setSelections } = useApp();
  const [confirming, setConfirming] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [ranked, setRanked] = useState<Recommendation[]>([]);
  const [opponentXi, setOpponentXi] = useState<{ player_id: string; player_name: string; role: string; score: number }[] | null>(null);
  const [showOpponentXi, setShowOpponentXi] = useState(false);
  const selectedCount = Object.values(selections).filter(s => s === "select").length;
  // Snapshot of whichever params actually produced `ranked` -- compared
  // against the live dropdowns below so changing Team/Opponent/Venue/Format
  // after generating shows an explicit "stale, regenerate" notice instead of
  // silently leaving old results on screen with no indication they're outdated.
  const [generatedParams, setGeneratedParams] = useState<{ team: string; opponent: string; venue: string; format: string; gender: string } | null>(null);
  const stale = generated && generatedParams !== null &&
    (generatedParams.team !== team || generatedParams.opponent !== opponent ||
     generatedParams.venue !== venue || generatedParams.format !== format || generatedParams.gender !== gender);
  const squadStrength = useMemo(() => {
    const xi = ranked.filter(r => r.in_xi);
    return xi.length ? xi.reduce((s, r) => s + r.score, 0) / xi.length : 0;
  }, [ranked]);

  const teamLocked = !!user?.country;

  useEffect(() => {
    if (user?.country) setTeam(user.country);
  }, [user?.country]);

  const handleGenerate = async () => {
    setLoading(true);
    setError(null);
    try {
      const recRes = await api.recommendations({ team, opponent, venue, format, gender, auto_opponent_xi: true });
      setRanked(recRes.recommendations);
      setOpponentXi(recRes.opponent_xi);
      setGeneratedParams({ team, opponent, venue, format, gender });
      setGenerated(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't generate recommendations");
    } finally {
      setLoading(false);
    }
  };

  // Adopt the AI's constrained XI as the manual selection: mark every in_xi
  // player "select" and the rest of this pool "undecided", leaving any
  // selections for players outside this pool untouched.
  const resetToAiXi = () => {
    setSelections(prev => {
      const next = { ...prev };
      ranked.forEach(r => { next[r.player_id] = r.in_xi ? "select" : "undecided"; });
      return next;
    });
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
      const oppRes = await api.recommendations({ team: opponent, opponent: team, venue, format, gender });
      const team2PlayerIds = oppRes.recommendations.filter(r => r.in_xi).map(r => r.player_id);
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
          <button onClick={() => setExpandedId(expandedId === rec.player_name ? null : rec.player_name)} className="text-[11px] text-muted-foreground hover:text-foreground flex items-center gap-0.5 px-2">
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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Input panel */}
        <div className="space-y-4">
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
              {[{ label: "Team", value: team, set: setTeam, opts: COUNTRY_OPTIONS },
                { label: "Opponent", value: opponent, set: setOpponent, opts: ["Australia", "England", "South Africa", "New Zealand", "Pakistan", "India"] },
                // Real venues.canonical_name values -- the model fuzzy-matches this
                // against the DB (criiq_models/venues.py), so a name that isn't a
                // real ground (the old "MCG, Melbourne" / "Wankhede, Mumbai" style
                // strings) silently fails to match anything and venue conditioning
                // has zero effect, even though the request "succeeds".
                { label: "Venue", value: venue, set: setVenue, opts: ["Melbourne Cricket Ground", "Lord's", "Eden Gardens", "Wankhede Stadium", "Nassau County International Cricket Stadium"] },
                // T20I is the only supported format -- keep the field, drop ODI/Test.
                { label: "Format", value: format, set: setFormat, opts: ["T20I"] },
              ].map(field => (
                <div key={field.label} className="space-y-1">
                  <label className="text-[12px] text-muted-foreground">{field.label}</label>
                  {field.label === "Team" && teamLocked ? (
                    <button type="button" disabled
                      className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2 text-foreground text-left cursor-default">
                      {team}
                    </button>
                  ) : (
                    <select value={field.value} onChange={e => field.set(e.target.value)}
                      className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
                      {field.opts.map(o => <option key={o}>{o}</option>)}
                    </select>
                  )}
                </div>
              ))}
            </div>
            {stale && (
              <div className="mt-3 flex items-start gap-2 text-[12px] text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
                <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" />
                <span>Match parameters changed since these results were generated — click Generate Recommendation to refresh.</span>
              </div>
            )}
            <button onClick={handleGenerate} disabled={loading}
              className="w-full mt-3 py-2.5 bg-[#AAFF57] text-[#0D0D06] font-semibold text-sm rounded-lg hover:opacity-90 active:scale-[0.98] transition-all flex items-center justify-center gap-2 disabled:opacity-60">
              {loading ? <><RefreshCw size={14} className="animate-spin" /> Analysing…</> : <><Zap size={14} /> Generate Recommendation</>}
            </button>
          </div>

          {/* Squad strength — real average score of the AI's constrained XI
              within this pool (genuinely varies with team/opponent/venue,
              unlike a pre-match "win probability": criiq_models' win-prob
              model is a pure ball-by-ball game-state lookup with no team
              identity input at all, so it can't answer "who's favoured"
              before any XI exists — that only becomes a real number once two
              full XIs are simulated on the Simulator page). */}
          {generated && (
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="bg-card border border-border rounded-xl p-5">
              <h3 className="font-display text-base font-semibold text-foreground mb-1">Squad Strength</h3>
              <p className="text-[11px] text-muted-foreground mb-4">Avg score of the AI's {ranked.filter(r => r.in_xi).length}-player XI, this matchup</p>
              <div className="flex justify-center mb-4">
                <RadialGauge value={squadStrength} decimals={1} size={100} strokeWidth={7} color="#AAFF57" label="Score" />
              </div>
              <div className="space-y-2 text-[12px] mb-4">
                <p className="text-muted-foreground text-center">
                  {selectedCount === 0
                    ? "Tap Select on players below to build your own XI"
                    : `${selectedCount}/11 selected${selectedCount > 11 ? " — remove " + (selectedCount - 11) : ""}`}
                </p>
              </div>
              <button onClick={resetToAiXi}
                className="w-full mb-2 py-2 border border-[#AAFF57]/40 text-[#AAFF57] text-[12px] rounded-lg hover:bg-[#AAFF57]/10 active:scale-[0.98] transition-all flex items-center justify-center gap-1.5">
                <Sparkles size={13} /> Reset to AI's recommended XI
              </button>
              {selectedCount > 0 && (
                <button onClick={handleConfirm} disabled={confirming || selectedCount > 11}
                  className="w-full mb-2 py-2.5 bg-[#5FA800] text-white font-semibold text-[13px] rounded-lg hover:opacity-90 active:scale-[0.98] transition-all flex items-center justify-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed">
                  {confirming
                    ? <><RefreshCw size={14} className="animate-spin" /> Saving…</>
                    : <><CheckCircle2 size={14} /> Confirm Selection ({selectedCount}/11) → Squad</>}
                </button>
              )}
              <button onClick={handleSimulateXI} disabled={simulating}
                className="w-full py-2 border border-border text-foreground text-[12px] rounded-lg hover:border-[#AAFF57]/40 hover:text-[#AAFF57] transition-all flex items-center justify-center gap-1.5 disabled:opacity-60">
                {simulating
                  ? <><RefreshCw size={13} className="animate-spin" /> Preparing both XIs…</>
                  : <><PlayCircle size={13} /> Simulate this XI — get a real win probability</>}
              </button>
            </motion.div>
          )}
        </div>

        {/* Results */}
        <div className="lg:col-span-2">
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
                      {members.map((rec, i) => renderCard(rec, i))}
                    </div>
                  );
                })}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

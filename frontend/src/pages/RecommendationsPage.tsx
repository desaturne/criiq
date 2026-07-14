import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Zap, ChevronDown, RefreshCw } from "lucide-react";
import { RadialGauge } from "../components/common/RadialGauge";
import { SelectionControl } from "../components/common/SelectionControl";
import * as api from "../lib/api";
import { colorFor, initialsFor } from "../lib/mappers";
import { SelectionState } from "../types/index";

interface Recommendation { rank: number; player_name: string; role: string; score: number; reason: string; }

export function RecommendationsPage() {
  const [generated, setGenerated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [opponent, setOpponent] = useState("Australia");
  const [venue, setVenue] = useState("MCG, Melbourne");
  const [format, setFormat] = useState("T20I");
  const [pitch, setPitch] = useState("Pace-friendly");
  const [selections, setSelections] = useState<Record<string, SelectionState>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [ranked, setRanked] = useState<Recommendation[]>([]);
  const selectedCount = Object.values(selections).filter(s => s === "select").length;
  const [winProb, setWinProb] = useState(50);
  const [winFilled, setWinFilled] = useState(0);
  useEffect(() => {
    if (generated) { const t = setTimeout(() => setWinFilled(winProb), 600); return () => clearTimeout(t); }
  }, [generated, winProb]);

  const handleGenerate = async () => {
    setLoading(true);
    setError(null);
    try {
      const [recRes, winRes] = await Promise.all([
        api.recommendations({ opponent, venue, format }),
        api.winProb(),
      ]);
      setRanked(recRes.recommendations);
      setWinProb(Math.round(winRes.win_probability_batting * 100));
      setGenerated(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't generate recommendations");
    } finally {
      setLoading(false);
    }
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
            <h3 className="font-display text-base font-semibold text-foreground mb-4">Match Parameters</h3>
            <div className="space-y-3">
              {[{ label: "Opponent", value: opponent, set: setOpponent, opts: ["Australia", "England", "South Africa", "New Zealand", "Pakistan"] },
                { label: "Venue", value: venue, set: setVenue, opts: ["MCG, Melbourne", "Lord's, London", "Eden Gardens, Kolkata", "Wankhede, Mumbai", "Nassau County, USA"] },
                { label: "Format", value: format, set: setFormat, opts: ["T20I", "ODI", "Test"] },
                { label: "Pitch", value: pitch, set: setPitch, opts: ["Pace-friendly", "Spin-friendly", "Balanced", "Batting paradise", "Unpredictable"] }
              ].map(field => (
                <div key={field.label} className="space-y-1">
                  <label className="text-[12px] text-muted-foreground">{field.label}</label>
                  <select value={field.value} onChange={e => field.set(e.target.value)}
                    className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
                    {field.opts.map(o => <option key={o}>{o}</option>)}
                  </select>
                </div>
              ))}
            </div>
            <button onClick={handleGenerate} disabled={loading}
              className="w-full mt-4 py-2.5 bg-[#AAFF57] text-[#0D0D06] font-semibold text-sm rounded-lg hover:opacity-90 active:scale-[0.98] transition-all flex items-center justify-center gap-2 disabled:opacity-60">
              {loading ? <><RefreshCw size={14} className="animate-spin" /> Analysing…</> : <><Zap size={14} /> Generate Recommendation</>}
            </button>
          </div>

          {/* Win probability */}
          {generated && (
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="bg-card border border-border rounded-xl p-5">
              <h3 className="font-display text-base font-semibold text-foreground mb-4">Win Probability</h3>
              <div className="flex justify-center mb-4">
                <RadialGauge value={Math.round(winProb)} size={100} strokeWidth={7} color="#AAFF57" label="Win %" />
              </div>
              <div className="space-y-2 text-[12px]">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Current XI</span>
                  <span className="font-mono text-[#AAFF57] font-medium">{Math.round(winProb)}%</span>
                </div>
                <div className="h-1.5 rounded-full bg-border overflow-hidden">
                  <div className="h-full rounded-full bg-[#AAFF57] transition-all duration-1000" style={{ width: `${winFilled}%` }} />
                </div>
                <p className="text-muted-foreground text-center">Select {11 - selectedCount} more players to complete XI</p>
              </div>
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
                  <p className="text-[13px] text-muted-foreground">Ranked by recommendation score for <strong className="text-foreground">vs {opponent}</strong> at <strong className="text-foreground">{venue}</strong></p>
                  <span className="text-[12px] font-medium text-[#AAFF57]">{selectedCount}/11 selected</span>
                </div>
                {ranked.map((rec, i) => {
                  const color = colorFor(rec.player_name);
                  return (
                  <motion.div key={rec.rank} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.06 }}
                    className="bg-card border border-border rounded-xl overflow-hidden">
                    <div className="p-3 flex items-center gap-3">
                      <span className="font-mono text-[11px] text-muted-foreground w-5 text-right flex-shrink-0">#{rec.rank}</span>
                      <div className="w-8 h-8 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0" style={{ backgroundColor: color + "33", color }}>{initialsFor(rec.player_name)}</div>
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px] font-semibold text-foreground truncate">{rec.player_name}</div>
                        <div className="text-[10px] text-muted-foreground capitalize">{rec.role}</div>
                      </div>
                      <RadialGauge value={Math.round(rec.score)} size={44} strokeWidth={3.5} color={rec.score >= 85 ? "#AAFF57" : rec.score >= 70 ? "#60A5FA" : "#FB923C"} />
                      <button onClick={() => setExpandedId(expandedId === rec.player_name ? null : rec.player_name)} className="text-[11px] text-muted-foreground hover:text-foreground flex items-center gap-0.5 px-2">
                        Explain <ChevronDown size={10} className={`transition-transform ${expandedId === rec.player_name ? "rotate-180" : ""}`} />
                      </button>
                      <SelectionControl state={selections[rec.player_name] || "undecided"} onChange={s => setSelections(prev => ({ ...prev, [rec.player_name]: s }))} />
                    </div>
                    <AnimatePresence>
                      {expandedId === rec.player_name && (
                        <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden border-t border-border">
                          <div className="p-4 bg-secondary/30">
                            <p className="text-[12px] text-muted-foreground mb-1 font-medium">Why this recommendation</p>
                            <p className="text-[12px] text-foreground leading-relaxed">{rec.reason}</p>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </motion.div>
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

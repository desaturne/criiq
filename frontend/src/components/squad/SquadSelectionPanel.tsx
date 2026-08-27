import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { CheckCircle, X, TrendingUp, TrendingDown, ArrowRight, Loader2, ClipboardCheck } from "lucide-react";
import { AvatarWithRing } from "../common/AvatarWithRing";
import { SparkLine } from "../common/SparkLine";
import { AnalyzeXiModal } from "./AnalyzeXiModal";
import * as api from "../../lib/api";
import { Player, SelectionState } from "../../types/index";

export function SquadSelectionPanel({ players, selections, team, gender, opposition, format, onClose, onReset, onChangeSelection }: {
  players: Player[];
  selections: Record<string, SelectionState>;
  // `team` and `gender` describe whose squad is on screen. They're passed down
  // rather than assumed: this panel used to hand AnalyzeXiModal a literal
  // "India", so a coach registered to any other country had their XI analysed
  // against India's roster.
  team: string; gender: "female" | "male";
  opposition: string; format: string;
  onClose: () => void; onReset: () => void;
  onChangeSelection: (id: string, s: SelectionState) => void;
}) {
  const selected  = players.filter(p => selections[p.id] === "select");
  const reserves  = players.filter(p => selections[p.id] === "reserve");
  const excluded  = players.filter(p => selections[p.id] === "exclude");
  const batters   = selected.filter(p => p.isBatsman).length;
  const bowlers   = selected.filter(p => !p.isBatsman && p.role === "Bowler").length;
  const allRound  = selected.filter(p => p.role === "All-rounder").length;
  const isComplete = selected.length === 11;

  // Squad selections are saved per-match; use the next upcoming fixture as
  // the implicit "current match" since there's no match picker in this panel.
  const [matchId, setMatchId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showAnalysis, setShowAnalysis] = useState(false);

  useEffect(() => {
    api.listMatches().then(res => setMatchId(res.upcoming[0]?.id ?? null)).catch(() => setMatchId(null));
  }, []);

  const handleSave = async () => {
    if (!matchId) return;
    setSaving(true);
    try {
      await api.saveSelection(matchId, {
        xi: selected.map(p => p.id), extra: reserves.map(p => p.id), excluded: excluded.map(p => p.id),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  const roleTag = (role: string) => {
    if (role === "Batter" || role === "Batsman") return { bg: "bg-blue-500/15", text: "text-blue-400" };
    if (role === "Bowler")     return { bg: "bg-orange-500/15",  text: "text-orange-400" };
    if (role === "All-rounder") return { bg: "bg-[#5FA800]/15",  text: "text-[#5FA800]" };
    return { bg: "bg-secondary", text: "text-muted-foreground" };
  };

  return (
    <motion.div
      className="fixed inset-0 z-50 flex"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      {/* Slide-in panel from right */}
      <motion.div
        className="relative ml-auto flex flex-col bg-background h-full overflow-hidden"
        style={{ width: "min(780px, 95vw)" }}
        initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }}
        transition={{ type: "spring", damping: 30, stiffness: 300 }}
      >
        {/* ── Header ── */}
        <div className="flex-shrink-0 border-b border-border px-6 pt-5 pb-4 bg-background">
          <div className="flex items-start justify-between mb-4">
            <div>
              <h2 className="font-display text-2xl font-bold text-foreground">Squad Selection</h2>
              <p className="text-[13px] text-muted-foreground mt-0.5">
                Match vs {opposition} · {format}
              </p>
            </div>
            <button onClick={onClose} className="p-2 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors mt-0.5">
              <X size={16} />
            </button>
          </div>

          {/* Stat chips row */}
          <div className="flex gap-3 flex-wrap">
            {[
              { label: "BATTERS",      count: batters,           color: "#60A5FA" },
              { label: "BOWLERS",      count: bowlers,           color: "#FB923C" },
              { label: "ALL-ROUNDERS", count: allRound,          color: "#5FA800" },
              { label: "TOTAL",        count: `${selected.length}/11`, color: isComplete ? "#5FA800" : "var(--foreground)" },
            ].map(chip => (
              <div key={chip.label} className="flex items-baseline gap-2 bg-secondary rounded-xl px-4 py-2.5">
                <span className="font-mono text-2xl font-bold tabular-nums" style={{ color: chip.color }}>{chip.count}</span>
                <span className="text-[10px] font-semibold text-muted-foreground tracking-widest">{chip.label}</span>
              </div>
            ))}
            {isComplete && (
              <motion.div initial={{ scale: 0.8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
                className="flex items-center gap-2 bg-[#5FA800]/10 border border-[#5FA800]/30 rounded-xl px-4 py-2.5">
                <CheckCircle size={14} className="text-[#5FA800]" />
                <span className="text-[12px] font-semibold text-[#5FA800]">XI Complete</span>
              </motion.div>
            )}
          </div>
        </div>

        {/* ── Body ── */}
        <div className="flex-1 overflow-auto">
          <div className="p-6 grid grid-cols-3 gap-5 min-h-full">

            {/* Playing XI — 2 cols */}
            <div className="col-span-2">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-display text-[15px] font-semibold text-foreground">
                  Playing XI <span className="text-muted-foreground font-normal">({selected.length}/11)</span>
                </h3>
                <span className="text-[11px] text-muted-foreground">Click × to remove</span>
              </div>

              <div className="space-y-2">
                {selected.map((p, i) => {
                  const rc = roleTag(p.role);
                  const lastForm = p.recentForm[p.recentForm.length - 1];
                  const trend = p.recentForm[p.recentForm.length - 1] > p.recentForm[0];
                  return (
                    <motion.div key={p.id}
                      initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.04, type: "spring", stiffness: 400, damping: 30 }}
                      className="flex items-center gap-3 px-4 py-3 bg-card rounded-xl border border-[#5FA800]/25 group hover:border-[#5FA800]/50 transition-colors"
                    >
                      <span className="font-mono text-[13px] text-muted-foreground w-5 text-right flex-shrink-0">{i + 1}</span>
                      <AvatarWithRing initials={p.initials} color={p.color} selection="select" size={30} />
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-[13px] text-foreground truncate">{p.name}</div>
                        <div className="text-[10px] text-muted-foreground truncate">{p.battingHand} · {p.bowlingStyle !== "—" ? p.bowlingStyle : "Bat only"}</div>
                      </div>
                      <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium flex-shrink-0 ${rc.bg} ${rc.text}`}>{p.role}</span>
                      {/* Sparkline mini */}
                      <SparkLine values={p.recentForm} color={p.color} width={44} height={20} />
                      <div className="text-right flex-shrink-0 w-10">
                        <div className="font-mono text-[13px] font-bold" style={{ color: p.color }}>{lastForm}</div>
                        <div className="flex items-center justify-end gap-0.5 text-[9px]" style={{ color: trend ? "#5FA800" : "#E5484D" }}>
                          {trend ? <TrendingUp size={9} /> : <TrendingDown size={9} />}
                          {p.isBatsman ? "runs" : "wkts"}
                        </div>
                      </div>
                      <button onClick={() => onChangeSelection(p.id, "undecided")}
                        className="opacity-0 group-hover:opacity-100 p-1 rounded-full hover:bg-secondary text-muted-foreground hover:text-[#E5484D] transition-all flex-shrink-0">
                        <X size={12} />
                      </button>
                    </motion.div>
                  );
                })}

                {/* Empty slots */}
                {Array.from({ length: Math.max(0, 11 - selected.length) }).map((_, i) => (
                  <div key={i}
                    className="flex items-center gap-3 px-4 py-3 border border-dashed border-border rounded-xl opacity-40">
                    <span className="font-mono text-[13px] text-muted-foreground w-5 text-right">{selected.length + i + 1}</span>
                    <div className="w-9 h-9 rounded-full border-2 border-dashed border-border flex-shrink-0" />
                    <span className="text-[12px] text-muted-foreground italic">Empty slot</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Right column — Reserves + Excluded */}
            <div className="space-y-5">
              {/* Reserves */}
              <div>
                <h3 className="font-display text-[15px] font-semibold text-foreground mb-3">
                  Extras <span className="text-muted-foreground font-normal">({reserves.length})</span>
                </h3>
                <div className="space-y-2">
                  {reserves.map((p, i) => (
                    <motion.div key={p.id}
                      initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.05, type: "spring", stiffness: 400, damping: 30 }}
                      className="flex items-center gap-2.5 px-3 py-2.5 bg-card rounded-xl border border-border group hover:border-muted-foreground/30 transition-colors"
                    >
                      <AvatarWithRing initials={p.initials} color={p.color} selection="reserve" size={28} />
                      <div className="flex-1 min-w-0">
                        <div className="font-medium text-[12px] text-foreground truncate">{p.name}</div>
                        <div className="text-[10px] text-muted-foreground">{p.role}</div>
                      </div>
                      <button onClick={() => onChangeSelection(p.id, "select")}
                        className="opacity-0 group-hover:opacity-100 p-1 rounded text-muted-foreground hover:text-[#5FA800] transition-all flex-shrink-0"
                        title="Promote to XI">
                        <ArrowRight size={11} />
                      </button>
                    </motion.div>
                  ))}
                  {reserves.length === 0 && (
                    <div className="text-center py-5 text-[12px] text-muted-foreground border border-dashed border-border rounded-xl">
                      No reserves yet
                    </div>
                  )}
                </div>
              </div>

              {/* Excluded */}
              {excluded.length > 0 && (
                <div>
                  <h3 className="font-display text-[13px] font-semibold text-muted-foreground mb-2">
                    Excluded ({excluded.length})
                  </h3>
                  <div className="space-y-1.5">
                    {excluded.map(p => (
                      <div key={p.id} className="flex items-center gap-2.5 px-3 py-2 bg-card rounded-xl border border-[#E5484D]/20">
                        <AvatarWithRing initials={p.initials} color={p.color} selection="exclude" size={24} />
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-[11px] text-muted-foreground line-through truncate">{p.name}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Footer actions ── */}
        <div className="flex-shrink-0 border-t border-border px-6 py-4 bg-background flex items-center gap-3">
          <motion.button
            whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
            onClick={handleSave}
            disabled={!isComplete || saving || !matchId}
            className="flex-1 py-3 font-semibold text-sm rounded-xl flex items-center justify-center gap-2 transition-all disabled:cursor-not-allowed"
            style={{ background: isComplete ? "#5FA800" : "var(--secondary)", color: isComplete ? "#fff" : "var(--muted-foreground)" }}
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle size={15} />}
            {saved ? "Saved!" : saving ? "Saving…" : isComplete ? "Save Playing XI" : `Select ${11 - selected.length} more…`}
          </motion.button>
          <button onClick={() => setShowAnalysis(true)} disabled={!isComplete}
            className="flex items-center gap-1.5 px-5 py-3 border border-border text-muted-foreground text-sm rounded-xl hover:text-foreground hover:border-foreground/30 transition-all disabled:opacity-40 disabled:cursor-not-allowed">
            <ClipboardCheck size={14} /> Analyze this XI
          </button>
          <button onClick={onReset}
            className="px-6 py-3 border border-border text-muted-foreground text-sm rounded-xl hover:text-foreground hover:border-foreground/30 transition-all">
            Reset
          </button>
        </div>
      </motion.div>

      {showAnalysis && (
        <AnalyzeXiModal team={team} gender={gender} opponent={opposition} playerIds={selected.map(p => p.id)}
          onClose={() => setShowAnalysis(false)} />
      )}
    </motion.div>
  );
}

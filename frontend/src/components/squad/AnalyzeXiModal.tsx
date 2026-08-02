import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { X, ClipboardCheck, AlertTriangle, Loader2 } from "lucide-react";
import * as api from "../../lib/api";

// `gender` is required, not optional: the backend defaults it to "female", so
// omitting it for a men's XI made every player fall outside the scoped roster
// and the endpoint answered with an empty xi and 11 missing_player_ids.
export function AnalyzeXiModal({ team, opponent, gender, playerIds, onClose }: {
  team: string; opponent: string; gender: "female" | "male";
  playerIds: string[]; onClose: () => void;
}) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);

  useEffect(() => {
    let cancelled = false;
    api.analyzeXi({ team, opponent, gender, player_ids: playerIds })
      .then(res => { if (!cancelled) setResult(res); })
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : "Couldn't analyze this XI"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [team, opponent, gender, playerIds]);

  const comparison = result?.comparison_to_optimal;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4"
        style={{ background: "rgba(0,0,0,0.75)", backdropFilter: "blur(4px)" }}
        onClick={e => e.target === e.currentTarget && onClose()}
      >
        <motion.div
          initial={{ y: 60, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 60, opacity: 0 }}
          transition={{ type: "spring", damping: 28, stiffness: 280 }}
          className="bg-card border border-border rounded-t-2xl sm:rounded-2xl w-full max-w-2xl overflow-hidden flex flex-col"
          style={{ maxHeight: "85vh" }}
        >
          <div className="flex items-center justify-between px-6 py-4 border-b border-border flex-shrink-0">
            <div className="flex items-center gap-2.5">
              <ClipboardCheck size={16} style={{ color: "#AAFF57" }} />
              <h2 className="font-display text-[17px] font-semibold text-foreground">Analyze This XI</h2>
              <span className="text-[11px] text-muted-foreground">vs {opponent}</span>
            </div>
            <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors">
              <X size={16} />
            </button>
          </div>

          <div className="overflow-auto flex-1 p-5">
            {loading && (
              <div className="h-40 flex flex-col items-center justify-center text-center gap-3">
                <Loader2 size={22} className="text-[#AAFF57] animate-spin" />
                <p className="text-sm text-muted-foreground">Scoring this XI against the AI's optimal pick…</p>
              </div>
            )}
            {!loading && error && (
              <div className="h-40 flex items-center justify-center text-center">
                <p className="text-sm text-red-400">{error}</p>
              </div>
            )}
            {!loading && !error && result && (
              <div className="space-y-5">
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-secondary/50 rounded-xl p-4 text-center">
                    <div className="font-mono text-2xl font-bold text-foreground">{result.total_score?.toFixed?.(1) ?? result.total_score}</div>
                    <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-1">Total Score</div>
                  </div>
                  <div className="bg-secondary/50 rounded-xl p-4 text-center">
                    <div className="font-mono text-2xl font-bold text-foreground">{result.average_score?.toFixed?.(1) ?? result.average_score}</div>
                    <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-1">Average Score</div>
                  </div>
                </div>

                {result.violations?.length > 0 && (
                  <div className="bg-amber-500/10 border border-amber-500/20 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-2 text-amber-400 text-[12px] font-semibold">
                      <AlertTriangle size={13} /> Constraint issues
                    </div>
                    <ul className="space-y-1 text-[12px] text-foreground">
                      {result.violations.map((v: string, i: number) => <li key={i}>• {v}</li>)}
                    </ul>
                  </div>
                )}

                {comparison && (
                  <div>
                    <h3 className="text-[12px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                      vs the AI's optimal XI ({comparison.score_gap != null ? `${comparison.score_gap > 0 ? "+" : ""}${comparison.score_gap.toFixed?.(1) ?? comparison.score_gap} pts` : "—"})
                    </h3>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <p className="text-[11px] text-muted-foreground mb-1.5">Only in your XI</p>
                        <div className="space-y-1">
                          {(comparison.in_chosen_not_optimal ?? []).map((p: any, i: number) => (
                            <div key={i} className="text-[12px] text-foreground bg-secondary/30 rounded-lg px-2.5 py-1.5">{p.name ?? p}</div>
                          ))}
                        </div>
                      </div>
                      <div>
                        <p className="text-[11px] text-muted-foreground mb-1.5">Only in the optimal XI</p>
                        <div className="space-y-1">
                          {(comparison.in_optimal_not_chosen ?? []).map((p: any, i: number) => (
                            <div key={i} className="text-[12px] text-foreground bg-secondary/30 rounded-lg px-2.5 py-1.5">{p.name ?? p}</div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                <div>
                  <h3 className="text-[12px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">Per-player reasoning</h3>
                  <div className="space-y-2">
                    {(result.xi ?? []).map((p: any) => (
                      <div key={p.player_id ?? p.name} className="bg-secondary/30 rounded-lg px-3 py-2">
                        <div className="flex items-center justify-between mb-0.5">
                          <span className="text-[13px] font-medium text-foreground">{p.name}</span>
                          <span className="font-mono text-[12px] text-[#AAFF57]">{p.score?.toFixed?.(1) ?? p.score}</span>
                        </div>
                        {p.reasoning && (
                          <p className="text-[11px] text-muted-foreground leading-relaxed">
                            {Array.isArray(p.reasoning) ? p.reasoning.join(" ") : p.reasoning}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

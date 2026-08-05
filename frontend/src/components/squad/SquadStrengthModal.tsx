import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { X, Loader2, Target, TrendingUp, AlertTriangle, ListOrdered, Trophy } from "lucide-react";
import * as api from "../../lib/api";

interface XiMember { player_id: string; player_name: string; role: string; score: number; reasons: string[]; }

export function SquadStrengthModal({ team, opponent, venue, format, gender, squadStrength, ourXi, opponentPlayerIds,
  headToHead, onClose }: {
  team: string; opponent: string; venue: string; format: string; gender: "female" | "male";
  squadStrength: number; ourXi: XiMember[]; opponentPlayerIds: string[];
  headToHead: api.HeadToHeadTeam | null;
  onClose: () => void;
}) {
  const ourIds = useMemo(() => ourXi.map(p => p.player_id), [ourXi]);
  const ourNames = useMemo(() => ourXi.map(p => p.player_name), [ourXi]);

  const [orderResult, setOrderResult] = useState<Awaited<ReturnType<typeof api.optimizeBatting>> | "loading" | "error">("loading");
  const [simResult, setSimResult] = useState<any | "loading" | "error">("loading");

  useEffect(() => {
    let cancelled = false;
    setOrderResult("loading");
    api.optimizeBatting({ batting_team: team, bowling_team: opponent, batting_player_ids: ourIds,
      bowling_player_ids: opponentPlayerIds, venue, format, gender })
      .then(res => { if (!cancelled) setOrderResult(res); })
      .catch(() => { if (!cancelled) setOrderResult("error"); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let cancelled = false;
    setSimResult("loading");
    api.simulateMatch({ team1: team, team2: opponent, team1_player_ids: ourIds, team2_player_ids: opponentPlayerIds,
      toss_winner: team, n_simulations: 20, venue, format, gender })
      .then(res => { if (!cancelled) setSimResult(res); })
      .catch(() => { if (!cancelled) setSimResult("error"); })
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const target = useMemo(() => buildTargetSummary(headToHead, ourNames), [headToHead, ourNames]);
  const winPct = simResult !== "loading" && simResult !== "error" ? simResult.win_probability_pct?.[team] : undefined;

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
              <Trophy size={16} style={{ color: "#AAFF57" }} />
              <h2 className="font-display text-[17px] font-semibold text-foreground">Squad Analysis</h2>
              <span className="text-[11px] text-muted-foreground">vs {opponent}</span>
            </div>
            <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors">
              <X size={16} />
            </button>
          </div>

          <div className="overflow-auto flex-1 p-5 space-y-5">
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-secondary/50 rounded-xl p-4 text-center">
                <div className="font-mono text-2xl font-bold text-foreground">{squadStrength.toFixed(1)}</div>
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-1">Squad Strength</div>
              </div>
              <div className="bg-secondary/50 rounded-xl p-4 text-center">
                {simResult === "loading" ? (
                  <Loader2 size={18} className="mx-auto animate-spin text-[#AAFF57]" />
                ) : simResult === "error" ? (
                  <div className="font-mono text-sm text-muted-foreground">—</div>
                ) : (
                  <div className="font-mono text-2xl font-bold text-foreground">{winPct != null ? `${winPct}%` : "—"}</div>
                )}
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-1">Match Win Rate</div>
              </div>
            </div>
            {simResult !== "loading" && simResult !== "error" && (
              <p className="text-[11px] text-muted-foreground -mt-3 text-center">
                From {simResult.n_simulations} simulated match{simResult.n_simulations === 1 ? "" : "es"} of this XI vs {opponent}'s named XI
                {venue ? ` at ${venue}` : ""}.
              </p>
            )}

            {/* Aggregated from matchup_matrix.py's per-player head-to-head records. */}
            <div>
              <h3 className="text-[12px] font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <Target size={12} /> Who to target
              </h3>
              {!headToHead || (!target.battingTarget && !target.bowlingTarget && !target.bogey && !target.danger) ? (
                <p className="text-[11px] text-muted-foreground bg-secondary/30 rounded-lg px-3 py-2">
                  No recorded ball-by-ball history between these two named XIs yet -- picks above rest on form and team-level records only.
                </p>
              ) : (
                <div className="space-y-1.5">
                  {target.battingTarget && (
                    <p className="text-[11px] text-foreground bg-[#AAFF57]/10 border border-[#AAFF57]/20 rounded-lg px-3 py-2 leading-relaxed">
                      <TrendingUp size={11} className="inline mr-1 text-[#AAFF57]" />
                      With the bat, target <strong>{target.battingTarget.name}</strong> — {target.battingTarget.ourPlayer} has struck at{" "}
                      <strong>{target.battingTarget.strikeRate}</strong> SR off them ({target.battingTarget.balls} balls faced).
                    </p>
                  )}
                  {target.bowlingTarget && (
                    <p className="text-[11px] text-foreground bg-[#AAFF57]/10 border border-[#AAFF57]/20 rounded-lg px-3 py-2 leading-relaxed">
                      <TrendingUp size={11} className="inline mr-1 text-[#AAFF57]" />
                      With the ball, target <strong>{target.bowlingTarget.name}</strong> — {target.bowlingTarget.ourPlayer} has dismissed them{" "}
                      <strong>{target.bowlingTarget.dismissals}</strong> time{target.bowlingTarget.dismissals === 1 ? "" : "s"} in {target.bowlingTarget.balls} balls.
                    </p>
                  )}
                  {target.bogey && (
                    <p className="text-[11px] text-foreground bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2 leading-relaxed">
                      <AlertTriangle size={11} className="inline mr-1 text-amber-400" />
                      Watch out for <strong>{target.bogey.name}</strong> — dismissed {target.bogey.ourPlayer}{" "}
                      <strong>{target.bogey.dismissals}</strong> time{target.bogey.dismissals === 1 ? "" : "s"} in {target.bogey.balls} balls.
                    </p>
                  )}
                  {target.danger && (
                    <p className="text-[11px] text-foreground bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2 leading-relaxed">
                      <AlertTriangle size={11} className="inline mr-1 text-amber-400" />
                      <strong>{target.danger.name}</strong> counters {target.danger.ourPlayer} well — economy{" "}
                      <strong>{target.danger.economy}</strong> in {target.danger.balls} balls.
                    </p>
                  )}
                </div>
              )}
            </div>

            {/* Batting order + justification + in-match contingencies */}
            <div>
              <h3 className="text-[12px] font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <ListOrdered size={12} /> Batting order
              </h3>
              {orderResult === "loading" ? (
                <div className="flex items-center gap-2 text-[12px] text-muted-foreground py-3">
                  <Loader2 size={14} className="animate-spin text-[#AAFF57]" /> Searching for the best order… (~20s)
                </div>
              ) : orderResult === "error" ? (
                <p className="text-[11px] text-muted-foreground">Couldn't compute a batting order for this matchup.</p>
              ) : (
                <BattingOrderSection result={orderResult} />
              )}
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

function BattingOrderSection({ result }: { result: Awaited<ReturnType<typeof api.optimizeBatting>> }) {
  const explanation = result.explanation;
  const name = (pid: string) => result.batting_order.find(b => b.player_id === pid)?.name ?? pid;
  const metricLabel = result.metric_name === "win_probability" ? "win probability" : "expected score";
  const swap = explanation?.most_costly_adjacent_swap;
  const contingency = explanation?.contingency;

  return (
    <div className="space-y-3">
      <div className="space-y-1 max-h-48 overflow-auto pr-1">
        {result.batting_order.map(b => (
          <div key={b.position} className="flex items-center gap-2 text-[12px] px-2 py-1.5 rounded-lg bg-secondary/30">
            <span className="font-mono text-muted-foreground w-5 text-right">{b.position}</span>
            <span className="text-foreground font-medium">{b.name}</span>
          </div>
        ))}
      </div>

      {explanation && (
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Justification: vs a naive strike-rate-sorted order, this order lifts {metricLabel} by{" "}
          <strong className={explanation.improvement_over_baseline >= 0 ? "text-[#AAFF57]" : "text-red-400"}>
            {explanation.improvement_over_baseline >= 0 ? "+" : ""}{explanation.improvement_over_baseline}
          </strong>{swap && (
            <> Most order-sensitive pair: <strong className="text-foreground">{name(swap.player_ids[0])}</strong> /{" "}
              <strong className="text-foreground">{name(swap.player_ids[1])}</strong> (positions {swap.positions[0]}-{swap.positions[1]}),
              worth {swap.delta >= 0 ? "+" : ""}{swap.delta} {metricLabel} if swapped.</>
          )}
        </p>
      )}

      {contingency && (
        <div className="space-y-1.5">
          <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
            <p className="text-[11px] font-semibold text-amber-400">
              Early collapse → send in {name(contingency.early_collapse.player_id)}
            </p>
            <p className="text-[11px] text-muted-foreground leading-relaxed mt-0.5">{contingency.early_collapse.reason}</p>
          </div>
          <div className="bg-[#AAFF57]/10 border border-[#AAFF57]/25 rounded-lg px-3 py-2">
            <p className="text-[11px] font-semibold text-[#AAFF57]">
              Quick run chase → promote {name(contingency.quick_chase.player_id)}
            </p>
            <p className="text-[11px] text-muted-foreground leading-relaxed mt-0.5">{contingency.quick_chase.reason}</p>
          </div>
        </div>
      )}
    </div>
  );
}

// Picks the single strongest signal in each direction across the whole XI.
function buildTargetSummary(h2h: api.HeadToHeadTeam | null, ourNames: string[]) {
  const battingTargets: { name: string; strikeRate: number; balls: number; ourPlayer: string }[] = [];
  const bogeys: { name: string; dismissals: number; balls: number; ourPlayer: string }[] = [];
  const bowlingTargets: { name: string; dismissals: number; balls: number; ourPlayer: string }[] = [];
  const dangers: { name: string; economy: number; balls: number; ourPlayer: string }[] = [];

  if (h2h) {
    for (const ourPlayer of ourNames) {
      const bat = h2h.batting[ourPlayer];
      if (bat?.best?.strike_rate != null) {
        battingTargets.push({ name: bat.best.opponent, strikeRate: bat.best.strike_rate, balls: bat.best.balls, ourPlayer });
      }
      if (bat?.bogey && bat.bogey.dismissals > 0) {
        bogeys.push({ name: bat.bogey.opponent, dismissals: bat.bogey.dismissals, balls: bat.bogey.balls, ourPlayer });
      }
      const bowl = h2h.bowling[ourPlayer];
      if (bowl?.best && bowl.best.dismissals > 0) {
        bowlingTargets.push({ name: bowl.best.opponent, dismissals: bowl.best.dismissals, balls: bowl.best.balls, ourPlayer });
      }
      if (bowl?.most_expensive?.economy != null) {
        dangers.push({ name: bowl.most_expensive.opponent, economy: bowl.most_expensive.economy, balls: bowl.most_expensive.balls, ourPlayer });
      }
    }
  }

  return {
    battingTarget: battingTargets.sort((a, b) => b.strikeRate - a.strikeRate)[0],
    bogey: bogeys.sort((a, b) => b.dismissals - a.dismissals)[0],
    bowlingTarget: bowlingTargets.sort((a, b) => b.dismissals - a.dismissals)[0],
    danger: dangers.sort((a, b) => b.economy - a.economy)[0],
  };
}

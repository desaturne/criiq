import React, { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { X, GitCompare, Loader2 } from "lucide-react";
import { RadialGauge } from "../common/RadialGauge";
import { SelectionControl } from "../common/SelectionControl";
import { SparkLine } from "../common/SparkLine";
import { StatusBadge } from "../common/StatusBadge";
import * as api from "../../lib/api";
import { applyVsOpponent, mapApiPlayerDetail } from "../../lib/mappers";
import { Player, SelectionState } from "../../types/index";

export function PlayerCompareModal({
  players: listPlayers,
  playerIds,
  opposition,
  selections,
  onSelect,
  onClose,
  onRemove,
}: {
  players: Player[];
  playerIds: string[];
  opposition: string;
  selections: Record<string, SelectionState>;
  onSelect: (id: string, s: SelectionState) => void;
  onClose: () => void;
  onRemove: (id: string) => void;
}) {
  // The list view's Player objects have vsOpponent/phase/breakdown all
  // zeroed out (only /players/{id} and /players/{id}/vs/{opponent} compute
  // those) -- fetch the real detail card for each compared player instead of
  // showing those placeholder zeros as if they were real stats.
  const [detailed, setDetailed] = useState<Record<string, Player>>({});
  useEffect(() => {
    let cancelled = false;
    Promise.all(playerIds.map(id =>
      api.getPlayer(id).then(d => {
        let player = mapApiPlayerDetail(d);
        return api.getPlayerVsOpponent(id, opposition)
          .then(vs => applyVsOpponent(player, vs, opposition))
          .catch(() => player);
      })
    )).then(results => {
      if (cancelled) return;
      setDetailed(Object.fromEntries(results.map(p => [p.id, p])));
    });
    return () => { cancelled = true; };
  }, [playerIds.join(","), opposition]); // eslint-disable-line react-hooks/exhaustive-deps

  const players = playerIds
    .map(id => detailed[id] ?? listPlayers.find(p => p.id === id))
    .filter((p): p is Player => !!p);
  const loading = players.length < playerIds.length || playerIds.some(id => !detailed[id]);

  const statRows: { label: string; render: (p: Player) => React.ReactNode }[] = [
    {
      label: "Recent Form",
      render: p => (
        <div className="flex flex-col gap-2">
          <SparkLine values={p.recentForm} color={p.color} width={100} height={28} />
          <div className="flex gap-1.5 justify-center">
            {p.recentForm.map((v, i) => (
              <div key={i} className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-mono font-bold"
                   style={{ background: p.color + "22", color: p.color }}>
                {v}
              </div>
            ))}
          </div>
        </div>
      ),
    },
    {
      label: `vs ${opposition}`,
      render: p => (
        <div className="flex flex-col items-center gap-1.5">
          <RadialGauge value={p.vsOpponent} size={64} strokeWidth={5} color={p.color} label={`${p.vsOpponent}%`} />
          <p className="text-[11px] text-muted-foreground text-center leading-snug max-w-[160px]">{p.vsInsight}</p>
        </div>
      ),
    },
    {
      label: "Phase Performance",
      render: p => (
        <div className="space-y-2">
          {[
            { label: "Powerplay", val: p.powerplay, color: "#60A5FA" },
            { label: "Middle",    val: p.middle,    color: "#AAFF57" },
            { label: "Death",     val: p.death,     color: "#FB923C" },
          ].map(ph => (
            <div key={ph.label}>
              <div className="flex justify-between text-[10px] text-muted-foreground mb-1">
                <span>{ph.label}</span><span className="font-mono">{ph.val}%</span>
              </div>
              <div className="h-1.5 rounded-full bg-secondary overflow-hidden">
                <motion.div initial={{ width: 0 }} animate={{ width: `${ph.val}%` }}
                  transition={{ duration: 0.7, ease: "easeOut" }}
                  className="h-full rounded-full" style={{ background: ph.color }} />
              </div>
            </div>
          ))}
        </div>
      ),
    },
    {
      label: "Career Stats",
      render: p => {
        const stats = p.isBatsman
          ? [{ k: "Matches", v: p.career.matches }, { k: "Avg", v: p.career.avg ?? "—" }, { k: "SR", v: p.career.sr ?? "—" }, { k: "50s/100s", v: `${p.career.fifties ?? 0}/${p.career.hundreds ?? 0}` }]
          : [{ k: "Matches", v: p.career.matches }, { k: "Wkts", v: p.career.wickets ?? "—" }, { k: "Eco", v: p.career.economy ?? "—" }, { k: "Best", v: p.career.best ?? "—" }];
        return (
          <div className="grid grid-cols-2 gap-x-4 gap-y-2">
            {stats.map(s => (
              <div key={s.k} className="text-center p-2 rounded-lg bg-secondary/50">
                <div className="font-mono text-[15px] font-bold text-foreground">{s.v}</div>
                <div className="text-[9px] text-muted-foreground uppercase tracking-wider mt-0.5">{s.k}</div>
              </div>
            ))}
          </div>
        );
      },
    },
    {
      label: "Fielding",
      render: p => {
        const f = p.fielding;
        if (!f || f.matches === 0) {
          return <div className="text-[11px] text-muted-foreground text-center py-2">No fielding record</div>;
        }
        const MIN_MATCHES_FOR_RATE = 5;
        const rankValue = (x: NonNullable<Player["fielding"]>) =>
          x.matches >= MIN_MATCHES_FOR_RATE && x.dismissalsPerMatch != null ? x.dismissalsPerMatch : x.dismissals;
        const bestValue = Math.max(...players.map(pl => pl.fielding ? rankValue(pl.fielding) : -Infinity));
        const isBest = players.length > 1 && bestValue > 0 && rankValue(f) === bestValue;
        return (
          <div className="space-y-2">
            <div className="grid grid-cols-3 gap-1.5">
              {[{ k: "Catches", v: f.catches }, { k: "Run-outs", v: f.runOuts }, { k: "Stumpings", v: f.stumpings }].map(s => (
                <div key={s.k} className="text-center p-1.5 rounded-lg bg-secondary/50">
                  <div className="font-mono text-[13px] font-bold text-foreground">{s.v}</div>
                  <div className="text-[8px] text-muted-foreground uppercase tracking-wider mt-0.5">{s.k}</div>
                </div>
              ))}
            </div>
            {isBest && (
              <div className="text-[10px] font-semibold text-center py-1 rounded-md"
                   style={{ background: "#AAFF5722", color: "#AAFF57" }}>
                Better Fielder
              </div>
            )}
          </div>
        );
      },
    },
    {
      // Only real, backend-computed numbers: Form is a percentile rank
      // against every player's recent-form index; Total Score is the
      // model's importance_score (proven track record + ICC rank). The
      // per-opponent/venue/matchup sub-scores this used to show were never
      // computed anywhere and always rendered as 0 -- removed rather than
      // faked. See the AI Recommendations page for real per-opponent scoring.
      label: "AI Score",
      render: p => (
        <div className="space-y-2">
          <div>
            <div className="flex justify-between text-[10px] text-muted-foreground mb-1">
              <span>Recent form (percentile)</span><span className="font-mono font-semibold text-[#AAFF57]">{p.breakdown.form}</span>
            </div>
            <div className="h-1 rounded-full bg-secondary overflow-hidden">
              <motion.div initial={{ width: 0 }} animate={{ width: `${p.breakdown.form}%` }}
                transition={{ duration: 0.8, ease: "easeOut" }} className="h-full rounded-full bg-[#AAFF57]" />
            </div>
          </div>
          <div className="pt-2 border-t border-border flex justify-between items-center">
            <span className="text-[11px] text-muted-foreground">Importance Score</span>
            <span className="font-mono font-bold text-lg" style={{ color: p.color }}>{p.score}</span>
          </div>
        </div>
      ),
    },
    {
      label: "Selection",
      render: p => (
        <div className="flex justify-center">
          <SelectionControl state={selections[p.id] ?? "undecided"} onChange={s => onSelect(p.id, s)} />
        </div>
      ),
    },
  ];

  const cols = players.length;

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
          className="bg-card border border-border rounded-t-2xl sm:rounded-2xl w-full max-w-5xl overflow-hidden flex flex-col"
          style={{ maxHeight: "85vh" }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-border flex-shrink-0">
            <div className="flex items-center gap-2.5">
              <GitCompare size={16} style={{ color: "#AAFF57" }} />
              <h2 className="font-display text-[17px] font-semibold text-foreground">Player Comparison</h2>
              <span className="text-[11px] text-muted-foreground">{players.length} players</span>
              {loading && <Loader2 size={12} className="text-muted-foreground animate-spin" />}
            </div>
            <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors">
              <X size={16} />
            </button>
          </div>

          {/* Scrollable body */}
          <div className="overflow-auto flex-1" style={{ scrollbarWidth: "thin", scrollbarColor: "var(--border) transparent" }}>
            <div className="p-5">
              {/* Player headers */}
              <div className={`grid gap-3 mb-5`} style={{ gridTemplateColumns: `140px repeat(${cols}, 1fr)` }}>
                <div />
                {players.map(p => {
                  const sel = selections[p.id] ?? "undecided";
                  const ringColor = sel === "select" ? "#5FA800" : sel === "exclude" ? "#E5484D" : sel === "reserve" ? "#8A8970" : "transparent";
                  return (
                    <div key={p.id} className="flex flex-col items-center gap-2 p-3 rounded-xl bg-secondary/40 relative">
                      <button onClick={() => onRemove(p.id)}
                        className="absolute top-2 right-2 p-1 rounded hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors">
                        <X size={11} />
                      </button>
                      <div className="w-12 h-12 rounded-full flex items-center justify-center text-[15px] font-bold text-white flex-shrink-0"
                           style={{ background: p.color, border: `2.5px solid ${ringColor}`, boxShadow: sel !== "undecided" ? `0 0 12px ${ringColor}55` : "none" }}>
                        {p.initials}
                      </div>
                      <div className="text-center">
                        <div className="text-[13px] font-semibold text-foreground leading-tight">{p.name}</div>
                        <div className="text-[10px] text-muted-foreground mt-0.5">{p.archetype}</div>
                      </div>
                      <StatusBadge status={p.status} />
                    </div>
                  );
                })}
              </div>

              {/* Stat rows */}
              {statRows.map((row, ri) => (
                <div key={ri} className={`grid gap-3 mb-3`} style={{ gridTemplateColumns: `140px repeat(${cols}, 1fr)` }}>
                  {/* Row label */}
                  <div className="flex items-center">
                    <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-[0.1em]">{row.label}</span>
                  </div>
                  {/* Player cells */}
                  {players.map((p, pi) => (
                    <motion.div key={p.id}
                      initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: ri * 0.04 + pi * 0.03 }}
                      className="p-3 rounded-xl bg-secondary/30 border border-border">
                      {row.render(p)}
                    </motion.div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

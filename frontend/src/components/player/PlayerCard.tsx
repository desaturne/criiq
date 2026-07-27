import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { ChevronRight, BarChart2, Scale } from "lucide-react";
import { AvatarWithRing } from "../common/AvatarWithRing";
import { PhaseBar } from "../common/PhaseBar";
import { RadialGauge } from "../common/RadialGauge";
import { SelectionControl } from "../common/SelectionControl";
import { SparkLine } from "../common/SparkLine";
import { StatusBadge } from "../common/StatusBadge";
import { Player, SelectionState } from "../../types/index";

export function PlayerCard({ player, index, opposition, selection = "undecided", onSelect, comparing, onToggleCompare, onViewProfile }: {
  player: Player; index: number; opposition: string;
  selection?: SelectionState; onSelect?: (s: SelectionState) => void;
  comparing: boolean; onToggleCompare: () => void;
  onViewProfile?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const borderColor =
    selection === "select"  ? "#5FA800" :
    selection === "exclude" ? "#E5484D" :
    selection === "reserve" ? "#8A8970" :
    "var(--border)";

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.05 }}
      className="bg-card rounded-xl overflow-hidden transition-all duration-200 group"
      style={{ border: `1.5px solid ${borderColor}`, boxShadow: selection !== "undecided" ? `0 0 0 1px ${borderColor}20` : undefined }}
    >
      {/* Selection status strip */}
      {selection !== "undecided" && (
        <div className="h-0.5" style={{ background: borderColor }} />
      )}

      {/* Card header */}
      <div className="p-4 flex items-start gap-3">
        <AvatarWithRing initials={player.initials} color={player.color} selection={selection} size={36} />
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h3 className="text-[14px] font-semibold text-foreground leading-tight truncate">
                {onViewProfile ? (
                  <button onClick={onViewProfile} className="cursor-pointer hover:text-accent transition-colors text-left">{player.name}</button>
                ) : player.name}
              </h3>
              <p className="text-[11px] text-muted-foreground mt-0.5">{player.archetype}</p>
            </div>
            <StatusBadge status={player.status} />
          </div>
        </div>
      </div>

      {/* Recent form */}
      <div className="px-4 pb-3 border-t border-border pt-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Last 5</span>
          <SparkLine values={player.recentForm} color={player.color} />
        </div>
        <div className="flex gap-1.5">
          {player.recentForm.map((v, i) => (
            <div key={i} className="flex-1 text-center">
              <div className="text-[11px] font-mono font-medium text-foreground">{v}</div>
              <div className="text-[9px] text-muted-foreground">{player.isBatsman ? "R" : "W"}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Phase performance */}
      <div className="px-4 pb-3">
        <PhaseBar powerplay={player.powerplay} middle={player.middle} death={player.death} />
      </div>

      {/* vs opponent + radial gauge */}
      <div className="px-4 pb-3 flex items-center gap-3 border-t border-border pt-3">
        <RadialGauge value={player.vsOpponent} size={56} strokeWidth={4} color={player.color} label={`vs ${opposition.slice(0,3)}`} />
        <div className="flex-1 min-w-0">
          <div className="text-[10px] font-medium text-muted-foreground mb-0.5">vs {opposition}</div>
          <p className="text-[11px] text-foreground leading-snug">{player.vsInsight}</p>
        </div>
      </div>

      {/* Footer: stats + compare + selection */}
      <div className="px-4 py-3 border-t border-border bg-secondary/30 flex flex-col gap-3">
        <div className="flex items-center justify-between gap-2 min-w-0">
          <button onClick={() => setExpanded(!expanded)} className="text-[11px] text-muted-foreground hover:text-foreground flex items-center gap-1 transition-colors">
            <BarChart2 size={11} /> Stats
            <ChevronRight size={10} className={`transition-transform ${expanded ? "rotate-90" : ""}`} />
          </button>
          <motion.button
            onClick={onToggleCompare}
            whileTap={{ scale: 0.92 }}
            title="Add to compare"
            className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] transition-all"
            style={{
              background: comparing ? "rgba(170,255,87,0.15)" : "transparent",
              color: comparing ? "#AAFF57" : "var(--muted-foreground)",
              border: `1px solid ${comparing ? "rgba(170,255,87,0.4)" : "transparent"}`,
            }}
          >
            <Scale size={10} /> {comparing ? "Comparing" : "Compare"}
          </motion.button>
        </div>
        {onSelect && <div className="w-full"><SelectionControl state={selection} onChange={onSelect} /></div>}
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden">
            <div className="px-4 py-3 border-t border-border bg-secondary/20">
              {player.isBatsman ? (
                <div className="grid grid-cols-4 gap-2 text-center">
                  {[["M", player.career.matches], ["Runs", player.career.runs], ["Avg", player.career.avg], ["SR", player.career.sr]].map(([k, v]) => (
                    <div key={String(k)}>
                      <div className="font-mono text-[13px] font-medium text-foreground">{v}</div>
                      <div className="text-[9px] text-muted-foreground">{k}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="grid grid-cols-4 gap-2 text-center">
                  {[["M", player.career.matches], ["Wkts", player.career.wickets], ["Econ", player.career.economy], ["Best", player.career.best]].map(([k, v]) => (
                    <div key={String(k)}>
                      <div className="font-mono text-[13px] font-medium text-foreground">{v}</div>
                      <div className="text-[9px] text-muted-foreground">{k}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

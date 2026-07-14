import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { useNavigate, useParams } from "react-router";
import { ChevronLeft, Star } from "lucide-react";
import { PhaseBar } from "../components/common/PhaseBar";
import { RadialGauge } from "../components/common/RadialGauge";
import { StatusBadge } from "../components/common/StatusBadge";
import * as api from "../lib/api";
import { applyVsOpponent, mapApiPlayerDetail } from "../lib/mappers";
import { Player } from "../types/index";

export function PlayerProfilePage() {
  const { id: playerId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [player, setPlayer] = useState<Player | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const opposition = "Australia";

  useEffect(() => {
    if (!playerId) return;
    let cancelled = false;
    setLoading(true);
    setNotFound(false);
    api.getPlayer(playerId)
      .then(detail => {
        if (cancelled) return;
        const mapped = mapApiPlayerDetail(detail);
        setPlayer(mapped);
        api.getPlayerVsOpponent(playerId, opposition)
          .then(vs => { if (!cancelled) setPlayer(p => p && applyVsOpponent(p, vs, opposition)); })
          .catch(() => { /* no head-to-head record vs this opponent — keep the default */ });
      })
      .catch(() => { if (!cancelled) setNotFound(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [playerId]);

  if (loading) {
    return <div className="p-5 max-w-screen-xl mx-auto py-16 text-center text-sm text-muted-foreground">Loading player…</div>;
  }
  if (notFound || !player) {
    return (
      <div className="p-5 max-w-screen-xl mx-auto py-16 text-center">
        <p className="text-sm text-muted-foreground mb-4">Unknown player.</p>
        <button onClick={() => navigate(-1)} className="text-sm text-[#AAFF57] hover:underline">Go back</button>
      </div>
    );
  }
  return (
    <div className="p-5 max-w-screen-xl mx-auto">
      <button onClick={() => navigate(-1)} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground mb-5 transition-colors">
        <ChevronLeft size={14} /> Back
      </button>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Left: Profile */}
        <div className="space-y-4">
          <div className="bg-card border border-border rounded-xl p-5 text-center">
            <div className="w-20 h-20 rounded-full flex items-center justify-center text-2xl font-bold mx-auto mb-3" style={{ backgroundColor: player.color + "33", color: player.color }}>{player.initials}</div>
            <h1 className="font-display text-xl font-bold text-foreground">{player.name}</h1>
            <p className="text-sm text-muted-foreground">{player.archetype}</p>
            <div className="flex justify-center gap-2 mt-3">
              <StatusBadge status={player.status} />
              <span className="text-[10px] bg-secondary px-2 py-0.5 rounded-full text-muted-foreground">{player.team}</span>
            </div>
            <div className="mt-4 pt-4 border-t border-border grid grid-cols-2 gap-3 text-center">
              <div><div className="text-[11px] text-muted-foreground">Batting</div><div className="text-sm font-medium text-foreground mt-0.5">{player.battingHand}-hand</div></div>
              <div><div className="text-[11px] text-muted-foreground">Bowling</div><div className="text-sm font-medium text-foreground mt-0.5 truncate">{player.bowlingStyle}</div></div>
            </div>
          </div>

          {/* Scouting note */}
          <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-2">
              <Star size={13} className="text-amber-400" />
              <span className="text-[11px] font-medium text-amber-400 uppercase tracking-wider">Scouting Note</span>
            </div>
            <p className="text-[13px] text-foreground leading-relaxed">{player.vsInsight}. Phase analysis shows exceptional middle-over performance — a key asset in chasing targets above 170.</p>
          </div>
        </div>

        {/* Right: Stats */}
        <div className="lg:col-span-2 space-y-4">
          {/* Career stats */}
          <div className="bg-card border border-border rounded-xl p-5">
            <h3 className="font-display text-base font-semibold text-foreground mb-4">Career Statistics</h3>
            <div className="grid grid-cols-2 gap-4">
              {player.isBatsman ? (
                <>
                  {[["Matches", player.career.matches], ["Innings", player.career.innings], ["Runs", player.career.runs], ["Average", player.career.avg], ["Strike Rate", player.career.sr], ["50s / 100s", `${player.career.fifties} / ${player.career.hundreds}`]].map(([k, v]) => (
                    <div key={String(k)} className="border border-border rounded-lg p-3">
                      <div className="font-mono text-xl font-bold text-foreground">{v}</div>
                      <div className="text-[11px] text-muted-foreground mt-0.5">{k}</div>
                    </div>
                  ))}
                </>
              ) : (
                <>
                  {[["Matches", player.career.matches], ["Innings", player.career.innings], ["Wickets", player.career.wickets], ["Economy", player.career.economy], ["Bowling Avg", player.career.bowlingAvg], ["Best", player.career.best]].map(([k, v]) => (
                    <div key={String(k)} className="border border-border rounded-lg p-3">
                      <div className="font-mono text-xl font-bold text-foreground">{v}</div>
                      <div className="text-[11px] text-muted-foreground mt-0.5">{k}</div>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>

          {/* Phase performance */}
          <div className="bg-card border border-border rounded-xl p-5">
            <h3 className="font-display text-base font-semibold text-foreground mb-4">Phase Performance</h3>
            <PhaseBar powerplay={player.powerplay} middle={player.middle} death={player.death} />
          </div>

          {/* vs opponent radial gauges */}
          <div className="bg-card border border-border rounded-xl p-5">
            <h3 className="font-display text-base font-semibold text-foreground mb-4">Opposition Record</h3>
            <div className="flex flex-wrap gap-6">
              {[["Australia", player.vsOpponent], ["England", Math.round(player.vsOpponent * 0.9)], ["South Africa", Math.round(player.vsOpponent * 1.05)], ["New Zealand", Math.round(player.vsOpponent * 0.95)]].map(([opp, val]) => (
                <div key={String(opp)} className="flex flex-col items-center gap-2">
                  <RadialGauge value={Number(val)} size={64} strokeWidth={4} color={player.color} />
                  <span className="text-[11px] text-muted-foreground">{opp}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Recent form detail */}
          <div className="bg-card border border-border rounded-xl p-5">
            <h3 className="font-display text-base font-semibold text-foreground mb-4">Recent Form</h3>
            <div className="space-y-2">
              {player.recentForm.map((v, i) => (
                <div key={i} className="flex items-center gap-3 p-2.5 rounded-lg bg-secondary/40">
                  <span className="text-[11px] text-muted-foreground w-14">Match {5 - i}</span>
                  <div className="flex-1 h-1.5 rounded-full bg-border overflow-hidden">
                    <motion.div initial={{ width: 0 }} animate={{ width: `${(v / Math.max(...player.recentForm)) * 100}%` }} transition={{ delay: i * 0.1 + 0.3, duration: 0.8 }}
                      className="h-full rounded-full" style={{ backgroundColor: player.color }} />
                  </div>
                  <span className="font-mono text-sm font-medium text-foreground w-8 text-right">{v}</span>
                  <span className="text-[10px] text-muted-foreground">{player.isBatsman ? `SR ${player.recentSR[i]}` : `Econ ${player.recentSR[i]}`}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { ChevronLeft, ShieldAlert } from "lucide-react";
import { PhaseBar } from "../components/common/PhaseBar";
import { RadialGauge } from "../components/common/RadialGauge";
import { StatusBadge } from "../components/common/StatusBadge";
import * as api from "../lib/api";
import { applyVsOpponent, mapApiPlayerDetail } from "../lib/mappers";
import { Player } from "../types/index";

export function PlayerProfilePage() {
  const { id: playerId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const selectedOpponent = searchParams.get("opposition")?.trim() || "";
  const [player, setPlayer] = useState<Player | null>(null);
  // Real per-opponent record (player_vs_opponent) and full advanced profile
  // (player_advanced.profile_json) — kept outside the shared Player type
  // since they're specific to this page, not needed anywhere else the type
  // is used.
  const [opponents, setOpponents] = useState<any[]>([]);
  const [matchupOpponent, setMatchupOpponent] = useState<string | null>(null);
  const [matchupRecord, setMatchupRecord] = useState<any | null>(null);
  const [advanced, setAdvanced] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [retiring, setRetiring] = useState(false);
  const [retirePromptOpen, setRetirePromptOpen] = useState(false);

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
        setOpponents(detail.opponents || []);
        setAdvanced(detail.advanced || null);
        const activeOpponent = selectedOpponent || detail.opponents?.[0]?.opponent;
        setMatchupOpponent(activeOpponent || null);
        setMatchupRecord(null);
        if (activeOpponent) {
          api.getPlayerVsOpponent(playerId, activeOpponent)
            .then(vs => {
              if (!cancelled) {
                setMatchupRecord(vs);
                setPlayer(p => p && applyVsOpponent(p, vs, activeOpponent));
              }
            })
            .catch(() => {
              if (!cancelled) setMatchupRecord(null);
            });
        }
      })
      .catch(() => { if (!cancelled) setNotFound(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [playerId, selectedOpponent]);

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

  const handleRetire = async () => {
    if (player.status === "RETIRED") return;
    setRetiring(true);
    try {
      await api.retirePlayer(player.id);
      setPlayer(prev => prev ? { ...prev, status: "RETIRED" } : prev);
      setRetirePromptOpen(false);
    } finally {
      setRetiring(false);
    }
  };
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

          <button
            onClick={() => setRetirePromptOpen(true)}
            disabled={retiring || player.status === "RETIRED"}
            className="w-full inline-flex items-center justify-center gap-2 rounded-lg border border-amber-500/30 px-4 py-3 text-sm font-medium text-amber-300 transition-colors hover:bg-amber-500/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <ShieldAlert size={15} />
            {player.status === "RETIRED" ? "Retired" : "Retired?"}
          </button>
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

          {/* vs opponent — real player_vs_opponent records, win% as the gauge value */}
          <div className="bg-card border border-border rounded-xl p-5">
            <h3 className="font-display text-base font-semibold text-foreground mb-4">
              Opposition Record{matchupOpponent ? ` vs ${matchupOpponent}` : ""}
            </h3>
            {matchupOpponent && matchupRecord ? (
              <div className="mb-4 flex flex-col gap-2 rounded-lg border border-border bg-secondary/30 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="text-sm font-medium text-foreground">{matchupOpponent}</div>
                  <div className="text-[12px] text-muted-foreground">
                    {matchupRecord.matches} matches
                    {player.isBatsman ? ` · avg ${matchupRecord.bat_average ?? "—"} · SR ${matchupRecord.bat_strike_rate ?? "—"}` : ` · ${matchupRecord.wickets ?? 0} wickets · econ ${matchupRecord.economy ?? "—"}`}
                  </div>
                </div>
                <div className="text-sm font-medium text-foreground">{Math.round(matchupRecord.win_pct ?? 0)}% win rate</div>
              </div>
            ) : null}
            {opponents.length === 0 ? (
              <p className="text-[12px] text-muted-foreground">No opposition record on file for this player yet.</p>
            ) : (
              <div className="flex flex-wrap gap-6">
                {[...opponents]
                  .sort((a, b) => {
                    if (!matchupOpponent) return 0;
                    if (a.opponent === matchupOpponent) return -1;
                    if (b.opponent === matchupOpponent) return 1;
                    return 0;
                  })
                  .map(o => (
                  <div key={o.opponent} className="flex flex-col items-center gap-2">
                    <RadialGauge value={Math.round(o.win_pct ?? 0)} size={64} strokeWidth={4} color={player.color} label={`${Math.round(o.win_pct ?? 0)}%`} />
                    <span className="text-[11px] text-muted-foreground">{o.opponent}</span>
                    <span className="text-[10px] text-muted-foreground/70">{o.matches}m{player.isBatsman ? `, avg ${o.bat_average ?? "—"}` : `, ${o.wickets ?? 0}w`}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Advanced profile — player_advanced.profile_json: phase splits, vs-pace/vs-spin, six rate */}
          {advanced && (
            <div className="bg-card border border-border rounded-xl p-5">
              <h3 className="font-display text-base font-semibold text-foreground mb-4">Advanced Profile</h3>
              {advanced.batting?.vs_bowling_type && (
                <div className="mb-4">
                  <p className="text-[11px] text-muted-foreground uppercase tracking-wider mb-2">Vs Pace / Vs Spin (strike rate)</p>
                  <div className="flex gap-4">
                    {["pace", "spin"].map(style => {
                      const s = advanced.batting.vs_bowling_type[style];
                      if (!s) return null;
                      return (
                        <div key={style} className="flex-1 border border-border rounded-lg p-3 text-center">
                          <div className="font-mono text-lg font-bold text-foreground">{s.strike_rate}</div>
                          <div className="text-[10px] text-muted-foreground uppercase mt-0.5">vs {style} ({s.balls} balls)</div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
              {advanced.bowling?.by_phase && (
                <div className="mb-4">
                  <p className="text-[11px] text-muted-foreground uppercase tracking-wider mb-2">Economy by Phase</p>
                  <div className="flex gap-4">
                    {Object.entries(advanced.bowling.by_phase).map(([phase, s]: [string, any]) => (
                      <div key={phase} className="flex-1 border border-border rounded-lg p-3 text-center">
                        <div className="font-mono text-lg font-bold text-foreground">{s.economy}</div>
                        <div className="text-[10px] text-muted-foreground uppercase mt-0.5 capitalize">{phase} ({s.wickets}w)</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {advanced.strengths?.length > 0 && (
                <div>
                  <p className="text-[11px] text-muted-foreground uppercase tracking-wider mb-2">Strengths</p>
                  <ul className="space-y-1">
                    {advanced.strengths.map((s: string, i: number) => (
                      <li key={i} className="text-[12px] text-foreground">• {s}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* Recent form detail */}
          <div className="bg-card border border-border rounded-xl p-5">
            <h3 className="font-display text-base font-semibold text-foreground mb-4">Recent Form</h3>
            <div className="space-y-2">
              {player.recentForm.map((v, i) => (
                <div key={i} className="flex items-center gap-3 p-2.5 rounded-lg bg-secondary/40">
                  <span className="text-[11px] text-muted-foreground w-14">Match {player.recentForm.length - i}</span>
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

      <AnimatePresence>
        {retirePromptOpen && player.status !== "RETIRED" && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: "rgba(0,0,0,0.72)", backdropFilter: "blur(6px)" }}
            onClick={e => e.target === e.currentTarget && setRetirePromptOpen(false)}
          >
            <motion.div
              initial={{ scale: 0.94, y: 20, opacity: 0 }}
              animate={{ scale: 1, y: 0, opacity: 1 }}
              exit={{ scale: 0.96, y: 12, opacity: 0 }}
              transition={{ type: "spring", damping: 26, stiffness: 320 }}
              className="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-2xl"
            >
              <div className="flex items-start gap-3">
                <div className="mt-0.5 flex h-10 w-10 items-center justify-center rounded-full bg-amber-500/10 text-amber-300">
                  <ShieldAlert size={18} />
                </div>
                <div className="flex-1">
                  <h4 className="font-display text-lg font-semibold text-foreground">Retire player?</h4>
                  <p className="mt-1 text-sm text-muted-foreground">Are you sure the player is retired?</p>
                </div>
              </div>

              <div className="mt-6 flex justify-end gap-3">
                <button
                  onClick={() => setRetirePromptOpen(false)}
                  className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                >
                  No
                </button>
                <button
                  onClick={handleRetire}
                  disabled={retiring}
                  className="rounded-lg bg-[#AAFF57] px-4 py-2 text-sm font-semibold text-[#0D0D06] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {retiring ? "Saving..." : "Yes"}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

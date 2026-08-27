import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { useNavigate } from "react-router";
import { Users, Calendar, Zap, TrendingUp, TrendingDown, AlertTriangle, Shield, BarChart2, Database } from "lucide-react";
import { AnimatedStat } from "../components/common/AnimatedStat";
import { useApp } from "../context/AppContext";
import * as api from "../lib/api";

export function DashboardOverviewPage() {
  const { selections } = useApp();
  const navigate = useNavigate();
  const setPage = (p: string) => navigate("/" + p);

  const [totalPlayers, setTotalPlayers] = useState(0);
  const [winProb, setWinProb] = useState(50);
  const [formAlerts, setFormAlerts] = useState<{ player: string; msg: string; type: string }[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.dashboardSummary(),
      api.listPlayers({ limit: 1 }),
      api.dashboardAlerts(),
    ]).then(([summary, playerRes, alerts]) => {
      if (cancelled) return;
      setWinProb(Math.round((summary.win_probability?.win_probability_batting ?? 0.5) * 100));
      setTotalPlayers(playerRes.total);
      // Real, rule-based alerts (backend/matches.py's dashboard_alerts): last
      // 3 innings all 50+ (positive) or all <=10 (warning), computed from
      // each ACTIVE player's real recent-innings history -- not fabricated.
      setFormAlerts(alerts.map((a: any) => ({ player: a.player, msg: a.message, type: a.type })));
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const selectedCount = Object.values(selections).filter(s => s === "select").length;
  const reserveCount  = Object.values(selections).filter(s => s === "reserve").length;

  const alertColor = (t: string) =>
    t === "positive" ? "#AAFF57" : t === "warning" ? "#F59E0B" : "#FF5C5C";
  const alertIcon  = (t: string) =>
    t === "positive" ? <TrendingUp size={11} /> : t === "warning" ? <AlertTriangle size={11} /> : <TrendingDown size={11} />;

  if (loading) {
    return <div className="p-5 max-w-screen-xl mx-auto py-16 text-center text-sm text-muted-foreground">Loading dashboard…</div>;
  }

  return (
    <div className="p-5 max-w-screen-xl mx-auto space-y-5 pb-10">

      {/* ── Page header ── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-display text-3xl font-bold text-foreground tracking-tight">Match Command Center</h1>
          <p className="text-sm text-muted-foreground mt-1">India National Squad · Season 2025</p>
        </div>
        <span className="text-[12px] text-muted-foreground hidden sm:block">
          {new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}
        </span>
      </div>

      {/* ── 4 Stat Tiles ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-card border border-border rounded-2xl p-5" title="Every player CRIIQ has real data for, across all nations and both genders.">
          <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.12em] mb-3">Squad</div>
          <div className="font-mono text-4xl font-bold text-foreground tabular-nums leading-none">
            <AnimatedStat value={totalPlayers} />
          </div>
          <div className="text-[11px] text-muted-foreground mt-2">Players registered</div>
        </div>
        <div className="bg-card rounded-2xl p-5 transition-all duration-300"
             style={{ border: `1.5px solid ${selectedCount > 0 ? "#AAFF57" : "var(--border)"}` }}
             title="Players you've marked 'Select' for the next fixture, on the Squads page's Build XI tab.">
          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] mb-3" style={{ color: "#AAFF57" }}>XI Selected</div>
          <div className="font-mono text-4xl font-bold tabular-nums leading-none" style={{ color: "#AAFF57" }}>
            {selectedCount}<span className="text-2xl text-muted-foreground">/11</span>
          </div>
          <div className="mt-3 h-1 rounded-full bg-border overflow-hidden">
            <motion.div animate={{ width: `${(selectedCount / 11) * 100}%` }} transition={{ duration: 0.5 }}
              className="h-full rounded-full bg-[#AAFF57]" />
          </div>
        </div>
        <div className="bg-card border border-border rounded-2xl p-5" title="Players marked 'Reserve' — not in the XI, but available to step in.">
          <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.12em] mb-3">Reserves</div>
          <div className="font-mono text-4xl font-bold text-foreground tabular-nums leading-none">{reserveCount}</div>
          <div className="text-[11px] text-muted-foreground mt-2">Ready to step in</div>
        </div>
        {/* Win probability — a generic pre-XI baseline, not a real per-match
            prediction: the model only reads game state, never team identity,
            so it can't reflect who's actually playing before an XI exists. */}
        <div className="bg-card border border-border rounded-2xl p-5" title="Generic baseline from match-state only, not team-specific. Pick both XIs on the Simulator page for a real win probability.">
          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] mb-3" style={{ color: "#3ADCFF" }}>Win Probability (baseline)</div>
          <div className="font-mono text-4xl font-bold tabular-nums leading-none" style={{ color: "#3ADCFF" }}>
            <AnimatedStat value={winProb} suffix="%" />
          </div>
          <button onClick={() => navigate("/simulator")} className="text-[11px] text-[#3ADCFF] hover:underline mt-2">
            Get a real number on the Simulator →
          </button>
        </div>
      </div>

      {/* ── Main content (left) + Form Alerts (right) ── */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-4 items-start">
        <div className="space-y-4">
          {/* How AI scoring works — real components from criiq_models'
              RecommendationScorer (recommend/score.py), not a simplified guess. */}
          <div className="bg-card border border-border rounded-2xl p-5">
            <h3 className="font-display text-[15px] font-semibold text-foreground mb-1">How AI Scoring Works</h3>
            <p className="text-[12px] text-muted-foreground mb-4">
              Every player score on Recommendations is a transparent sum of six real, computed parts — never a black box.
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {[
                { label: "Model Impact", range: "0–45", color: "#AAFF57", desc: "A trained model's prediction of win-probability-added, from recent form." },
                { label: "Matchup", range: "±21", color: "#60A5FA", desc: "Real history vs this specific opponent's bowlers/batters, plus style fit." },
                { label: "Phase Fit", range: "0–8", color: "#A78BFA", desc: "How strong this player is in the powerplay, middle, or death overs." },
                { label: "Team Need", range: "0–5", color: "#FB923C", desc: "Bonus for covering this specific squad's weakest phase." },
                { label: "Track Record", range: "0–20", color: "#3ADCFF", desc: "Career importance score and current ICC ranking." },
                { label: "Risk", range: "≤0", color: "#F87171", desc: "Deductions for age advisory, inconsistent selection, or recalls." },
              ].map(c => (
                <div key={c.label} className="p-3 rounded-xl bg-secondary/40 border border-border">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[12px] font-semibold text-foreground">{c.label}</span>
                    <span className="text-[10px] font-mono" style={{ color: c.color }}>{c.range}</span>
                  </div>
                  <p className="text-[11px] text-muted-foreground leading-snug">{c.desc}</p>
                </div>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground mt-4">
              The full reasoning behind any player's score is shown on the <button onClick={() => navigate("/recommendations")} className="text-[#AAFF57] hover:underline">Recommendations</button> page.
            </p>
          </div>

          {/* Feature overview */}
          <div className="bg-card border border-border rounded-2xl p-5">
            <h3 className="font-display text-[15px] font-semibold text-foreground mb-4">What You Can Do Here</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {[
                { label: "Player Form", page: "players", color: "#60A5FA", icon: BarChart2, desc: "Browse real career stats, form, and role for any team/gender." },
                { label: "Squads", page: "squads", color: "#AAFF57", icon: Users, desc: "Manage the roster and build a Playing XI, with the AI's own pick pre-filled." },
                { label: "Matches", page: "matches", color: "#3ADCFF", icon: Calendar, desc: "Upcoming fixtures and opposition form." },
                { label: "Recommendations", page: "recommendations", color: "#A78BFA", icon: Zap, desc: "The AI's full ranked XI for a specific opponent/venue, with reasoning." },
                { label: "Simulator", page: "simulator", color: "#FB923C", icon: Shield, desc: "Ball-by-ball Monte Carlo match simulation, plus order optimizers." },
              ].map(f => (
                <button key={f.label} onClick={() => setPage(f.page)}
                  className="flex items-start gap-3 p-3 rounded-xl border border-border hover:border-border/60 transition-all text-left"
                  onMouseEnter={e => (e.currentTarget.style.background = f.color + "0D")}
                  onMouseLeave={e => (e.currentTarget.style.background = "")}
                >
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: f.color + "1A" }}>
                    <f.icon size={14} style={{ color: f.color }} />
                  </div>
                  <div className="min-w-0">
                    <div className="text-[13px] font-medium text-foreground">{f.label}</div>
                    <div className="text-[11px] text-muted-foreground leading-snug">{f.desc}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Data source */}
          <div className="bg-card border border-border rounded-2xl p-5 flex items-start gap-3">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: "#60A5FA1A" }}>
              <Database size={14} style={{ color: "#60A5FA" }} />
            </div>
            <div>
              <div className="text-[13px] font-medium text-foreground">Data source</div>
              <p className="text-[11px] text-muted-foreground leading-snug mt-0.5">
                Player and match data is built from <a href="https://cricsheet.org" target="_blank" rel="noreferrer" className="text-[#60A5FA] hover:underline">Cricsheet</a>'s
                free, public ball-by-ball dataset — women's and men's T20I plus major domestic T20 leagues (WBBL, WPL, The Hundred, and others).
                Everything you see (career stats, form, phase splits, recommendations) is computed from those real match records, not sample or placeholder data.
              </p>
            </div>
          </div>
        </div>

        {/* Form Alerts — real, rule-based (see effect above) */}
        <div className="bg-card border border-border rounded-2xl p-5">
          <h3 className="font-display text-[15px] font-semibold text-foreground mb-1">Form Alerts</h3>
          <p className="text-[11px] text-muted-foreground mb-4">Real rule: last 3 innings all 50+ or all ≤10, for ACTIVE players.</p>
          <div className="space-y-2.5">
            {formAlerts.length === 0 && <p className="text-[12px] text-muted-foreground">No form alerts right now.</p>}
            {formAlerts.map((alert, i) => {
              const c = alertColor(alert.type);
              return (
                <motion.div key={i}
                  initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.1 + i * 0.08 }}
                  className="flex items-start gap-2.5 p-3 rounded-xl"
                  style={{ background: c + "0A", border: `1px solid ${c}1A` }}
                >
                  <div className="w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5"
                       style={{ background: c + "20", color: c }}>
                    {alertIcon(alert.type)}
                  </div>
                  <div className="min-w-0">
                    <div className="text-[12px] font-semibold text-foreground truncate">{alert.player}</div>
                    <div className="text-[11px] text-muted-foreground leading-snug mt-0.5">{alert.msg}</div>
                  </div>
                </motion.div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

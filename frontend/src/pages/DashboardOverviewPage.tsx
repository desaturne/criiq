import { motion } from "motion/react";
import { useNavigate } from "react-router";
import { Users, Calendar, FileText, MapPin, TrendingUp, TrendingDown, AlertTriangle, ArrowRight, Shield, BarChart2 } from "lucide-react";
import { AnimatedStat } from "../components/common/AnimatedStat";
import { CountdownTimer } from "../components/common/CountdownTimer";
import { CricketBall } from "../components/common/CricketBall";
import { RadialGauge } from "../components/common/RadialGauge";
import { useApp } from "../context/AppContext";
import { MATCHES } from "../data/matches";
import { PLAYERS } from "../data/players";

export function DashboardOverviewPage() {
  const { selections } = useApp();
  const navigate = useNavigate();
  const setPage = (p: string) => {
    const map: Record<string, string> = { playerform: "players", match: "matches/m1" };
    navigate("/" + (map[p] ?? p));
  };
  const nextMatch = MATCHES[0];
  const selectedCount  = Object.values(selections).filter(s => s === "select").length;
  const reserveCount   = Object.values(selections).filter(s => s === "reserve").length;
  const batters        = PLAYERS.filter(p => selections[p.id] === "select" && p.isBatsman).length;
  const bowlers        = PLAYERS.filter(p => selections[p.id] === "select" && !p.isBatsman && p.role === "Bowler").length;
  const allRounders    = PLAYERS.filter(p => selections[p.id] === "select" && p.role === "All-rounder").length;
  const winProb        = Math.round(45 + selectedCount * 3.2);

  // Target date ~3 days from "now" (mock)
  const target = new Date("2025-01-15T14:00:00+11:00");

  const formAlerts = [
    { player: "Jasprit Bumrah",   msg: "Career-best form — 3-2-4 wkts in last 3. Lock in.", type: "positive" },
    { player: "Shubman Gill",     msg: "3 consecutive 50+ scores. Confidence at a peak.",   type: "positive" },
    { player: "Hardik Pandya",    msg: "Economy 8.14 last 3 games. Consider alternatives.", type: "warning"  },
    { player: "Yuzvendra Chahal", msg: "Full-toss count elevated. Form dip this month.",    type: "negative" },
  ];

  const alertColor = (t: string) =>
    t === "positive" ? "#5FA800" : t === "warning" ? "#9A6B11" : "#B4534A";
  const alertIcon  = (t: string) =>
    t === "positive" ? <TrendingUp size={11} /> : t === "warning" ? <AlertTriangle size={11} /> : <TrendingDown size={11} />;

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
        {/* Squad size */}
        <div className="bg-card border border-border rounded-2xl p-5">
          <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.12em] mb-3">Squad</div>
          <div className="font-mono text-4xl font-bold text-foreground tabular-nums leading-none">
            <AnimatedStat value={15} />
          </div>
          <div className="text-[11px] text-muted-foreground mt-2">Players registered</div>
        </div>
        {/* XI Selected — live */}
        <div className="bg-card rounded-2xl p-5 transition-all duration-300"
             style={{ border: `1.5px solid ${selectedCount > 0 ? "#5FA800" : "var(--border)"}` }}>
          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] mb-3" style={{ color: "#5F7F24" }}>XI Selected</div>
          <div className="font-mono text-4xl font-bold tabular-nums leading-none" style={{ color: "#5F7F24" }}>
            {selectedCount}<span className="text-2xl text-muted-foreground">/11</span>
          </div>
          <div className="mt-3 h-1 rounded-full bg-border overflow-hidden">
            <motion.div animate={{ width: `${(selectedCount / 11) * 100}%` }} transition={{ duration: 0.5 }}
              className="h-full rounded-full bg-[#5FA800]" />
          </div>
        </div>
        {/* Reserves */}
        <div className="bg-card border border-border rounded-2xl p-5">
          <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.12em] mb-3">Reserves</div>
          <div className="font-mono text-4xl font-bold text-foreground tabular-nums leading-none">{reserveCount}</div>
          <div className="text-[11px] text-muted-foreground mt-2">Ready to step in</div>
        </div>
        {/* Win probability */}
        <div className="bg-card border border-border rounded-2xl p-5">
          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] mb-3" style={{ color: "#5B6B7A" }}>Win Probability</div>
          <div className="font-mono text-4xl font-bold tabular-nums leading-none" style={{ color: "#5B6B7A" }}>
            <AnimatedStat value={winProb} suffix="%" />
          </div>
          <div className="text-[11px] text-muted-foreground mt-2">vs {nextMatch.team2}</div>
        </div>
      </div>

      {/* ── Upcoming Match Hero Card ── */}
      <div className="relative rounded-2xl overflow-hidden"
         style={{ background: "linear-gradient(135deg, #FBFBF8 0%, #F2F4F0 58%, #EEF2EE 100%)", border: "1px solid rgba(22,21,14,0.08)" }}>
            {/* Grid texture */}
            <div className="absolute inset-0 pointer-events-none"
            style={{ backgroundImage: "linear-gradient(rgba(22,21,14,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(22,21,14,0.03) 1px, transparent 1px)", backgroundSize: "48px 48px" }} />
          <div className="absolute -top-24 -left-24 w-72 h-72 rounded-full pointer-events-none"
            style={{ background: "radial-gradient(circle, rgba(95,168,0,0.08) 0%, transparent 70%)" }} />

            <div className="relative z-10 p-7 lg:p-10">
              <div className="flex flex-col xl:flex-row xl:items-center gap-8 xl:gap-12">

                {/* Left: match details */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-5">
                    <span className="text-[10px] font-semibold px-2.5 py-1 rounded-full border"
                      style={{ background: "rgba(95,168,0,0.10)", color: "#5A7E1D", borderColor: "rgba(95,168,0,0.18)" }}>Upcoming</span>
                    <span className="text-[10px] font-semibold px-2.5 py-1 rounded-full border"
                      style={{ borderColor: "rgba(22,21,14,0.10)", color: "rgba(22,21,14,0.60)" }}>T20I</span>
                  </div>

                  {/* Teams */}
                  <div className="flex items-center gap-5 mb-5">
                    <div>
                      <div className="font-display font-bold tracking-tight" style={{ fontSize: "clamp(2rem, 5vw, 3.5rem)", lineHeight: 1, color: "#16150E" }}>INDIA</div>
                      <div className="text-[11px] mt-1.5" style={{ color: "rgba(22,21,14,0.55)" }}>Home</div>
                    </div>
                    <div className="flex flex-col items-center gap-1.5 flex-shrink-0">
                      <CricketBall size={26} className="text-[#5FA800]" />
                      <span className="text-xs font-bold" style={{ color: "rgba(22,21,14,0.55)" }}>VS</span>
                    </div>
                    <div>
                      <div className="font-display font-bold tracking-tight" style={{ fontSize: "clamp(2rem, 5vw, 3.5rem)", lineHeight: 1, color: "#16150E" }}>AUSTRALIA</div>
                      <div className="text-[11px] mt-1.5" style={{ color: "rgba(22,21,14,0.55)" }}>Away</div>
                    </div>
                  </div>

                  {/* Venue + date */}
                  <div className="flex items-center flex-wrap gap-x-5 gap-y-1.5 text-[13px] mb-4" style={{ color: "rgba(22,21,14,0.62)" }}>
                    <span className="flex items-center gap-1.5"><MapPin size={13} style={{ color: "#5B6B7A" }} /> MCG, Melbourne</span>
                    <span className="hidden sm:inline opacity-30">·</span>
                    <span>Jan 15, 2025</span>
                    <span className="hidden sm:inline opacity-30">·</span>
                    <span>14:00 AEDT</span>
                  </div>

                  {/* Opposition form */}
                  <div className="flex items-center gap-3">
                    <span className="text-[11px] flex-shrink-0" style={{ color: "rgba(22,21,14,0.60)" }}>AUS last 5:</span>
                    <div className="flex gap-1.5">
                      {nextMatch.opponentForm.map((r, i) => (
                        <motion.div key={i}
                          initial={{ scale: 0, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ delay: 0.5 + i * 0.07 }}
                          className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold"
                          style={{ background: r === "W" ? "rgba(95,168,0,0.12)" : "rgba(185,90,72,0.12)", color: r === "W" ? "#5F7F24" : "#9E5A52", border: `1px solid ${r === "W" ? "rgba(95,168,0,0.22)" : "rgba(185,90,72,0.22)"}` }}>
                          {r}
                        </motion.div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Right: countdown + CTAs */}
                <div className="flex flex-col items-start xl:items-center gap-7 xl:flex-shrink-0">
                  <div>
                    <div className="text-[10px] font-semibold uppercase tracking-[0.15em] mb-4" style={{ color: "rgba(22,21,14,0.55)" }}>Match begins in</div>
                    <CountdownTimer targetDate={target.toISOString()} />
                  </div>
                  <div className="flex flex-col gap-2.5 w-full xl:min-w-[220px]">
                    <button onClick={() => setPage("match")}
                      className="w-full py-2.5 px-6 rounded-xl text-sm font-medium flex items-center justify-center gap-1.5 transition-colors"
                      style={{ border: "1px solid rgba(22,21,14,0.14)", color: "rgba(22,21,14,0.72)" }}
                      onMouseEnter={e => { e.currentTarget.style.color = "#16150E"; e.currentTarget.style.borderColor = "rgba(22,21,14,0.24)"; }}
                      onMouseLeave={e => { e.currentTarget.style.color = "rgba(22,21,14,0.72)"; e.currentTarget.style.borderColor = "rgba(22,21,14,0.14)"; }}
                    >
                      Match Details <ArrowRight size={13} />
                    </button>
                  </div>
                </div>
              </div>
            </div>
      </div>

      {/* ── Secondary 3-column section ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Squad Readiness */}
        <div className="bg-card border border-border rounded-2xl p-5">
          <div className="flex items-center justify-between mb-5">
            <h3 className="font-display text-[15px] font-semibold text-foreground">Squad Readiness</h3>
            <span className="text-[11px] text-muted-foreground">{selectedCount}/11 set</span>
          </div>
          <div className="flex justify-around mb-5">
            {[
              { label: "Batters",   val: batters,    max: 7, color: "#5B6B7A" },
              { label: "Bowlers",   val: bowlers,    max: 4, color: "#5F7F24" },
              { label: "All-round", val: allRounders, max: 2, color: "#7C6C52" },
            ].map(g => (
              <div key={g.label} className="flex flex-col items-center gap-2">
                <RadialGauge value={g.max > 0 ? Math.round((g.val / g.max) * 100) : 0} size={68} strokeWidth={5} color={g.color} />
                <div className="text-center">
                  <div className="text-[13px] font-semibold text-foreground">{g.val}/{g.max}</div>
                  <div className="text-[10px] text-muted-foreground">{g.label}</div>
                </div>
              </div>
            ))}
          </div>
          <button onClick={() => setPage("playerform")}
            className="w-full py-2.5 text-[12px] font-medium text-muted-foreground hover:text-foreground border border-border rounded-xl transition-colors flex items-center justify-center gap-1.5">
            <Users size={12} /> Select Playing XI
          </button>
        </div>

        {/* Form Alerts */}
        <div className="bg-card border border-border rounded-2xl p-5">
          <h3 className="font-display text-[15px] font-semibold text-foreground mb-4">Form Alerts</h3>
          <div className="space-y-2.5">
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

        {/* Quick Actions */}
        <div className="bg-card border border-border rounded-2xl p-5">
          <h3 className="font-display text-[15px] font-semibold text-foreground mb-4">Quick Actions</h3>
          <div className="space-y-2">
            {([
              { label: "Select Playing XI",    sub: "Pick players for vs Australia", page: "players",         color: "#5F7F24", icon: Users         },
              { label: "View Matches",          sub: "Upcoming fixtures & details",   page: "matches",         color: "#5B6B7A", icon: Calendar       },
              { label: "Scouting Reports",      sub: "Pre-match documents",           page: "reports",         color: "#7C6C52", icon: FileText       },
            ] as const).map((action, i) => (
              <motion.button key={action.label}
                initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.1 + i * 0.07 }}
                onClick={() => setPage(action.page)}
                className="w-full flex items-center gap-3 p-3 rounded-xl border border-border hover:border-border/60 transition-all group text-left"
                onMouseEnter={e => (e.currentTarget.style.background = action.color + "0D")}
                onMouseLeave={e => (e.currentTarget.style.background = "")}
              >
                <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: action.color + "1A" }}>
                  <action.icon size={14} style={{ color: action.color }} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] font-medium text-foreground truncate">{action.label}</div>
                  <div className="text-[11px] text-muted-foreground truncate">{action.sub}</div>
                </div>
                <ArrowRight size={13} className="text-muted-foreground group-hover:text-foreground transition-colors flex-shrink-0" />
              </motion.button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

import { useState, useEffect } from "react";
import { motion } from "motion/react";
import { useNavigate, useParams } from "react-router";
import { Zap, ChevronLeft, MapPin, Shield } from "lucide-react";
import { RadialGauge } from "../components/common/RadialGauge";
import { MATCHES } from "../data/matches";

export function MatchDetailPage() {
  const { id: matchId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const match = MATCHES.find(m => m.id === matchId) || MATCHES[0];
  const [animated, setAnimated] = useState(false);
  useEffect(() => { const t = setTimeout(() => setAnimated(true), 400); return () => clearTimeout(t); }, []);
  const condBar = (label: string, val: number, color: string) => (
    <div className="space-y-1.5">
      <div className="flex justify-between text-sm">
        <span className="text-foreground font-medium">{label}</span>
        <span className="font-mono" style={{ color }}>{val}%</span>
      </div>
      <div className="h-2 rounded-full bg-secondary overflow-hidden">
        <motion.div initial={{ width: 0 }} animate={{ width: animated ? `${val}%` : "0%" }} transition={{ duration: 1.2, ease: "easeOut" }}
          className="h-full rounded-full" style={{ backgroundColor: color }} />
      </div>
    </div>
  );
  return (
    <div className="p-5 max-w-screen-xl mx-auto">
      <button onClick={() => navigate("/matches")} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground mb-5 transition-colors">
        <ChevronLeft size={14} /> Back to Matches
      </button>

      {/* Hero */}
      <div className="bg-card border border-border rounded-xl p-6 mb-5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${match.status === "Upcoming" ? "bg-blue-500/15 text-blue-400" : "bg-secondary text-muted-foreground"}`}>{match.status}</span>
              <span className="text-[11px] text-muted-foreground">{match.format}</span>
            </div>
            <h1 className="font-display text-3xl font-bold text-foreground">{match.team1} <span className="text-muted-foreground">vs</span> {match.team2}</h1>
            <div className="flex items-center gap-4 mt-2 text-[13px] text-muted-foreground">
              <span className="flex items-center gap-1"><MapPin size={12} /> {match.venue}</span>
              <span>{match.date} · {match.time}</span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => navigate("/recommendations")} className="flex items-center gap-2 bg-[#AAFF57] text-[#0D0D06] px-4 py-2 rounded-lg text-sm font-semibold hover:opacity-90 transition-opacity">
              <Zap size={14} /> Get AI Selection
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-5">
        {/* Opponent form */}
        <div className="bg-card border border-border rounded-xl p-5">
          <h3 className="font-display text-base font-semibold text-foreground mb-4">Opponent Form</h3>
          <div className="flex items-center gap-3 mb-4">
            <div className="w-12 h-12 rounded-full bg-secondary flex items-center justify-center text-sm font-bold text-foreground">{match.team2.slice(0, 3).toUpperCase()}</div>
            <div>
              <div className="font-semibold text-foreground">{match.team2}</div>
              <div className="text-[11px] text-muted-foreground">Last 5 T20Is</div>
            </div>
            <div className="flex gap-1.5 ml-auto">
              {match.opponentForm.map((r, i) => (
                <span key={i} className={`w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-bold ${r === "W" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"}`}>{r}</span>
              ))}
            </div>
          </div>
          <div className="p-3 bg-amber-500/5 border border-amber-500/20 rounded-lg text-[12px] text-foreground leading-relaxed">
            <span className="text-amber-400 font-medium">Scouting: </span>
            {match.team2 === "Australia" ? "Strong batting top-order. Warner and Head in excellent form. Pace attack with Hazelwood and Cummins are key threats." : "Recent form mixed. Look to target middle-order vulnerabilities in overs 11-15."}
          </div>
        </div>

        {/* Match context */}
        <div className="bg-card border border-border rounded-xl p-5">
          <h3 className="font-display text-base font-semibold text-foreground mb-4">Match Context</h3>
          <div className="flex items-center gap-4 mb-4">
            <RadialGauge value={match.paceSupport} size={64} strokeWidth={4} color="#5B6B7A" label="Pace" />
            <RadialGauge value={match.spinSupport} size={64} strokeWidth={4} color="#7C6C52" label="Spin" />
            <div className="flex-1 text-sm text-muted-foreground leading-relaxed">
              Conditions are summarized through pitch and opponent data only.
            </div>
          </div>
          <div className="text-[13px] text-foreground leading-relaxed">
            <span className="font-medium">Pitch note: </span>
            {match.paceSupport > 70 ? "Pitch heavily favors pace — back 3 seamers and restrict leg-spinners." : match.spinSupport > 70 ? "Spin-friendly surface — prioritize your best leg-spinner and left-arm orthodox pairing." : "Balanced surface suits an attack mix of 3 seamers and 2 spinners."}
          </div>
        </div>
      </div>

      {/* Pitch report */}
      <div className="bg-card border border-border rounded-xl p-5">
        <h3 className="font-display text-base font-semibold text-foreground mb-5">Pitch Report</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
          <div className="space-y-4">
            {condBar("Pace Support", match.paceSupport, "#60A5FA")}
            {condBar("Spin Support", match.spinSupport, "#A78BFA")}
          </div>
          <div className="space-y-4">
            {condBar("Batting Anchors", match.battingAnchors, "#AAFF57")}
            {condBar("Finisher Suitability", match.finishersFit, "#FB923C")}
          </div>
        </div>
        <div className="mt-5 p-4 bg-secondary/40 border border-border rounded-lg">
          <div className="flex items-center gap-2 mb-1">
            <Shield size={13} className="text-[#5F7F24]" />
            <span className="text-[11px] font-semibold text-[#5F7F24] uppercase tracking-wider">Pro Tip</span>
          </div>
          <p className="text-[13px] text-foreground leading-relaxed">
            {match.paceSupport > 70 ? "Pitch heavily favors pace — back 3 seamers and restrict leg-spinners. Consider an extra fast-bowling all-rounder." : match.spinSupport > 70 ? "Spin-friendly surface — prioritize your best leg-spinner and left-arm orthodox pairing." : "Balanced surface suits an attack mix of 3 seamers and 2 spinners."}
          </p>
        </div>
      </div>
    </div>
  );
}

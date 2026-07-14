import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { useNavigate } from "react-router";
import { MapPin, Filter, ArrowRight } from "lucide-react";
import * as api from "../lib/api";
import { mapApiMatch } from "../lib/mappers";
import { Match } from "../types/index";

export function MatchesPage() {
  const navigate = useNavigate();
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const statusColor = { Upcoming: "bg-blue-500/15 text-blue-400", Live: "bg-green-500/15 text-green-400", Completed: "bg-secondary text-muted-foreground" };

  useEffect(() => {
    api.listMatches()
      .then(res => setMatches([...res.upcoming, ...res.completed].map(mapApiMatch)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="p-5 max-w-screen-xl mx-auto py-16 text-center text-sm text-muted-foreground">Loading matches…</div>;
  }
  return (
    <div className="p-5 max-w-screen-xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="font-display text-2xl font-bold text-foreground">Matches</h1>
          <p className="text-sm text-muted-foreground mt-0.5">Upcoming and completed fixtures</p>
        </div>
        <button className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-border rounded-lg text-muted-foreground hover:text-foreground transition-colors">
          <Filter size={12} /> Filter
        </button>
      </div>
      <div className="grid gap-3">
        {matches.map((m, i) => (
          <motion.div key={m.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}
            onClick={() => navigate("/matches/" + m.id)}
            className="bg-card border border-border rounded-xl p-5 hover:border-[#AAFF57]/30 transition-all cursor-pointer group">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${statusColor[m.status]}`}>{m.status}</span>
                  <span className="text-[11px] text-muted-foreground">{m.format}</span>
                </div>
                <h3 className="font-display text-lg font-semibold text-foreground">{m.team1} <span className="text-muted-foreground font-normal text-base">vs</span> {m.team2}</h3>
                {m.result && <p className="text-[12px] text-[#AAFF57] mt-0.5">{m.result}</p>}
                <div className="flex items-center gap-4 mt-2 text-[12px] text-muted-foreground">
                  <span className="flex items-center gap-1"><MapPin size={11} /> {m.venue}</span>
                  <span>{m.date} · {m.time}</span>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <div className="hidden sm:flex gap-1">
                  {m.opponentForm.map((r, idx) => (
                    <span key={idx} className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold ${r === "W" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"}`}>{r}</span>
                  ))}
                </div>
                <ArrowRight size={16} className="text-muted-foreground group-hover:text-[#AAFF57] transition-colors" />
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

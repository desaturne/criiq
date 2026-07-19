import { useState, useEffect } from "react";
import { useNavigate, useParams } from "react-router";
import { Zap, ChevronLeft, MapPin, PlayCircle } from "lucide-react";
import * as api from "../lib/api";
import { mapApiMatch } from "../lib/mappers";
import { Match } from "../types/index";

export function MatchDetailPage() {
  const { id: matchId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [match, setMatch] = useState<Match | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!matchId) return;
    let cancelled = false;
    api.getMatch(matchId)
      .then(m => { if (!cancelled) setMatch(mapApiMatch(m)); })
      .catch(() => { if (!cancelled) setNotFound(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [matchId]);

  if (loading) {
    return <div className="p-5 max-w-screen-xl mx-auto py-16 text-center text-sm text-muted-foreground">Loading match…</div>;
  }
  if (notFound || !match) {
    return (
      <div className="p-5 max-w-screen-xl mx-auto py-16 text-center">
        <p className="text-sm text-muted-foreground mb-4">Unknown match.</p>
        <button onClick={() => navigate("/matches")} className="text-sm text-[#AAFF57] hover:underline">Back to Matches</button>
      </div>
    );
  }
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
            <button onClick={() => navigate("/simulator")} className="flex items-center gap-2 border border-border text-foreground px-4 py-2 rounded-lg text-sm font-medium hover:border-[#AAFF57]/40 hover:text-[#AAFF57] transition-colors">
              <PlayCircle size={14} /> Simulate Match
            </button>
            <button onClick={() => navigate("/recommendations")} className="flex items-center gap-2 bg-[#AAFF57] text-[#0D0D06] px-4 py-2 rounded-lg text-sm font-semibold hover:opacity-90 transition-opacity">
              <Zap size={14} /> Get AI Selection
            </button>
          </div>
        </div>
      </div>

      {/* Opponent form — real results (matches.team_last5), not placeholder data */}
      <div className="bg-card border border-border rounded-xl p-5">
        <h3 className="font-display text-base font-semibold text-foreground mb-4">Opponent Form</h3>
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-full bg-secondary flex items-center justify-center text-sm font-bold text-foreground">{match.team2.slice(0, 3).toUpperCase()}</div>
          <div>
            <div className="font-semibold text-foreground">{match.team2}</div>
            <div className="text-[11px] text-muted-foreground">Last 5 results</div>
          </div>
          <div className="flex gap-1.5 ml-auto">
            {match.opponentForm.length > 0 ? match.opponentForm.map((r, i) => (
              <span key={i} className={`w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-bold ${r === "W" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"}`}>{r}</span>
            )) : <span className="text-[12px] text-muted-foreground">No recent results on file</span>}
          </div>
        </div>
      </div>
    </div>
  );
}

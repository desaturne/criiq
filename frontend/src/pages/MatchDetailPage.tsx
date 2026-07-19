import { useState, useEffect } from "react";
import { useNavigate, useParams } from "react-router";
import { ChevronLeft, MapPin } from "lucide-react";
import * as api from "../lib/api";
import { mapApiMatch } from "../lib/mappers";
import { Match } from "../types/index";
import { RealMatchScorecard, RealInningsCard } from "../components/match/Scorecard";

export function MatchDetailPage() {
  const { id: matchId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [match, setMatch] = useState<Match | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  // Scorecard only exists for a match that's actually been played -- a
  // fixture "f<n>" has no deliveries on file yet, so it's fetched separately
  // (and allowed to fail quietly) rather than blocking the page on data that
  // genuinely doesn't exist for upcoming fixtures.
  const [innings, setInnings] = useState<RealInningsCard[] | null>(null);
  const [resultLoading, setResultLoading] = useState(false);

  useEffect(() => {
    if (!matchId) return;
    let cancelled = false;
    api.getMatch(matchId)
      .then(m => { if (!cancelled) setMatch(mapApiMatch(m)); })
      .catch(() => { if (!cancelled) setNotFound(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [matchId]);

  useEffect(() => {
    if (!matchId || !match || match.status === "Upcoming") return;
    let cancelled = false;
    setResultLoading(true);
    api.getMatchScorecard(matchId)
      .then(res => { if (!cancelled) setInnings(res.innings); })
      .catch(() => { /* allowed to fail quietly -- no ball-by-ball data on file */ })
      .finally(() => { if (!cancelled) setResultLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchId, match?.status]);

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

      {/* Hero -- read-only summary of an already-played match. No Simulate/AI
          Selection actions here: this page shows what actually happened
          (real scorecard + win-probability below), it doesn't set up a
          hypothetical trial -- that's what the standalone Simulator page is
          for. */}
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

      {/* Real ball-by-ball scorecard -- only exists once this match has
          actually been played (a fixture has none yet). */}
      {match.status !== "Upcoming" && (
        <div className="space-y-5 mt-5">
          {resultLoading && !innings && (
            <div className="py-10 text-center text-sm text-muted-foreground">Loading match result…</div>
          )}
          {innings && innings.length > 0 && <RealMatchScorecard innings={innings} />}
          {!resultLoading && (!innings || innings.length === 0) && (
            <p className="text-[12px] text-muted-foreground text-center py-4">No ball-by-ball data on file for this match.</p>
          )}
        </div>
      )}
    </div>
  );
}

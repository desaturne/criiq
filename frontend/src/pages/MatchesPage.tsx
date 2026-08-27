import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { useNavigate } from "react-router";
import { MapPin, ArrowRight, X } from "lucide-react";
import * as api from "../lib/api";
import { mapApiMatch } from "../lib/mappers";
import { Match } from "../types/index";

type FilterMode = "all" | "country" | "h2h";

export function MatchesPage() {
  const navigate = useNavigate();
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const statusColor = { Upcoming: "bg-blue-500/15 text-blue-400", Live: "bg-green-500/15 text-green-400", Completed: "bg-secondary text-muted-foreground" };

  // Gender is always applied (matches.py's `gender` filter) -- men's and
  // women's sides share team names (e.g. "India"), so leaving it off would
  // silently blend the two into one list.
  const [gender, setGender] = useState<"female" | "male">("female");
  const [mode, setMode] = useState<FilterMode>("all");
  const [country, setCountry] = useState("");
  const [h2hTeam1, setH2hTeam1] = useState("");
  const [h2hTeam2, setH2hTeam2] = useState("");
  const [teams, setTeams] = useState<string[]>([]);

  // Real team names for this gender, for the two dropdowns below -- not a
  // hardcoded list, since which countries have real T20I data differs by
  // gender (see model-training/README.md, distinct-player-count differences).
  useEffect(() => {
    api.listTeams({ gender }).then(res => setTeams(res.map(t => t.team))).catch(() => setTeams([]));
  }, [gender]);

  // Reset the mode-specific selections whenever gender changes -- a country
  // valid for women's teams may not have any men's fixtures on file (or vice
  // versa), so carrying a stale selection across the toggle would silently
  // filter to "no matches" instead of an obviously-cleared picker.
  useEffect(() => {
    setCountry(""); setH2hTeam1(""); setH2hTeam2("");
  }, [gender]);

  useEffect(() => {
    setLoading(true);
    const params: Parameters<typeof api.listMatches>[0] = { gender };
    if (mode === "country" && country) params.country = country;
    if (mode === "h2h" && h2hTeam1 && h2hTeam2) { params.team1 = h2hTeam1; params.team2 = h2hTeam2; }
    // Only completed matches are shown here -- "upcoming" fixtures are
    // placeholder rows (see backend/matches.py's fixture_to_json) with no
    // real result/scorecard/win-prob to show, so surfacing them alongside
    // real played matches was misleading.
    api.listMatches(params)
      .then(res => setMatches(res.completed.map(mapApiMatch)))
      .catch(() => setMatches([]))
      .finally(() => setLoading(false));
  }, [gender, mode, country, h2hTeam1, h2hTeam2]);

  const clearFilter = () => { setMode("all"); setCountry(""); setH2hTeam1(""); setH2hTeam2(""); };

  return (
    <div className="p-5 max-w-screen-xl mx-auto">
      <div className="flex items-center justify-between mb-5 flex-wrap gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold text-foreground">Matches</h1>
          <p className="text-sm text-muted-foreground mt-0.5">Completed fixtures</p>
        </div>
        <div className="flex rounded-lg border border-border overflow-hidden">
          {(["female", "male"] as const).map(g => (
            <button key={g} onClick={() => setGender(g)}
              className={`px-3 py-1.5 text-sm font-medium transition-colors ${gender === g ? "bg-[#AAFF57] text-[#0D0D06]" : "bg-secondary text-muted-foreground hover:text-foreground"}`}>
              {g === "female" ? "Women" : "Men"}
            </button>
          ))}
        </div>
      </div>

      {/* Filter mode tabs */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        {([
          { id: "all" as const, label: "All matches" },
          { id: "country" as const, label: "By country" },
          { id: "h2h" as const, label: "Team vs Team" },
        ]).map(t => (
          <button key={t.id} onClick={() => setMode(t.id)}
            className={`px-3 py-1.5 text-[13px] rounded-lg border transition-colors ${mode === t.id ? "bg-[#AAFF57]/10 border-[#AAFF57]/40 text-[#AAFF57] font-medium" : "border-border text-muted-foreground hover:text-foreground"}`}>
            {t.label}
          </button>
        ))}

        {mode === "country" && (
          <select value={country} onChange={e => setCountry(e.target.value)}
            className="text-sm bg-secondary border border-border rounded-lg px-3 py-1.5 text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
            <option value="">Select a country…</option>
            {teams.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        )}

        {mode === "h2h" && (
          <>
            <select value={h2hTeam1} onChange={e => setH2hTeam1(e.target.value)}
              className="text-sm bg-secondary border border-border rounded-lg px-3 py-1.5 text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
              <option value="">Team A…</option>
              {teams.filter(t => t !== h2hTeam2).map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <span className="text-[12px] text-muted-foreground">vs</span>
            <select value={h2hTeam2} onChange={e => setH2hTeam2(e.target.value)}
              className="text-sm bg-secondary border border-border rounded-lg px-3 py-1.5 text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
              <option value="">Team B…</option>
              {teams.filter(t => t !== h2hTeam1).map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </>
        )}

        {mode !== "all" && (
          <button onClick={clearFilter} className="flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground transition-colors">
            <X size={12} /> Clear
          </button>
        )}
      </div>

      {loading ? (
        <div className="py-16 text-center text-sm text-muted-foreground">Loading matches…</div>
      ) : matches.length === 0 ? (
        <div className="py-16 text-center text-sm text-muted-foreground">
          {mode === "h2h" && (!h2hTeam1 || !h2hTeam2) ? "Pick both teams to see their head-to-head history."
            : mode === "country" && !country ? "Pick a country to see its matches."
            : "No matches found for this filter."}
        </div>
      ) : (
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
      )}
    </div>
  );
}

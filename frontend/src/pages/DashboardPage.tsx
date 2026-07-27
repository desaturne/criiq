import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useNavigate } from "react-router";
import { FileText, Search, GitCompare } from "lucide-react";
import { AnimatedStat } from "../components/common/AnimatedStat";
import { PlayerCard } from "../components/player/PlayerCard";
import { PlayerCompareModal } from "../components/player/PlayerCompareModal";
import * as api from "../lib/api";
import { mapApiPlayerListItem } from "../lib/mappers";
import { Player } from "../types/index";

// Read-only scouting/browsing view. Squad selection (Select/Reserve/Exclude,
// the Playing XI panel) lives on the Squads page instead -- this page is
// purely "look at real player data", never a place to build a squad from.
export function DashboardPage() {
  const navigate = useNavigate();
  const [team, setTeam] = useState("India");
  const [gender, setGender] = useState<"female" | "male">("female");
  const [opposition, setOpposition] = useState("Australia");
  const [search, setSearch] = useState("");
  const [filterRole, setFilterRole] = useState("All");
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [showCompare, setShowCompare] = useState(false);
  const [players, setPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.listPlayers({ search, country: team, gender, limit: 100 })
      .then(res => { if (!cancelled) setPlayers(res.players.map(mapApiPlayerListItem)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [search, team, gender]);

  const toggleCompare = (id: string) => {
    setCompareIds(prev =>
      prev.includes(id)
        ? prev.filter(x => x !== id)
        : prev.length < 3 ? [...prev, id] : prev
    );
  };

  const filtered = players.filter(p => filterRole === "All" || p.role === filterRole);

  // Real aggregates from the fetched squad, not fabricated placeholder numbers.
  const stats = useMemo(() => {
    const n = players.length;
    const avgForm = n ? Math.round(players.reduce((s, p) => s + p.score, 0) / n) : 0;
    const active = players.filter(p => p.status === "ACTIVE").length;
    const inForm = players.filter(p => p.score >= 70).length;
    return { total: n, avgForm, active, inForm };
  }, [players]);

  return (
    <div className="p-5 max-w-screen-xl mx-auto pb-16">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-5">
        <div className="flex-1">
          <h1 className="font-display text-2xl font-bold text-foreground">Player Form</h1>
          <p className="text-sm text-muted-foreground mt-0.5">Scouting view · {team} {gender === "female" ? "Women's" : "Men's"} squad · vs {opposition}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex rounded-lg border border-border overflow-hidden">
            {(["female", "male"] as const).map(g => (
              <button key={g} onClick={() => setGender(g)}
                className={`px-3 py-1.5 text-sm font-medium transition-colors ${gender === g ? "bg-[#AAFF57] text-[#0D0D06]" : "bg-secondary text-muted-foreground hover:text-foreground"}`}>
                {g === "female" ? "Women" : "Men"}
              </button>
            ))}
          </div>
          <select value={team} onChange={e => setTeam(e.target.value)} title="Squad / nationality"
            className="text-sm bg-secondary border border-border rounded-lg px-3 py-1.5 text-foreground font-medium focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
            {["India", "Australia", "England", "South Africa", "New Zealand", "Pakistan"].map(t => <option key={t}>{t}</option>)}
          </select>
          <select value={opposition} onChange={e => setOpposition(e.target.value)} title="Opponent"
            className="text-sm bg-secondary border border-border rounded-lg px-3 py-1.5 text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
            {["Australia", "England", "South Africa", "New Zealand", "Pakistan", "India"].filter(t => t !== team).map(t => <option key={t}>{t}</option>)}
          </select>
        </div>
      </div>

      {/* Summary stats — real aggregates over the currently-filtered squad */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
        {[
          { label: "Players Shown", value: stats.total, unit: "", color: "#AAFF57" },
          { label: "Avg Form Score", value: stats.avgForm, unit: "/100", color: "#60A5FA" },
          { label: "Active", value: stats.active, unit: `/${stats.total}`, color: "#34D399" },
          { label: "In Form (70+)", value: stats.inForm, unit: `/${stats.total}`, color: "#A78BFA" },
        ].map(s => (
          <div key={s.label} className="bg-card border border-border rounded-xl p-4">
            <div className="font-mono text-2xl font-bold" style={{ color: s.color }}><AnimatedStat value={s.value} suffix={s.unit} /></div>
            <div className="text-[11px] text-muted-foreground mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex gap-2 mb-4 flex-wrap items-center">
        <div className="relative flex-1 max-w-xs">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search players…"
            className="w-full pl-9 pr-3 py-1.5 text-sm bg-secondary border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40 text-foreground placeholder:text-muted-foreground" />
        </div>
        <div className="flex gap-1.5 flex-wrap">
          {["All", "Batsman", "Bowler", "All-rounder"].map(r => (
            <button key={r} onClick={() => setFilterRole(r)}
              className={`px-3 py-1.5 text-[12px] rounded-lg border transition-colors ${filterRole === r ? "bg-[#AAFF57] text-[#0D0D06] border-[#AAFF57] font-medium" : "border-border text-muted-foreground hover:text-foreground"}`}>
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* Player grid — browse only, no selection controls */}
      {loading ? (
        <div className="py-16 text-center text-sm text-muted-foreground">Loading players…</div>
      ) : filtered.length === 0 ? (
        <div className="py-16 text-center text-sm text-muted-foreground">No players match these filters.</div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {filtered.map((p, i) => (
            <PlayerCard
              key={p.id} player={p} index={i} opposition={opposition}
              comparing={compareIds.includes(p.id)}
              onToggleCompare={() => toggleCompare(p.id)}
              onViewProfile={() => navigate("/players/" + p.id)}
            />
          ))}
        </div>
      )}

      {/* Floating action buttons */}
      <div className="fixed bottom-6 right-6 flex flex-col items-end gap-2.5">
        <AnimatePresence>
          {compareIds.length >= 2 && (
            <motion.button
              key="compare"
              initial={{ scale: 0.8, opacity: 0, y: 10 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.8, opacity: 0, y: 10 }}
              whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.96 }}
              onClick={() => setShowCompare(true)}
              className="flex items-center gap-2 px-5 py-3 rounded-full font-semibold text-sm shadow-xl"
              style={{ background: "#3ADCFF", color: "#0D0D06", boxShadow: "0 8px 28px rgba(58,220,255,0.3)" }}
            >
              <GitCompare size={15} />
              Compare {compareIds.length} Players
            </motion.button>
          )}
        </AnimatePresence>
        <motion.button whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.97 }}
          onClick={() => navigate("/reports")}
          className="flex items-center gap-2 bg-card border border-border text-foreground px-4 py-2.5 rounded-full text-sm shadow-lg">
          <FileText size={14} /> Generate Report
        </motion.button>
      </div>

      {/* Player Compare Modal */}
      {showCompare && compareIds.length >= 2 && (
        <PlayerCompareModal
          players={players}
          playerIds={compareIds}
          opposition={opposition}
          selections={{}}
          onSelect={() => {}}
          onClose={() => setShowCompare(false)}
          onRemove={id => {
            const next = compareIds.filter(x => x !== id);
            setCompareIds(next);
            if (next.length < 2) setShowCompare(false);
          }}
        />
      )}
    </div>
  );
}

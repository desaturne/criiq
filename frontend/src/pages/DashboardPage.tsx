import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useNavigate } from "react-router";
import { Users, FileText, Search, CheckCircle, GitCompare } from "lucide-react";
import { AnimatedStat } from "../components/common/AnimatedStat";
import { PlayerCard } from "../components/player/PlayerCard";
import { PlayerCompareModal } from "../components/player/PlayerCompareModal";
import { SquadSelectionPanel } from "../components/squad/SquadSelectionPanel";
import { useApp } from "../context/AppContext";
import * as api from "../lib/api";
import { mapApiPlayerListItem } from "../lib/mappers";
import { Player, SelectionState } from "../types/index";

export function DashboardPage() {
  const { selections, setSelections } = useApp();
  const navigate = useNavigate();
  const [opposition, setOpposition] = useState("Australia");
  const [search, setSearch] = useState("");
  const [filterRole, setFilterRole] = useState("All");
  const [filterStatus, setFilterStatus] = useState<SelectionState | "All">("All");
  const [showSquadPanel, setShowSquadPanel] = useState(false);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [showCompare, setShowCompare] = useState(false);
  const [players, setPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.listPlayers({ search, limit: 100 })
      .then(res => { if (!cancelled) setPlayers(res.players.map(mapApiPlayerListItem)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [search]);

  const toggleCompare = (id: string) => {
    setCompareIds(prev =>
      prev.includes(id)
        ? prev.filter(x => x !== id)
        : prev.length < 3 ? [...prev, id] : prev
    );
  };

  const setSelection = (id: string, s: SelectionState) =>
    setSelections(prev => ({ ...prev, [id]: s }));

  const selectedCount = Object.values(selections).filter(s => s === "select").length;
  const reserveCount  = Object.values(selections).filter(s => s === "reserve").length;

  const filtered = players.filter(p => {
    const matchRole = filterRole === "All" || p.role === filterRole;
    const matchStatus = filterStatus === "All" || selections[p.id] === filterStatus;
    return matchRole && matchStatus;
  });

  return (
    <div className="p-5 max-w-screen-xl mx-auto pb-28">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-5">
        <div className="flex-1">
          <h1 className="font-display text-2xl font-bold text-foreground">Player Form</h1>
          <p className="text-sm text-muted-foreground mt-0.5">Select players for your XI · vs {opposition}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select value={opposition} onChange={e => setOpposition(e.target.value)}
            className="text-sm bg-secondary border border-border rounded-lg px-3 py-1.5 text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
            {["Australia", "England", "South Africa", "New Zealand", "Pakistan"].map(t => <option key={t}>{t}</option>)}
          </select>
          <button onClick={() => setShowSquadPanel(true)}
            className="text-[12px] px-3 py-1.5 rounded-full font-medium border transition-all"
            style={selectedCount > 0 ? { background: "#5FA800", color: "#fff", borderColor: "#5FA800" } : { borderColor: "var(--border)", color: "var(--muted-foreground)" }}>
            XI: {selectedCount}/11
          </button>
          {reserveCount > 0 && (
            <button onClick={() => setShowSquadPanel(true)}
              className="text-[12px] bg-secondary text-muted-foreground border border-border px-2.5 py-1 rounded-full">
              Reserve: {reserveCount}
            </button>
          )}
        </div>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
        {[{ label: "Avg Form Score", value: 83, unit: "/100", color: "#AAFF57" }, { label: "Squad Avg SR", value: 141, unit: "", color: "#60A5FA" }, { label: "Win Probability", value: 68, unit: "%", color: "#34D399" }, { label: "Players In Form", value: 8, unit: "/11", color: "#A78BFA" }].map(s => (
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
        <div className="flex gap-1.5 flex-wrap border-l border-border pl-2 ml-1">
          {(["All", "select", "reserve", "exclude"] as const).map(s => {
            const labels: Record<string, string> = { All: "All status", select: "Selected", reserve: "Reserve", exclude: "Excluded" };
            const colors: Record<string, string> = { select: "#5FA800", reserve: "#8A8970", exclude: "#E5484D" };
            return (
              <button key={s} onClick={() => setFilterStatus(s)}
                className="px-2.5 py-1.5 text-[11px] rounded-lg border transition-colors"
                style={filterStatus === s && s !== "All" ? { background: colors[s], color: "#fff", borderColor: colors[s] } : filterStatus === s ? { background: "var(--secondary)", color: "var(--foreground)", borderColor: "var(--border)" } : { borderColor: "var(--border)", color: "var(--muted-foreground)" }}>
                {labels[s]}
              </button>
            );
          })}
        </div>
      </div>

      {/* Player grid */}
      {loading ? (
        <div className="py-16 text-center text-sm text-muted-foreground">Loading players…</div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {filtered.map((p, i) => (
            <PlayerCard
              key={p.id} player={p} index={i} opposition={opposition}
              selection={selections[p.id] ?? "undecided"}
              onSelect={s => setSelection(p.id, s)}
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
          {selectedCount > 0 && (
            <motion.button
              key="view-squad"
              initial={{ scale: 0.8, opacity: 0, y: 10 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.8, opacity: 0, y: 10 }}
              whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.96 }}
              onClick={() => setShowSquadPanel(true)}
              className="flex items-center gap-2 px-5 py-3 rounded-full font-semibold text-sm shadow-xl"
              style={{ background: "#5FA800", color: "#fff", boxShadow: "0 8px 32px rgba(95,168,0,0.35)" }}
            >
              <Users size={15} />
              View Squad · {selectedCount}/11
              {selectedCount === 11 && <CheckCircle size={14} />}
            </motion.button>
          )}
        </AnimatePresence>
        <motion.button whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.97 }}
          onClick={() => navigate("/reports")}
          className="flex items-center gap-2 bg-card border border-border text-foreground px-4 py-2.5 rounded-full text-sm shadow-lg">
          <FileText size={14} /> Generate Report
        </motion.button>
      </div>

      {/* Squad Selection Panel */}
      <AnimatePresence>
        {showSquadPanel && (
          <SquadSelectionPanel
            players={players}
            selections={selections}
            opposition={opposition}
            format="T20I"
            onClose={() => setShowSquadPanel(false)}
            onReset={() => setSelections({})}
            onChangeSelection={setSelection}
          />
        )}
      </AnimatePresence>

      {/* Player Compare Modal */}
      {showCompare && compareIds.length >= 2 && (
        <PlayerCompareModal
          players={players}
          playerIds={compareIds}
          opposition={opposition}
          selections={selections}
          onSelect={setSelection}
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

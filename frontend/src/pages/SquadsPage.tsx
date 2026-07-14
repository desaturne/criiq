import React, { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useNavigate } from "react-router";
import { Search, CheckCircle, X, Eye, Download, UserPlus, Edit, Trash2 } from "lucide-react";
import { SparkLine } from "../components/common/SparkLine";
import { StatusBadge } from "../components/common/StatusBadge";
import { PLAYERS } from "../data/players";
import { Player, PlayerStatus } from "../types/index";

export function SquadsPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [selectedRows, setSelectedRows] = useState<string[]>([]);
  const [filterStatus, setFilterStatus] = useState("All");
  const [players, setPlayers] = useState<Player[]>(PLAYERS);
  const [showAddPanel, setShowAddPanel] = useState(false);
  const [addSuccess, setAddSuccess] = useState(false);
  const [newPlayer, setNewPlayer] = useState({ name: "", role: "Batsman", battingHand: "Right", bowlingStyle: "", status: "ACTIVE" as PlayerStatus });

  const filtered = players.filter(p =>
    p.name.toLowerCase().includes(search.toLowerCase()) &&
    (filterStatus === "All" || p.status === filterStatus)
  );
  const toggleRow = (id: string) => setSelectedRows(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);

  const handleAddPlayer = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPlayer.name.trim()) return;
    const initials = newPlayer.name.trim().split(" ").map((w: string) => w[0]).join("").toUpperCase().slice(0, 3);
    const colors = ["#60A5FA", "#34D399", "#F59E0B", "#EC4899", "#A78BFA", "#FB923C", "#2DD4BF"];
    const color = colors[players.length % colors.length];
    const created: Player = {
      id: String(Date.now()), name: newPlayer.name.trim(), role: newPlayer.role, archetype: newPlayer.role,
      battingHand: newPlayer.battingHand as "Right" | "Left", bowlingStyle: newPlayer.bowlingStyle || "—",
      status: newPlayer.status, team: "India", initials, color, isBatsman: newPlayer.role === "Batsman" || newPlayer.role === "Wicket-keeper",
      recentForm: [30, 25, 40, 20, 35], recentSR: [130, 125, 140, 120, 135],
      vsOpponent: 65, vsInsight: "New addition — building match record.",
      powerplay: 60, middle: 65, death: 60,
      career: { matches: 0, innings: 0, runs: 0, avg: 0, sr: 0, fifties: 0, hundreds: 0 },
      score: 60, breakdown: { form: 60, vsOpponent: 60, venueFit: 60, matchupAdvantage: 60 },
    };
    setPlayers(prev => [...prev, created]);
    setAddSuccess(true);
    setTimeout(() => { setAddSuccess(false); setShowAddPanel(false); setNewPlayer({ name: "", role: "Batsman", battingHand: "Right", bowlingStyle: "", status: "ACTIVE" }); }, 1500);
  };

  return (
    <div className="p-5 max-w-screen-xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="font-display text-2xl font-bold text-foreground">Squads</h1>
          <p className="text-sm text-muted-foreground mt-0.5">{players.length} players registered</p>
        </div>
        <div className="flex gap-2">
          <button className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-border rounded-lg text-muted-foreground hover:text-foreground transition-colors">
            <Download size={12} /> Export
          </button>
          <button onClick={() => setShowAddPanel(true)} className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#AAFF57] text-[#0D0D06] rounded-lg font-medium hover:opacity-90 transition-opacity">
            <UserPlus size={12} /> Add Player
          </button>
        </div>
      </div>
      <div className="flex gap-2 mb-4 flex-wrap">
        <div className="relative">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search…"
            className="pl-8 pr-3 py-1.5 text-sm bg-secondary border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40 text-foreground placeholder:text-muted-foreground w-52" />
        </div>
        {["All", "ACTIVE", "INCONSISTENT", "INACTIVE"].map(s => (
          <button key={s} onClick={() => setFilterStatus(s)}
            className={`px-2.5 py-1.5 text-[11px] rounded-lg border transition-colors ${filterStatus === s ? "bg-[#AAFF57] text-[#0D0D06] border-[#AAFF57] font-medium" : "border-border text-muted-foreground hover:text-foreground"}`}>
            {s}
          </button>
        ))}
      </div>
      {selectedRows.length > 0 && (
        <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mb-3 flex items-center gap-3 bg-[#AAFF57]/10 border border-[#AAFF57]/30 rounded-lg px-4 py-2">
          <span className="text-sm font-medium text-[#AAFF57]">{selectedRows.length} selected</span>
          <button className="text-xs text-muted-foreground hover:text-destructive transition-colors flex items-center gap-1"><Trash2 size={11} /> Deactivate</button>
          <button className="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"><Download size={11} /> Export selected</button>
        </motion.div>
      )}
      <div className="bg-card border border-border rounded-xl overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border">
              <th className="p-3 w-8"><input type="checkbox" className="rounded" onChange={e => setSelectedRows(e.target.checked ? players.map(p => p.id) : [])} /></th>
              {["Player", "Role", "Hand / Style", "Status", "Form (last 5)", "Score", "Actions"].map(h => (
                <th key={h} className="p-3 text-left text-[11px] font-medium text-muted-foreground uppercase tracking-wider">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((p, i) => (
              <motion.tr key={p.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.03 }}
                className={`border-b border-border hover:bg-secondary/40 transition-colors ${selectedRows.includes(p.id) ? "bg-secondary/60" : ""}`}>
                <td className="p-3"><input type="checkbox" checked={selectedRows.includes(p.id)} onChange={() => toggleRow(p.id)} className="rounded" /></td>
                <td className="p-3">
                  <div className="flex items-center gap-2">
                    <div className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0" style={{ backgroundColor: p.color + "33", color: p.color }}>{p.initials}</div>
                    <div>
                      <div className="text-[13px] font-medium text-foreground">{p.name}</div>
                      <div className="text-[10px] text-muted-foreground">{p.team}</div>
                    </div>
                  </div>
                </td>
                <td className="p-3 text-[12px] text-muted-foreground">{p.role}</td>
                <td className="p-3 text-[12px] text-muted-foreground">{p.battingHand} / {p.bowlingStyle}</td>
                <td className="p-3"><StatusBadge status={p.status} /></td>
                <td className="p-3"><SparkLine values={p.recentForm} color={p.color} width={60} height={22} /></td>
                <td className="p-3">
                  <div className="font-mono text-sm font-medium" style={{ color: p.color }}>{p.score}</div>
                </td>
                <td className="p-3">
                  <div className="flex items-center gap-1">
                    <button onClick={() => navigate("/players/" + p.id)} className="p-1.5 rounded hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors"><Eye size={13} /></button>
                    <button className="p-1.5 rounded hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors"><Edit size={13} /></button>
                    <button className="p-1.5 rounded hover:bg-secondary text-muted-foreground hover:text-destructive transition-colors"><Trash2 size={13} /></button>
                  </div>
                </td>
              </motion.tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Add Player Slide-in Panel */}
      <AnimatePresence>
        {showAddPanel && (
          <motion.div className="fixed inset-0 z-50 flex" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setShowAddPanel(false)} />
            <motion.div
              className="relative ml-auto flex flex-col bg-background h-full overflow-hidden shadow-2xl"
              style={{ width: "min(420px, 95vw)" }}
              initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }}
              transition={{ type: "spring", damping: 30, stiffness: 300 }}
            >
              <div className="flex items-center justify-between px-6 py-5 border-b border-border flex-shrink-0">
                <div>
                  <h2 className="font-display text-xl font-bold text-foreground">Add Player</h2>
                  <p className="text-[12px] text-muted-foreground mt-0.5">Register a new squad member</p>
                </div>
                <button onClick={() => setShowAddPanel(false)} className="p-2 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors"><X size={16} /></button>
              </div>
              <div className="flex-1 overflow-auto p-6">
                {addSuccess ? (
                  <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} className="flex flex-col items-center justify-center h-full gap-4">
                    <CheckCircle size={48} className="text-[#AAFF57]" />
                    <p className="text-lg font-semibold text-foreground">Player Added!</p>
                    <p className="text-sm text-muted-foreground">{newPlayer.name} has been registered.</p>
                  </motion.div>
                ) : (
                  <form onSubmit={handleAddPlayer} className="space-y-4">
                    <div className="space-y-1.5">
                      <label className="text-[12px] font-medium text-muted-foreground">Full Name *</label>
                      <input required value={newPlayer.name} onChange={e => setNewPlayer(p => ({ ...p, name: e.target.value }))} placeholder="e.g. Rohit Sharma"
                        className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40" />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-[12px] font-medium text-muted-foreground">Role *</label>
                      <select value={newPlayer.role} onChange={e => setNewPlayer(p => ({ ...p, role: e.target.value }))}
                        className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
                        {["Batsman", "Bowler", "All-rounder", "Wicket-keeper"].map(r => <option key={r}>{r}</option>)}
                      </select>
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-[12px] font-medium text-muted-foreground">Batting Hand</label>
                      <select value={newPlayer.battingHand} onChange={e => setNewPlayer(p => ({ ...p, battingHand: e.target.value }))}
                        className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
                        <option>Right</option>
                        <option>Left</option>
                      </select>
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-[12px] font-medium text-muted-foreground">Bowling Style</label>
                      <input value={newPlayer.bowlingStyle} onChange={e => setNewPlayer(p => ({ ...p, bowlingStyle: e.target.value }))} placeholder="e.g. Right-arm Fast"
                        className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40" />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-[12px] font-medium text-muted-foreground">Status</label>
                      <select value={newPlayer.status} onChange={e => setNewPlayer(p => ({ ...p, status: e.target.value as PlayerStatus }))}
                        className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
                        <option>ACTIVE</option>
                        <option>INCONSISTENT</option>
                        <option>INACTIVE</option>
                      </select>
                    </div>
                    <div className="pt-4 flex gap-3">
                      <button type="submit"
                        className="flex-1 py-2.5 bg-[#AAFF57] text-[#0D0D06] text-sm font-semibold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all flex items-center justify-center gap-2">
                        <UserPlus size={14} /> Add Player
                      </button>
                      <button type="button" onClick={() => setShowAddPanel(false)}
                        className="px-5 py-2.5 border border-border text-sm text-muted-foreground rounded-lg hover:text-foreground hover:border-foreground/30 transition-all">
                        Cancel
                      </button>
                    </div>
                  </form>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

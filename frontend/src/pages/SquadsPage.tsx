import React, { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useNavigate, useLocation } from "react-router";
import { Search, CheckCircle, X, Eye, Download, UserPlus, Edit, Trash2, Users, GitCompare, ClipboardList } from "lucide-react";
import { PlayerCard } from "../components/player/PlayerCard";
import { PlayerCompareModal } from "../components/player/PlayerCompareModal";
import { SparkLine } from "../components/common/SparkLine";
import { SquadSelectionPanel } from "../components/squad/SquadSelectionPanel";
import { StatusBadge } from "../components/common/StatusBadge";
import { useApp } from "../context/AppContext";
import * as api from "../lib/api";
import { mapApiPlayerListItem } from "../lib/mappers";
import { Player, PlayerStatus, SelectionState } from "../types/index";

export function SquadsPage() {
  const navigate = useNavigate();
  const { user } = useApp();
  const [team, setTeam] = useState(user?.country || "India");
  const [search, setSearch] = useState("");
  const [selectedRows, setSelectedRows] = useState<string[]>([]);
  const [filterStatus, setFilterStatus] = useState("All");
  const [gender, setGender] = useState<"female" | "male">("female");
  const [players, setPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddPanel, setShowAddPanel] = useState(false);
  const [addSuccess, setAddSuccess] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [newPlayer, setNewPlayer] = useState({ name: "", role: "Batter", battingHand: "Right", bowlingStyle: "", status: "ACTIVE" as PlayerStatus });

  const loadPlayers = () => {
    setLoading(true);
    return api.listPlayers({ limit: 100, country: team === "All" ? undefined : team, gender })
      .then(res => setPlayers(res.players.map(mapApiPlayerListItem)))
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadPlayers(); }, [team, gender]);

  const filtered = players.filter(p =>
    p.name.toLowerCase().includes(search.toLowerCase()) &&
    (filterStatus === "All" || p.status === filterStatus)
  );

  const roleGroups = React.useMemo(() => {
    const groups = [
      { key: "Batter", title: "Batters", players: [] as Player[] },
      { key: "Bowler", title: "Bowlers", players: [] as Player[] },
      { key: "All-rounder", title: "All-rounders", players: [] as Player[] },
      { key: "Wicket-keeper", title: "Wicket-keepers", players: [] as Player[] },
      { key: "Other", title: "Other Players", players: [] as Player[] },
    ];

    filtered.forEach(p => {
      const roleLower = (p.role || "").toLowerCase();
      if (roleLower.includes("bat")) {
        groups[0].players.push(p);
      } else if (roleLower.includes("bowl")) {
        groups[1].players.push(p);
      } else if (roleLower.includes("round")) {
        groups[2].players.push(p);
      } else if (roleLower.includes("keeper")) {
        groups[3].players.push(p);
      } else {
        groups[4].players.push(p);
      }
    });

    return groups.filter(g => g.players.length > 0);
  }, [filtered]);

  const toggleRow = (id: string) => setSelectedRows(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);

  const openAdd = () => {
    setEditingId(null);
    setNewPlayer({ name: "", role: "Batter", battingHand: "Right", bowlingStyle: "", status: "ACTIVE" });
    setShowAddPanel(true);
  };

  const openEdit = (p: Player) => {
    setEditingId(p.id);
    setNewPlayer({ name: p.name, role: p.role, battingHand: p.battingHand, bowlingStyle: p.bowlingStyle === "—" ? "" : p.bowlingStyle, status: p.status === "UNKNOWN" ? "ACTIVE" : p.status });
    setShowAddPanel(true);
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this player?")) return;
    setError(null);
    try {
      await api.deletePlayer(id);
      await loadPlayers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't delete this player");
    }
  };

  const handleAddPlayer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPlayer.name.trim()) return;
    const body = {
      name: newPlayer.name.trim(), role: newPlayer.role,
      batting_hand: newPlayer.battingHand, bowling_style: newPlayer.bowlingStyle || null,
      status: newPlayer.status,
    };
    setError(null);
    try {
      if (editingId) {
        await api.updatePlayer(editingId, body);
      } else {
        await api.addPlayer(body);
      }
      await loadPlayers();
      setAddSuccess(true);
      setTimeout(() => {
        setAddSuccess(false); setShowAddPanel(false); setEditingId(null);
        setNewPlayer({ name: "", role: "Batter", battingHand: "Right", bowlingStyle: "", status: "ACTIVE" });
      }, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save this player");
    }
  };

  const exportToCSV = (playersToExport: Player[], filename: string) => {
    const headers = ["ID", "Name", "Team", "Role", "Batting Hand", "Bowling Style", "Status", "Score"];
    const rows = playersToExport.map(p => [
      `"${p.id}"`,
      `"${p.name.replace(/"/g, '""')}"`,
      `"${p.team.replace(/"/g, '""')}"`,
      `"${p.role.replace(/"/g, '""')}"`,
      `"${p.battingHand}"`,
      `"${(p.bowlingStyle || "").replace(/"/g, '""')}"`,
      `"${p.status}"`,
      p.score
    ]);

    const csvContent = [headers.join(","), ...rows.map(r => r.join(","))].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleExportSelected = () => {
    const selectedPlayers = players.filter(p => selectedRows.includes(p.id));
    if (selectedPlayers.length > 0) {
      exportToCSV(selectedPlayers, `${team}_selected_players.csv`);
    }
  };

  const handleExportAll = () => {
    if (filtered.length > 0) {
      exportToCSV(filtered, `${team}_squad_roster.csv`);
    }
  };

  const handleDeactivateSelected = async () => {
    if (selectedRows.length === 0) return;
    if (!confirm(`Deactivate ${selectedRows.length} selected player(s)?`)) return;

    setPlayers(prev => prev.map(p => {
      if (selectedRows.includes(p.id)) {
        return { ...p, status: "INACTIVE" as PlayerStatus };
      }
      return p;
    }));

    for (const id of selectedRows) {
      if (id.startsWith("m")) {
        const p = players.find(x => x.id === id);
        if (p) {
          try {
            await api.updatePlayer(id, {
              name: p.name,
              role: p.role,
              country: p.team,
              batting_hand: p.battingHand,
              bowling_style: p.bowlingStyle === "—" ? null : p.bowlingStyle,
              status: "INACTIVE"
            });
          } catch (err) {
            console.error("Failed to deactivate player", id, err);
          }
        }
      }
    }
    setSelectedRows([]);
  };

  return (
    <div className="p-5 max-w-screen-xl mx-auto pb-16">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="font-display text-2xl font-bold text-foreground">Squad Roster</h1>
          <p className="text-sm text-muted-foreground mt-0.5">{players.length} players in {team} {gender === "female" ? "Women's" : "Men's"} pool</p>
        </div>
        <div className="flex gap-2">
          <button onClick={handleExportAll} className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-border rounded-lg text-muted-foreground hover:text-foreground transition-colors">
            <Download size={12} /> Export
          </button>
          <button onClick={openAdd} className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#AAFF57] text-[#0D0D06] rounded-lg font-medium hover:opacity-90 transition-opacity">
            <UserPlus size={12} /> Add Player
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-3 text-[12px] text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{error}</div>
      )}

      {/* Filters: Fixed Team Badge (no dropdown) & Gender selector & Search */}
      <div className="flex gap-2 mb-4 flex-wrap items-center">
        <div className="flex rounded-lg border border-border overflow-hidden">
          {(["female", "male"] as const).map(g => (
            <button key={g} onClick={() => setGender(g)}
              className={`px-3 py-1.5 text-sm font-medium transition-colors ${gender === g ? "bg-[#AAFF57] text-[#0D0D06]" : "bg-secondary text-muted-foreground hover:text-foreground"}`}>
              {g === "female" ? "Women" : "Men"}
            </button>
          ))}
        </div>
        {/* Country Selector Dropdown */}
        <select value={team} onChange={e => setTeam(e.target.value)} title="Squad / nationality"
          className="text-sm bg-secondary border border-border rounded-lg px-3 py-1.5 text-foreground font-medium focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
          {["India", "Australia", "England", "South Africa", "New Zealand", "Pakistan", "Sri Lanka", "West Indies", "All"].map(t => <option key={t}>{t}</option>)}
        </select>
        <div className="relative">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search players…"
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
          <button onClick={handleDeactivateSelected} className="text-xs text-muted-foreground hover:text-destructive transition-colors flex items-center gap-1"><Trash2 size={11} /> Deactivate</button>
          <button onClick={handleExportSelected} className="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"><Download size={11} /> Export selected</button>
        </motion.div>
      )}

      {loading ? (
        <div className="py-16 text-center text-sm text-muted-foreground">Loading squad…</div>
      ) : (
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
            {roleGroups.map(group => (
              <React.Fragment key={group.key}>
                <tr className="bg-secondary/70 border-y border-border">
                  <td colSpan={8} className="px-4 py-2 text-[11px] font-bold tracking-wider text-[#AAFF57] uppercase">
                    {group.title} ({group.players.length})
                  </td>
                </tr>
                {group.players.map((p, i) => (
                  <motion.tr key={p.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.02 }}
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
                        <button onClick={() => openEdit(p)} className="p-1.5 rounded hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors"><Edit size={13} /></button>
                        <button onClick={() => handleDelete(p.id)} className="p-1.5 rounded hover:bg-secondary text-muted-foreground hover:text-destructive transition-colors"><Trash2 size={13} /></button>
                      </div>
                    </td>
                  </motion.tr>
                ))}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
      )}

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
                  <h2 className="font-display text-xl font-bold text-foreground">{editingId ? "Edit Player" : "Add Player"}</h2>
                  <p className="text-[12px] text-muted-foreground mt-0.5">{editingId ? "Update squad member details" : "Register a new squad member"}</p>
                </div>
                <button onClick={() => setShowAddPanel(false)} className="p-2 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors"><X size={16} /></button>
              </div>
              <div className="flex-1 overflow-auto p-6">
                {addSuccess ? (
                  <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} className="flex flex-col items-center justify-center h-full gap-4">
                    <CheckCircle size={48} className="text-[#AAFF57]" />
                    <p className="text-lg font-semibold text-foreground">{editingId ? "Player Updated!" : "Player Added!"}</p>
                    <p className="text-sm text-muted-foreground">{newPlayer.name} has been {editingId ? "updated" : "registered"}.</p>
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
                        {["Batter", "Bowler", "All-rounder", "Wicket-keeper"].map(r => <option key={r}>{r}</option>)}
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
                        <UserPlus size={14} /> {editingId ? "Save Changes" : "Add Player"}
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

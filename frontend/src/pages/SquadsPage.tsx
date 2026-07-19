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
  const { selections, setSelections } = useApp();
  const [tab, setTab] = useState<"roster" | "build">("roster");
  const [search, setSearch] = useState("");
  const [selectedRows, setSelectedRows] = useState<string[]>([]);
  const [filterStatus, setFilterStatus] = useState("All");
  const [team, setTeam] = useState("India");
  const [gender, setGender] = useState<"female" | "male">("female");
  const [opposition, setOpposition] = useState("Australia");
  const [players, setPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddPanel, setShowAddPanel] = useState(false);
  const [addSuccess, setAddSuccess] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [newPlayer, setNewPlayer] = useState({ name: "", role: "Batsman", battingHand: "Right", bowlingStyle: "", status: "ACTIVE" as PlayerStatus });
  const [showSquadPanel, setShowSquadPanel] = useState(false);
  const location = useLocation();
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [showCompare, setShowCompare] = useState(false);

  const loadPlayers = () => {
    setLoading(true);
    return api.listPlayers({ limit: 100, country: team === "All" ? undefined : team, gender })
      .then(res => setPlayers(res.players.map(mapApiPlayerListItem)))
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadPlayers(); }, [team, gender]);

  // Arriving from Recommendations' "Confirm Selection" -> open straight onto
  // the Playing XI panel so the confirmed picks are shown, not left to a click.
  useEffect(() => {
    if ((location.state as { openSquad?: boolean } | null)?.openSquad) {
      setShowSquadPanel(true);
    }
  }, [location.state]);

  const filtered = players.filter(p =>
    p.name.toLowerCase().includes(search.toLowerCase()) &&
    (filterStatus === "All" || p.status === filterStatus)
  );
  const toggleRow = (id: string) => setSelectedRows(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  const toggleCompare = (id: string) => setCompareIds(prev =>
    prev.includes(id) ? prev.filter(x => x !== id) : prev.length < 3 ? [...prev, id] : prev
  );
  const setSelection = (id: string, s: SelectionState) =>
    setSelections(prev => ({ ...prev, [id]: s }));
  const selectedCount = Object.values(selections).filter(s => s === "select").length;
  const reserveCount = Object.values(selections).filter(s => s === "reserve").length;

  const openAdd = () => {
    setEditingId(null);
    setNewPlayer({ name: "", role: "Batsman", battingHand: "Right", bowlingStyle: "", status: "ACTIVE" });
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
        setNewPlayer({ name: "", role: "Batsman", battingHand: "Right", bowlingStyle: "", status: "ACTIVE" });
      }, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save this player");
    }
  };

  return (
    <div className="p-5 max-w-screen-xl mx-auto pb-16">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="font-display text-2xl font-bold text-foreground">Squads</h1>
          <p className="text-sm text-muted-foreground mt-0.5">{players.length} players in {team} {gender === "female" ? "Women's" : "Men's"} pool</p>
        </div>
        {tab === "roster" && (
          <div className="flex gap-2">
            <button className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-border rounded-lg text-muted-foreground hover:text-foreground transition-colors">
              <Download size={12} /> Export
            </button>
            <button onClick={openAdd} className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#AAFF57] text-[#0D0D06] rounded-lg font-medium hover:opacity-90 transition-opacity">
              <UserPlus size={12} /> Add Player
            </button>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-4 border-b border-border">
        {[{ id: "roster" as const, label: "Roster", icon: ClipboardList }, { id: "build" as const, label: "Build XI", icon: Users }].map(t => {
          const Icon = t.icon;
          return (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 px-3 py-2.5 text-[13px] border-b-2 transition-colors ${tab === t.id ? "border-[#AAFF57] text-foreground font-medium" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
              <Icon size={13} /> {t.label}
            </button>
          );
        })}
      </div>

      {error && (
        <div className="mb-3 text-[12px] text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{error}</div>
      )}

      {/* Shared team/gender filters -- drive the same fetched player pool for both tabs */}
      <div className="flex gap-2 mb-4 flex-wrap">
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
          {["India", "Australia", "England", "South Africa", "New Zealand", "Pakistan", "All"].map(t => <option key={t}>{t}</option>)}
        </select>
        {tab === "roster" && (
          <>
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
          </>
        )}
        {tab === "build" && (
          <select value={opposition} onChange={e => setOpposition(e.target.value)} title="Opponent"
            className="text-sm bg-secondary border border-border rounded-lg px-3 py-1.5 text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
            {["Australia", "England", "South Africa", "New Zealand", "Pakistan", "India"].filter(t => t !== team).map(t => <option key={t}>{t}</option>)}
          </select>
        )}
      </div>

      {tab === "roster" && selectedRows.length > 0 && (
        <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mb-3 flex items-center gap-3 bg-[#AAFF57]/10 border border-[#AAFF57]/30 rounded-lg px-4 py-2">
          <span className="text-sm font-medium text-[#AAFF57]">{selectedRows.length} selected</span>
          <button className="text-xs text-muted-foreground hover:text-destructive transition-colors flex items-center gap-1"><Trash2 size={11} /> Deactivate</button>
          <button className="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"><Download size={11} /> Export selected</button>
        </motion.div>
      )}
      {loading ? (
        <div className="py-16 text-center text-sm text-muted-foreground">Loading squad…</div>
      ) : tab === "build" ? (
        <>
          {/* Empty-state prompt shown before the coach has picked anyone --
              tells them how the XI gets built and where it shows up. */}
          {selectedCount === 0 && (
            <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
              className="mb-4 flex items-center gap-3 bg-[#AAFF57]/[0.08] border border-[#AAFF57]/25 rounded-2xl px-4 py-3.5">
              <div className="w-10 h-10 rounded-full bg-[#AAFF57]/15 flex items-center justify-center flex-shrink-0">
                <Users size={18} className="text-[#AAFF57]" />
              </div>
              <div>
                <p className="text-[13px] font-semibold text-foreground">Build your Playing XI</p>
                <p className="text-[12px] text-muted-foreground">
                  Tap <span className="text-[#AAFF57] font-medium">Select</span> on any player below to add them — your XI builds up in{" "}
                  <span className="text-foreground font-medium">View Squad</span> as you go, up to 11.
                </p>
              </div>
            </motion.div>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {players.map((p, i) => (
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

          <div className="fixed bottom-6 right-6 flex flex-col items-end gap-2.5">
            <AnimatePresence>
              {compareIds.length >= 2 && (
                <motion.button key="compare" initial={{ scale: 0.8, opacity: 0, y: 10 }} animate={{ scale: 1, opacity: 1, y: 0 }} exit={{ scale: 0.8, opacity: 0, y: 10 }}
                  whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.96 }} onClick={() => setShowCompare(true)}
                  className="flex items-center gap-2 px-5 py-3 rounded-full font-semibold text-sm shadow-xl"
                  style={{ background: "#3ADCFF", color: "#0D0D06", boxShadow: "0 8px 28px rgba(58,220,255,0.3)" }}>
                  <GitCompare size={15} /> Compare {compareIds.length} Players
                </motion.button>
              )}
              {selectedCount > 0 && (
                <motion.button key="view-squad" initial={{ scale: 0.8, opacity: 0, y: 10 }} animate={{ scale: 1, opacity: 1, y: 0 }} exit={{ scale: 0.8, opacity: 0, y: 10 }}
                  whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.96 }} onClick={() => setShowSquadPanel(true)}
                  className="flex items-center gap-2 px-5 py-3 rounded-full font-semibold text-sm shadow-xl"
                  style={{ background: "#5FA800", color: "#fff", boxShadow: "0 8px 32px rgba(95,168,0,0.35)" }}>
                  <Users size={15} /> View Squad · {selectedCount}/11
                  {selectedCount === 11 && <CheckCircle size={14} />}
                </motion.button>
              )}
            </AnimatePresence>
            {reserveCount > 0 && (
              <button onClick={() => setShowSquadPanel(true)}
                className="text-[12px] bg-card border border-border text-muted-foreground px-3 py-1.5 rounded-full shadow-lg">
                Reserve: {reserveCount}
              </button>
            )}
          </div>

          <AnimatePresence>
            {showSquadPanel && (
              <SquadSelectionPanel
                players={players} selections={selections} opposition={opposition} format="T20I"
                onClose={() => setShowSquadPanel(false)}
                onReset={() => setSelections({})}
                onChangeSelection={setSelection}
              />
            )}
          </AnimatePresence>

          {showCompare && compareIds.length >= 2 && (
            <PlayerCompareModal
              players={players} playerIds={compareIds} opposition={opposition} selections={selections}
              onSelect={setSelection}
              onClose={() => setShowCompare(false)}
              onRemove={id => {
                const next = compareIds.filter(x => x !== id);
                setCompareIds(next);
                if (next.length < 2) setShowCompare(false);
              }}
            />
          )}
        </>
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
                    <button onClick={() => openEdit(p)} className="p-1.5 rounded hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors"><Edit size={13} /></button>
                    <button onClick={() => handleDelete(p.id)} className="p-1.5 rounded hover:bg-secondary text-muted-foreground hover:text-destructive transition-colors"><Trash2 size={13} /></button>
                  </div>
                </td>
              </motion.tr>
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

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useNavigate, useLocation } from "react-router";
import { CheckCircle, Users, GitCompare, Shield } from "lucide-react";
import { PlayerCard } from "../components/player/PlayerCard";
import { PlayerCompareModal } from "../components/player/PlayerCompareModal";
import { SquadSelectionPanel } from "../components/squad/SquadSelectionPanel";
import { useApp } from "../context/AppContext";
import * as api from "../lib/api";
import { mapApiPlayerListItem } from "../lib/mappers";
import { Player, SelectionState } from "../types/index";

export function BuildXiPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, selections, setSelections } = useApp();

  // The coach's own team is fixed to their registered country (e.g. India)
  const team = user?.country || "India";
  const [gender, setGender] = useState<"female" | "male">("female");
  const [opposition, setOpposition] = useState("Australia");
  const [players, setPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);
  const [showSquadPanel, setShowSquadPanel] = useState(false);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [showCompare, setShowCompare] = useState(false);

  const loadPlayers = () => {
    setLoading(true);
    return api.listPlayers({ limit: 100, country: team, gender, opponent: opposition })
      .then(res => setPlayers(res.players.map(mapApiPlayerListItem)))
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadPlayers(); }, [team, gender, opposition]);

  useEffect(() => {
    if ((location.state as { openSquad?: boolean } | null)?.openSquad) {
      setShowSquadPanel(true);
    }
  }, [location.state]);

  const toggleCompare = (id: string) => setCompareIds(prev =>
    prev.includes(id) ? prev.filter(x => x !== id) : prev.length < 3 ? [...prev, id] : prev
  );
  const setSelection = (id: string, s: SelectionState) =>
    setSelections(prev => ({ ...prev, [id]: s }));

  const selectedCount = Object.values(selections).filter(s => s === "select").length;

  return (
    <div className="p-5 max-w-screen-xl mx-auto pb-16">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="font-display text-2xl font-bold text-foreground">Build XI</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Draft your starting Playing XI for {team} {gender === "female" ? "Women" : "Men"} vs {opposition}
          </p>
        </div>
      </div>

      {/* Controls Bar: Fixed team badge (No India dropdown), Opponent selector & Gender selector */}
      <div className="flex gap-2 mb-4 flex-wrap items-center">
        {/* Gender Toggle */}
        <div className="flex rounded-lg border border-border overflow-hidden">
          {(["female", "male"] as const).map(g => (
            <button key={g} onClick={() => setGender(g)}
              className={`px-3 py-1.5 text-sm font-medium transition-colors ${gender === g ? "bg-[#AAFF57] text-[#0D0D06]" : "bg-secondary text-muted-foreground hover:text-foreground"}`}>
              {g === "female" ? "Women" : "Men"}
            </button>
          ))}
        </div>

        {/* Fixed Country Badge for signed-in Coach (No Team dropdown) */}
        <div className="flex items-center gap-1.5 bg-secondary border border-border rounded-lg px-3 py-1.5 text-sm font-semibold text-foreground">
          <Shield size={14} className="text-[#AAFF57]" />
          <span>{team}</span>
          <span className="text-[10px] text-muted-foreground font-normal ml-1">(Your Team)</span>
        </div>

        {/* Opponent Selector Dropdown */}
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-muted-foreground font-medium">vs</span>
          <select value={opposition} onChange={e => setOpposition(e.target.value)} title="Opponent"
            className="text-sm bg-secondary border border-border rounded-lg px-3 py-1.5 text-foreground font-medium focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
            {["Australia", "England", "South Africa", "New Zealand", "Pakistan", "Sri Lanka", "West Indies"]
              .filter(t => t.toLowerCase() !== team.toLowerCase())
              .map(t => <option key={t}>{t}</option>)}
          </select>
        </div>

        {/* Inline actions */}
        <div className="ml-auto flex items-center gap-2">
          {compareIds.length >= 2 && (
            <button onClick={() => setShowCompare(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg text-[#0D0D06]" style={{ background: "#3ADCFF" }}>
              <GitCompare size={14} /> Compare {compareIds.length}
            </button>
          )}
          {selectedCount > 0 && (
            <button onClick={() => setShowSquadPanel(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold rounded-lg text-white" style={{ background: "#5FA800" }}>
              <Users size={14} /> View Squad · {selectedCount}/11
              {selectedCount === 11 && <CheckCircle size={14} />}
            </button>
          )}
        </div>
      </div>

      {/* Instructional Banner */}
      {selectedCount === 0 && (
        <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
          className="mb-4 flex items-center gap-3 bg-[#AAFF57]/[0.08] border border-[#AAFF57]/25 rounded-2xl px-4 py-3.5">
          <div className="w-10 h-10 rounded-full bg-[#AAFF57]/15 flex items-center justify-center flex-shrink-0">
            <Users size={18} className="text-[#AAFF57]" />
          </div>
          <div>
            <p className="text-[13px] font-semibold text-foreground">Select your 11-player lineup</p>
            <p className="text-[12px] text-muted-foreground">
              Tap <span className="text-[#AAFF57] font-medium">Select</span> on players below to build your squad against <span className="text-foreground font-medium">{opposition}</span>. Click <span className="text-foreground font-medium">View Squad</span> anytime to review your Playing XI.
            </p>
          </div>
        </motion.div>
      )}

      {/* Player Grid */}
      {loading ? (
        <div className="py-16 text-center text-sm text-muted-foreground">Loading squad players…</div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {players.map((p, i) => (
            <PlayerCard
              key={p.id} player={p} index={i} opposition={opposition}
              selection={selections[p.id] ?? "undecided"}
              onSelect={s => setSelection(p.id, s)}
              comparing={compareIds.includes(p.id)}
              onToggleCompare={() => toggleCompare(p.id)}
              onViewProfile={(selectedOpposition) => navigate(`/players/${p.id}?opposition=${encodeURIComponent(selectedOpposition)}`)}
            />
          ))}
        </div>
      )}

      {/* Slide-in Squad XI Panel */}
      <AnimatePresence>
        {showSquadPanel && (
          <SquadSelectionPanel
            players={players} selections={selections} team={team} gender={gender}
            opposition={opposition} format="T20I"
            onClose={() => setShowSquadPanel(false)}
            onReset={() => setSelections({})}
            onChangeSelection={setSelection}
          />
        )}
      </AnimatePresence>

      {/* Player Compare Modal */}
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
    </div>
  );
}

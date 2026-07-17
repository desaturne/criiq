import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Search, X, Eye, Plus, Edit, Trash2 } from "lucide-react";
import { useAdminCtx } from "../context/AdminContext";
import { INITIAL_USERS } from "../../data/admin-users";
import { AppUser, Role } from "../../types/index";

export function AdminUsers() {
  const { users, setUsers } = useAdminCtx();
  const [search, setSearch] = useState("");
  const [showPanel, setShowPanel] = useState(false);
  const [editTarget, setEditTarget] = useState<AppUser | null>(null);
  const [showPassFor, setShowPassFor] = useState<number | null>(null);
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "Coach" as Role, status: "Active" as AppUser["status"], team: "" });
  const [nextId, setNextId] = useState(INITIAL_USERS.length + 1);

  const filtered = users.filter(u => u.name.toLowerCase().includes(search.toLowerCase()) || u.email.toLowerCase().includes(search.toLowerCase()));
  const openAdd  = () => { setForm({ name: "", email: "", password: "", role: "Coach", status: "Active", team: "" }); setEditTarget(null); setShowPanel(true); };
  const openEdit = (u: AppUser) => { setForm({ name: u.name, email: u.email, password: u.password, role: u.role, status: u.status, team: u.team }); setEditTarget(u); setShowPanel(true); };
  const saveUser = () => {
    if (!form.name || !form.email || !form.password) return;
    if (editTarget) {
      setUsers(prev => prev.map(u => u.id === editTarget.id ? { ...u, ...form } : u));
    } else {
      const avatar = form.name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
      setUsers(prev => [...prev, { ...form, id: nextId, lastLogin: "Just now", avatar }]);
      setNextId(n => n + 1);
    }
    setShowPanel(false);
  };

  const S = { background: "#1A1A1A", border: "1px solid #252525", color: "white" as const };
  const IC = "w-full px-3 py-2 rounded-lg text-[13px] focus:outline-none transition-all";

  return (
    <div className="p-6 max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white font-display">User Management</h1>
          <p className="text-sm mt-0.5" style={{ color: "#555" }}>{users.length} total · {users.filter(u => u.status === "Active").length} active</p>
        </div>
        <button onClick={openAdd} className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold" style={{ background: "#EF4444", color: "white", boxShadow: "0 0 16px rgba(239,68,68,0.2)" }}>
          <Plus size={14} /> Add User
        </button>
      </div>
      <div className="relative mb-4">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "#444" }} />
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by name or email…" className={IC + " pl-9"} style={S} />
      </div>
      <div className="rounded-xl overflow-hidden" style={{ background: "#151515", border: "1px solid #1E1E1E" }}>
        <table className="w-full">
          <thead>
            <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
              {["User", "Email", "Password", "Role", "Status", "Last Login", "Actions"].map(h => (
                <th key={h} className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider" style={{ color: "#444" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((u, i) => (
              <motion.tr key={u.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.04 }} style={{ borderBottom: "1px solid #1A1A1A" }}>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2.5">
                    <div className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0" style={{ background: "rgba(239,68,68,0.12)", color: "#F87171" }}>{u.avatar}</div>
                    <span className="text-[13px] font-medium text-white">{u.name}</span>
                  </div>
                </td>
                <td className="px-4 py-3 text-[12px]" style={{ color: "#777" }}>{u.email}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] font-mono" style={{ color: "#555" }}>{showPassFor === u.id ? u.password : "••••••••"}</span>
                    <button onClick={() => setShowPassFor(showPassFor === u.id ? null : u.id)} style={{ color: "#444" }}
                      onMouseEnter={e => e.currentTarget.style.color = "#888"} onMouseLeave={e => e.currentTarget.style.color = "#444"}>
                      <Eye size={12} />
                    </button>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className="text-[11px] px-2 py-0.5 rounded-full" style={{ background: u.role === "Coach" ? "rgba(59,130,246,0.1)" : "rgba(167,139,250,0.1)", color: u.role === "Coach" ? "#60A5FA" : "#A78BFA" }}>{u.role}</span>
                </td>
                <td className="px-4 py-3">
                  <button onClick={() => setUsers(prev => prev.map(x => x.id === u.id ? { ...x, status: x.status === "Active" ? "Inactive" : "Active" } : x))}
                    className="text-[11px] px-2 py-0.5 rounded-full transition-all"
                    style={{ background: u.status === "Active" ? "rgba(34,197,94,0.1)" : u.status === "Suspended" ? "rgba(239,68,68,0.1)" : "rgba(107,114,128,0.1)", color: u.status === "Active" ? "#22C55E" : u.status === "Suspended" ? "#F87171" : "#6B7280" }}>
                    {u.status}
                  </button>
                </td>
                <td className="px-4 py-3 text-[12px]" style={{ color: "#444" }}>{u.lastLogin}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1">
                    <button onClick={() => openEdit(u)} style={{ color: "#444" }} className="p-1.5 rounded-md transition-colors"
                      onMouseEnter={e => e.currentTarget.style.color = "#60A5FA"} onMouseLeave={e => e.currentTarget.style.color = "#444"}>
                      <Edit size={13} />
                    </button>
                    <button onClick={() => setUsers(prev => prev.filter(x => x.id !== u.id))} style={{ color: "#444" }} className="p-1.5 rounded-md transition-colors"
                      onMouseEnter={e => e.currentTarget.style.color = "#F87171"} onMouseLeave={e => e.currentTarget.style.color = "#444"}>
                      <Trash2 size={13} />
                    </button>
                  </div>
                </td>
              </motion.tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && <div className="py-12 text-center text-sm" style={{ color: "#444" }}>No users found</div>}
      </div>

      <AnimatePresence>
        {showPanel && (
          <motion.div className="fixed inset-0 z-50 flex" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowPanel(false)} />
            <motion.div className="relative ml-auto flex flex-col h-full shadow-2xl" style={{ width: "min(440px,95vw)", background: "#111", borderLeft: "1px solid #1E1E1E" }}
              initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ type: "spring", damping: 30, stiffness: 300 }}>
              <div className="flex items-center justify-between px-6 py-5 flex-shrink-0" style={{ borderBottom: "1px solid #1E1E1E" }}>
                <div>
                  <h2 className="text-lg font-bold text-white">{editTarget ? "Edit User" : "Add New User"}</h2>
                  <p className="text-[12px] mt-0.5" style={{ color: "#555" }}>{editTarget ? "Update credentials and role" : "Create a new platform user"}</p>
                </div>
                <button onClick={() => setShowPanel(false)} className="p-2 rounded-lg" style={{ color: "#555" }}><X size={16} /></button>
              </div>
              <div className="flex-1 overflow-auto p-6 space-y-4">
                {[
                  { label: "Full Name", key: "name",     type: "text",  ph: "John Smith" },
                  { label: "Email",     key: "email",    type: "email", ph: "john@teamcricket.com" },
                  { label: "Password",  key: "password", type: "text",  ph: "Min. 8 characters" },
                  { label: "Team",      key: "team",     type: "text",  ph: "India A" },
                ].map(f => (
                  <div key={f.key} className="space-y-1.5">
                    <label className="text-[13px] font-medium" style={{ color: "#888" }}>{f.label}</label>
                    <input type={f.type} placeholder={f.ph} value={(form as any)[f.key]}
                      onChange={e => setForm(p => ({ ...p, [f.key]: e.target.value }))}
                      className={IC} style={S} />
                  </div>
                ))}
                <div className="space-y-1.5">
                  <label className="text-[13px] font-medium" style={{ color: "#888" }}>Role</label>
                  <select value={form.role} onChange={e => setForm(p => ({ ...p, role: e.target.value as Role }))} className={IC} style={S}>
                    <option value="Coach">Coach</option>
                    <option value="Player">Player</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-[13px] font-medium" style={{ color: "#888" }}>Status</label>
                  <select value={form.status} onChange={e => setForm(p => ({ ...p, status: e.target.value as AppUser["status"] }))} className={IC} style={S}>
                    <option value="Active">Active</option>
                    <option value="Inactive">Inactive</option>
                    <option value="Suspended">Suspended</option>
                  </select>
                </div>
              </div>
              <div className="px-6 py-5 flex gap-3 flex-shrink-0" style={{ borderTop: "1px solid #1E1E1E" }}>
                <button onClick={() => setShowPanel(false)} className="flex-1 py-2.5 rounded-lg text-sm font-medium" style={{ background: "#1A1A1A", color: "#888", border: "1px solid #252525" }}>Cancel</button>
                <button onClick={saveUser} className="flex-1 py-2.5 rounded-lg text-sm font-semibold" style={{ background: "#EF4444", color: "white" }}>
                  {editTarget ? "Save Changes" : "Create User"}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

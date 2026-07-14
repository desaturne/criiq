import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { LayoutDashboard, Users, LogOut, Shield, Activity, Server } from "lucide-react";
import { AdminContext } from "./context/AdminContext";
import { AdminActivity } from "./pages/AdminActivity";
import { AdminOverview } from "./pages/AdminOverview";
import { AdminRoles } from "./pages/AdminRoles";
import { AdminSystem } from "./pages/AdminSystem";
import { AdminUsers } from "./pages/AdminUsers";
import { INITIAL_USERS } from "../data/admin-users";
import { AppUser } from "../types/index";

export function AdminShell({ onLogout }: { onLogout: () => void }) {
  const [users, setUsers] = useState<AppUser[]>(INITIAL_USERS);
  const [section, setSection] = useState<"overview" | "users" | "roles" | "system" | "activity">("overview");

  const nav = [
    { id: "overview", label: "Overview",    icon: LayoutDashboard },
    { id: "users",    label: "Users",        icon: Users },
    { id: "roles",    label: "Roles",        icon: Shield },
    { id: "system",   label: "System",       icon: Server },
    { id: "activity", label: "Activity Log", icon: Activity },
  ] as const;

  return (
    <AdminContext.Provider value={{ users, setUsers }}>
      <div className="h-screen flex flex-col" style={{ fontFamily: "var(--font-sans)", background: "#0C0C0C" }}>
        <header className="h-12 flex-shrink-0 flex items-center px-4 gap-3 z-30" style={{ background: "#111", borderBottom: "1px solid #1E1E1E" }}>
          <div className="flex items-center gap-2">
            <Shield size={15} className="text-red-500" />
            <span className="font-display font-bold text-base text-white tracking-wider">CRIIQ</span>
            <span className="text-[10px] font-medium px-2 py-0.5 rounded-full tracking-widest uppercase" style={{ background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.2)", color: "#F87171" }}>ADMIN</span>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-[11px]" style={{ color: "#555" }}>
              <div className="w-1.5 h-1.5 rounded-full bg-green-500" /> System operational
            </span>
            <div className="w-px h-4" style={{ background: "#222" }} />
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold" style={{ background: "rgba(239,68,68,0.15)", color: "#EF4444" }}>SA</div>
              <span className="text-[12px] text-white hidden sm:block">Super Admin</span>
            </div>
            <button onClick={onLogout} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] transition-colors" style={{ color: "#888", background: "#1A1A1A", border: "1px solid #2A2A2A" }}
              onMouseEnter={e => { e.currentTarget.style.color = "#F87171"; e.currentTarget.style.borderColor = "#3A2020"; }}
              onMouseLeave={e => { e.currentTarget.style.color = "#888"; e.currentTarget.style.borderColor = "#2A2A2A"; }}>
              <LogOut size={12} /> Logout
            </button>
          </div>
        </header>
        <div className="flex flex-1 overflow-hidden">
          <aside className="w-52 flex-shrink-0 flex flex-col" style={{ background: "#111", borderRight: "1px solid #1E1E1E" }}>
            <div className="p-3 space-y-0.5 flex-1 overflow-auto">
              {nav.map(item => {
                const Icon = item.icon;
                const active = section === item.id;
                return (
                  <button key={item.id} onClick={() => setSection(item.id)}
                    className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-[13px] transition-all text-left"
                    style={{ background: active ? "rgba(239,68,68,0.1)" : "transparent", color: active ? "#F87171" : "#666", border: active ? "1px solid rgba(239,68,68,0.15)" : "1px solid transparent" }}>
                    <Icon size={14} /> {item.label}
                  </button>
                );
              })}
            </div>
            <div className="p-3" style={{ borderTop: "1px solid #1E1E1E" }}>
              <div className="px-3 py-2 rounded-lg text-[11px]" style={{ background: "#1A1A1A" }}>
                <div className="font-medium mb-0.5" style={{ color: "#666" }}>Logged in as</div>
                <div style={{ color: "#F87171" }}>admin@criiq.in</div>
              </div>
            </div>
          </aside>
          <main className="flex-1 overflow-auto" style={{ background: "#0C0C0C", scrollbarWidth: "thin", scrollbarColor: "#222 transparent" }}>
            <AnimatePresence mode="wait">
              <motion.div key={section} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
                {section === "overview" && <AdminOverview />}
                {section === "users"    && <AdminUsers />}
                {section === "roles"    && <AdminRoles />}
                {section === "system"   && <AdminSystem />}
                {section === "activity" && <AdminActivity />}
              </motion.div>
            </AnimatePresence>
          </main>
        </div>
      </div>
    </AdminContext.Provider>
  );
}

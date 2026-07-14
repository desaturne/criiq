import { motion } from "motion/react";
import { Shield } from "lucide-react";
import { useAdminCtx } from "../context/AdminContext";

export function AdminRoles() {
  const { users } = useAdminCtx();
  const defs = [
    { role: "Coach",  color: "#3B82F6", desc: "Access to player data, squad selection, match analytics, and AI tools.", perms: ["Player profiles", "Squad selection", "Match analytics", "AI recommendations", "Reports"] },
    { role: "Player", color: "#A78BFA", desc: "Read-only access to personal stats, form data, and match schedules.", perms: ["Own profile", "Match schedule", "Personal stats"] },
  ];
  return (
    <div className="p-6 max-w-4xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white font-display">Roles & Permissions</h1>
        <p className="text-sm mt-0.5" style={{ color: "#555" }}>Platform access control for all user types</p>
      </div>
      <div className="grid gap-4">
        {defs.map((r, i) => (
          <motion.div key={r.role} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.1 }}
            className="rounded-xl p-5" style={{ background: "#151515", border: "1px solid #1E1E1E" }}>
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: r.color + "18" }}>
                  <Shield size={16} style={{ color: r.color }} />
                </div>
                <div>
                  <h3 className="text-[15px] font-bold text-white">{r.role}</h3>
                  <p className="text-[12px] mt-0.5" style={{ color: "#555" }}>{r.desc}</p>
                </div>
              </div>
              <span className="text-[12px]" style={{ color: "#444" }}>{users.filter(u => u.role === r.role).length} users</span>
            </div>
            <div className="flex flex-wrap gap-2 mt-3">
              {r.perms.map(p => (
                <span key={p} className="text-[11px] px-2.5 py-1 rounded-full" style={{ background: r.color + "10", color: r.color + "CC", border: "1px solid " + r.color + "20" }}>{p}</span>
              ))}
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

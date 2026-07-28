import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { Users, CheckCircle, User, Activity, CircleCheckBig, CircleX } from "lucide-react";
import { useAdminCtx } from "../context/AdminContext";
import * as api from "../../lib/api";

export function AdminOverview() {
  const { users } = useAdminCtx();
  const [pending, setPending] = useState<{ id: number; name: string; email: string; country: string; status: string }[]>([]);
  const [pendingError, setPendingError] = useState<string | null>(null);
  const [reviewingId, setReviewingId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.pendingCoachRegistrations()
      .then(rows => { if (!cancelled) setPending(rows); })
      .catch(err => { if (!cancelled) setPendingError(err instanceof Error ? err.message : "Could not load pending coach approvals"); });
    return () => { cancelled = true; };
  }, []);

  const review = async (id: number, status: "Active" | "Suspended") => {
    setReviewingId(id);
    setPendingError(null);
    try {
      await api.reviewCoachRegistration(id, status);
      setPending(prev => prev.filter(item => item.id !== id));
    } catch (err) {
      setPendingError(err instanceof Error ? err.message : "Could not update the registration");
    } finally {
      setReviewingId(null);
    }
  };

  const stats = [
    { label: "Total Users", val: users.length,                                         color: "#EF4444", icon: Users },
    { label: "Active",       val: users.filter(u => u.status === "Active").length,      color: "#22C55E", icon: CheckCircle },
    { label: "Coaches",      val: users.filter(u => u.role === "Coach").length,         color: "#3B82F6", icon: User },
    { label: "Players",      val: users.filter(u => u.role === "Player").length,        color: "#A78BFA", icon: Activity },
  ];
  return (
    <div className="p-6 max-w-5xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white font-display">Admin Overview</h1>
        <p className="text-sm mt-0.5" style={{ color: "#555" }}>Platform health and user statistics</p>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {stats.map((s, i) => {
          const Icon = s.icon;
          return (
            <motion.div key={s.label} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.07 }}
              className="rounded-xl p-5" style={{ background: "#151515", border: "1px solid #1E1E1E" }}>
              <div className="w-8 h-8 rounded-lg flex items-center justify-center mb-3" style={{ background: s.color + "18" }}>
                <Icon size={15} style={{ color: s.color }} />
              </div>
              <div className="text-2xl font-bold text-white font-display">{s.val}</div>
              <div className="text-[12px] mt-0.5" style={{ color: "#555" }}>{s.label}</div>
            </motion.div>
          );
        })}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-xl p-5" style={{ background: "#151515", border: "1px solid #1E1E1E" }}>
          <h3 className="text-[14px] font-semibold text-white mb-4">Recent Users</h3>
          <div className="space-y-3">
            {users.slice(0, 5).map(u => (
              <div key={u.id} className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0" style={{ background: "rgba(239,68,68,0.12)", color: "#F87171" }}>{u.avatar}</div>
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] font-medium text-white truncate">{u.name}</div>
                  <div className="text-[11px] truncate" style={{ color: "#555" }}>{u.email}</div>
                </div>
                <span className="text-[10px] px-2 py-0.5 rounded-full flex-shrink-0" style={{ background: u.status === "Active" ? "rgba(34,197,94,0.1)" : "rgba(239,68,68,0.1)", color: u.status === "Active" ? "#22C55E" : "#F87171" }}>{u.status}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-xl p-5" style={{ background: "#151515", border: "1px solid #1E1E1E" }}>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-[14px] font-semibold text-white">Pending Coach Approvals</h3>
            <span className="text-[11px] px-2 py-0.5 rounded-full" style={{ background: "rgba(59,130,246,0.12)", color: "#60A5FA" }}>{pending.length} waiting</span>
          </div>
          {pendingError && <div className="mb-3 text-[12px] text-red-400">{pendingError}</div>}
          <div className="space-y-3">
            {pending.length === 0 ? (
              <div className="text-[12px]" style={{ color: "#555" }}>No coach registrations awaiting review.</div>
            ) : pending.map(item => (
              <div key={item.id} className="rounded-lg p-3" style={{ background: "#111", border: "1px solid #1E1E1E" }}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-[13px] font-medium text-white truncate">{item.name}</div>
                    <div className="text-[11px] truncate" style={{ color: "#666" }}>{item.email}</div>
                    <div className="text-[11px] mt-1" style={{ color: "#888" }}>{item.country} · Coach · {item.status}</div>
                  </div>
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    <button onClick={() => review(item.id, "Active")} disabled={reviewingId === item.id}
                      className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[11px] font-medium disabled:opacity-60"
                      style={{ background: "rgba(34,197,94,0.12)", color: "#22C55E" }}>
                      <CircleCheckBig size={12} /> Approve
                    </button>
                    <button onClick={() => review(item.id, "Suspended")} disabled={reviewingId === item.id}
                      className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[11px] font-medium disabled:opacity-60"
                      style={{ background: "rgba(239,68,68,0.12)", color: "#F87171" }}>
                      <CircleX size={12} /> Reject
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-xl p-5" style={{ background: "#151515", border: "1px solid #1E1E1E" }}>
          <h3 className="text-[14px] font-semibold text-white mb-4">System Health</h3>
          {[{ label: "API Response", val: 98, color: "#22C55E" }, { label: "DB Performance", val: 95, color: "#22C55E" }, { label: "Storage Used", val: 42, color: "#EAB308" }, { label: "Memory", val: 67, color: "#3B82F6" }].map(h => (
            <div key={h.label} className="mb-3">
              <div className="flex justify-between text-[12px] mb-1">
                <span style={{ color: "#888" }}>{h.label}</span>
                <span style={{ color: h.color }}>{h.val}%</span>
              </div>
              <div className="h-1.5 rounded-full" style={{ background: "#222" }}>
                <motion.div initial={{ width: 0 }} animate={{ width: h.val + "%" }} transition={{ duration: 1, delay: 0.3 }} className="h-full rounded-full" style={{ background: h.color }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

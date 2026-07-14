import { motion } from "motion/react";

export function AdminSystem() {
  const metrics = [
    { label: "API Latency",     val: "42ms", status: "good",    note: "↓ 8% from yesterday" },
    { label: "DB Query Time",   val: "12ms", status: "good",    note: "Optimal performance" },
    { label: "Storage Used",    val: "42%",  status: "warning", note: "108 GB / 256 GB" },
    { label: "Memory",          val: "67%",  status: "ok",      note: "5.4 GB / 8 GB" },
    { label: "Active Sessions", val: "7",    status: "good",    note: "Peak: 24 today" },
    { label: "Error Rate",      val: "0.2%", status: "good",    note: "Within threshold" },
  ];
  const sc = { good: "#22C55E", ok: "#3B82F6", warning: "#EAB308" };
  return (
    <div className="p-6 max-w-4xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white font-display">System Health</h1>
        <p className="text-sm mt-0.5" style={{ color: "#555" }}>Real-time platform monitoring</p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {metrics.map((m, i) => (
          <motion.div key={m.label} initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * 0.06 }}
            className="rounded-xl p-5" style={{ background: "#151515", border: "1px solid #1E1E1E" }}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-[12px]" style={{ color: "#555" }}>{m.label}</span>
              <div className="w-2 h-2 rounded-full" style={{ background: sc[m.status as keyof typeof sc] }} />
            </div>
            <div className="text-2xl font-bold font-display" style={{ color: sc[m.status as keyof typeof sc] }}>{m.val}</div>
            <div className="text-[11px] mt-1" style={{ color: "#444" }}>{m.note}</div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

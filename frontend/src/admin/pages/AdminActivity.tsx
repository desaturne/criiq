import { motion } from "motion/react";

export function AdminActivity() {
  const logs = [
    { time: "14:32", user: "admin@criiq.in",          action: "User created",   detail: "priya@teamcricket.com added with Player role",    type: "create"  },
    { time: "13:18", user: "rahul@teamcricket.com",   action: "Login",          detail: "Successful login from 192.168.1.42",               type: "auth"    },
    { time: "12:05", user: "admin@criiq.in",          action: "Role changed",   detail: "vikram@teamcricket.com → Coach",                   type: "edit"    },
    { time: "11:44", user: "aisha@teamcricket.com",   action: "Login failed",   detail: "3 failed attempts — account suspended",            type: "warning" },
    { time: "10:22", user: "admin@criiq.in",          action: "User suspended", detail: "aisha@teamcricket.com suspended",                  type: "warning" },
    { time: "09:15", user: "rajan@teamcricket.com",   action: "Password reset", detail: "Self-service reset completed",                     type: "auth"    },
    { time: "08:50", user: "admin@criiq.in",          action: "System backup",  detail: "Automated backup completed successfully",          type: "system"  },
  ];
  const tc = { create: "#22C55E", auth: "#3B82F6", edit: "#EAB308", warning: "#EF4444", system: "#A78BFA" };
  return (
    <div className="p-6 max-w-4xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white font-display">Activity Log</h1>
        <p className="text-sm mt-0.5" style={{ color: "#555" }}>All admin and user actions — today</p>
      </div>
      <div className="rounded-xl overflow-hidden" style={{ background: "#151515", border: "1px solid #1E1E1E" }}>
        {logs.map((l, i) => (
          <motion.div key={i} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }}
            className="flex items-start gap-4 px-5 py-4" style={{ borderBottom: i < logs.length - 1 ? "1px solid #1A1A1A" : "none" }}>
            <div className="text-[11px] font-mono flex-shrink-0 mt-0.5" style={{ color: "#444", minWidth: 36 }}>{l.time}</div>
            <div className="w-2 h-2 rounded-full flex-shrink-0 mt-1.5" style={{ background: tc[l.type as keyof typeof tc] }} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                <span className="text-[13px] font-medium text-white">{l.action}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: tc[l.type as keyof typeof tc] + "15", color: tc[l.type as keyof typeof tc] }}>{l.type}</span>
              </div>
              <div className="text-[12px]" style={{ color: "#555" }}>{l.detail}</div>
              <div className="text-[11px] mt-0.5" style={{ color: "#3A3A3A" }}>{l.user}</div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

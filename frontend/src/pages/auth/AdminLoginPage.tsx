import React, { useState } from "react";
import { motion } from "motion/react";
import { ChevronLeft, XCircle, Eye, Lock, RefreshCw, Shield, Mail } from "lucide-react";
import { ADMIN_CREDENTIALS, INITIAL_USERS } from "../../data/admin-users";

export function AdminLoginPage({ onLogin, onBack }: { onLogin: () => void; onBack: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [shake, setShake] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (email === ADMIN_CREDENTIALS.email && password === ADMIN_CREDENTIALS.password) {
      setLoading(true);
      setTimeout(onLogin, 1000);
    } else {
      setError("Invalid admin credentials. Access denied.");
      setShake(true);
      setTimeout(() => setShake(false), 600);
    }
  };

  return (
    <div className="min-h-screen flex bg-[#0A0A0A]" style={{ fontFamily: "var(--font-sans)" }}>
      <div className="hidden lg:flex w-[48%] flex-col relative overflow-hidden" style={{ background: "linear-gradient(135deg, #0D0D0D 0%, #1A0A0A 60%, #0D0505 100%)" }}>
        <div className="absolute inset-0" style={{ backgroundImage: "radial-gradient(rgba(239,68,68,0.07) 1px, transparent 1px)", backgroundSize: "28px 28px" }} />
        <svg className="absolute inset-0 w-full h-full opacity-10" preserveAspectRatio="none">
          <path d="M0 400 Q200 350, 400 380 T800 360" stroke="#EF4444" strokeWidth="1" fill="none" />
          <path d="M100 0 Q80 300, 120 600 T100 1000" stroke="#DC2626" strokeWidth="1.5" fill="none" />
        </svg>
        <div className="relative z-10 flex flex-col h-full p-12 justify-between">
          <div className="flex items-center gap-2">
            <Shield size={20} className="text-red-500" />
            <span className="font-display font-bold text-xl text-white tracking-widest uppercase">CRIIQ Admin</span>
          </div>
          <div>
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full mb-6" style={{ background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.25)" }}>
              <div className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
              <span className="text-[11px] font-medium text-red-400 tracking-wider uppercase">Restricted Access</span>
            </div>
            <h1 className="font-display text-4xl font-bold text-white leading-tight mb-4">
              System<br /><em className="text-red-500 not-italic">Command</em><br />Centre
            </h1>
            <p className="text-sm leading-relaxed max-w-xs" style={{ color: "#6B6060" }}>
              Authorised personnel only. This portal manages all user accounts, roles, and system configuration.
            </p>
            <div className="mt-10 grid grid-cols-3 gap-6">
              {[{ val: String(INITIAL_USERS.filter(u => u.status === "Active").length), label: "Active users" }, { val: "3", label: "Teams" }, { val: "100%", label: "Uptime" }].map(s => (
                <div key={s.label}>
                  <div className="font-display text-2xl font-bold text-red-400">{s.val}</div>
                  <div className="text-[11px] mt-0.5" style={{ color: "#5A4A4A" }}>{s.label}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="text-[11px]" style={{ color: "#3A2A2A" }}>Criiq Admin Portal · Confidential</div>
        </div>
      </div>

      <div className="flex-1 flex items-center justify-center p-8" style={{ background: "#111111" }}>
        <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.4 }} className="w-full max-w-sm">
          <button onClick={onBack} className="flex items-center gap-1.5 text-[12px] mb-8 transition-colors" style={{ color: "#555" }}
            onMouseEnter={e => e.currentTarget.style.color = "#888"} onMouseLeave={e => e.currentTarget.style.color = "#555"}>
            <ChevronLeft size={14} /> Back to user login
          </button>
          <div className="mb-8">
            <div className="w-12 h-12 rounded-xl flex items-center justify-center mb-4" style={{ background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.2)" }}>
              <Shield size={22} className="text-red-500" />
            </div>
            <h2 className="font-display text-3xl font-bold text-white">Admin Sign in</h2>
            <p className="text-sm mt-1" style={{ color: "#555" }}>Enter your administrator credentials</p>
          </div>
          <motion.form onSubmit={handleSubmit} animate={shake ? { x: [0, -8, 8, -8, 8, 0] } : {}} transition={{ duration: 0.4 }} className="space-y-4">
            {[
              { label: "Admin Email", type: "email", val: email, set: setEmail, ph: "admin@criiq.in", icon: Mail },
            ].map(f => (
              <div key={f.label} className="space-y-1.5">
                <label className="text-[13px] font-medium" style={{ color: "#888" }}>{f.label}</label>
                <div className="relative">
                  <f.icon size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "#444" }} />
                  <input type={f.type} value={f.val} onChange={e => f.set(e.target.value)} placeholder={f.ph}
                    className="w-full pl-9 pr-4 py-2.5 text-sm rounded-lg focus:outline-none transition-all text-white placeholder:text-[#3A3A3A]"
                    style={{ background: "#1A1A1A", border: "1px solid #252525" }}
                    onFocus={e => { e.target.style.borderColor = "#EF4444"; e.target.style.boxShadow = "0 0 0 3px rgba(239,68,68,0.1)"; }}
                    onBlur={e => { e.target.style.borderColor = "#252525"; e.target.style.boxShadow = "none"; }} />
                </div>
              </div>
            ))}
            <div className="space-y-1.5">
              <label className="text-[13px] font-medium" style={{ color: "#888" }}>Password</label>
              <div className="relative">
                <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "#444" }} />
                <input type={showPass ? "text" : "password"} value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••"
                  className="w-full pl-9 pr-10 py-2.5 text-sm rounded-lg focus:outline-none transition-all text-white placeholder:text-[#3A3A3A]"
                  style={{ background: "#1A1A1A", border: "1px solid #252525" }}
                  onFocus={e => { e.target.style.borderColor = "#EF4444"; e.target.style.boxShadow = "0 0 0 3px rgba(239,68,68,0.1)"; }}
                  onBlur={e => { e.target.style.borderColor = "#252525"; e.target.style.boxShadow = "none"; }} />
                <button type="button" onClick={() => setShowPass(!showPass)} className="absolute right-3 top-1/2 -translate-y-1/2" style={{ color: "#444" }}>
                  <Eye size={14} />
                </button>
              </div>
            </div>
            {error && (
              <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }}
                className="flex items-center gap-2 px-3 py-2.5 rounded-lg text-[12px]"
                style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", color: "#F87171" }}>
                <XCircle size={13} /> {error}
              </motion.div>
            )}
            <button type="submit" disabled={loading}
              className="w-full py-2.5 text-sm font-semibold rounded-lg transition-all flex items-center justify-center gap-2 disabled:opacity-60"
              style={{ background: "#EF4444", color: "white", boxShadow: "0 0 20px rgba(239,68,68,0.2)" }}>
              {loading ? <><RefreshCw size={14} className="animate-spin" /> Authenticating…</> : <><Shield size={14} /> Access Admin Portal</>}
            </button>
          </motion.form>
          <p className="mt-6 text-center text-[11px]" style={{ color: "#333" }}>Unauthorised access attempts are logged and reported</p>
        </motion.div>
      </div>
    </div>
  );
}

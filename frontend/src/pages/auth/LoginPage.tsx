import React, { useState } from "react";
import { motion } from "motion/react";
import { Lock, RefreshCw, Mail } from "lucide-react";
import { CricketBall } from "../../components/common/CricketBall";

export function LoginPage({ onLogin, onAdminAccess }: { onLogin: () => void; onAdminAccess?: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [shake, setShake] = useState(false);
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) { setShake(true); setTimeout(() => setShake(false), 600); return; }
    setLoading(true);
    setTimeout(onLogin, 1200);
  };
  return (
    <div className="min-h-screen flex">
      {/* Left branded panel */}
      <div className="hidden lg:flex w-[52%] flex-col relative bg-[#111110] overflow-hidden">
        {/* Grid dot texture */}
        <div className="absolute inset-0" style={{ backgroundImage: "radial-gradient(rgba(170,255,87,0.12) 1px, transparent 1px)", backgroundSize: "24px 24px" }} />
        {/* Animated seam lines */}
        <svg className="absolute inset-0 w-full h-full" style={{ opacity: 0.08 }} preserveAspectRatio="none">
          <style>{`
            @keyframes drawSeam { from { stroke-dashoffset: 3000; } to { stroke-dashoffset: 0; } }
            .s1 { stroke-dasharray: 3000; animation: drawSeam 4s ease-in-out forwards 0.5s; }
            .s2 { stroke-dasharray: 3000; animation: drawSeam 4s ease-in-out forwards 1s; }
            .s3 { stroke-dasharray: 3000; animation: drawSeam 4s ease-in-out forwards 1.5s; }
          `}</style>
          <path className="s1" d="M150 -50 C120 200, 280 350, 200 600 S80 820 160 1050" stroke="#AAFF57" strokeWidth="2.5" fill="none" />
          <path className="s2" d="M380 -80 C350 200, 500 380, 430 650 S290 880 380 1100" stroke="#AAFF57" strokeWidth="1.5" fill="none" />
          <path className="s3" d="M -50 200 C 150 170, 350 260, 580 200 S 820 120, 1050 180" stroke="white" strokeWidth="1.2" fill="none" />
        </svg>
        {/* Content */}
        <div className="relative z-10 flex flex-col h-full p-12 justify-between">
          <div className="flex items-center gap-2">
            <CricketBall size={22} className="text-[#AAFF57]" />
            <span className="font-display font-bold text-2xl text-white tracking-tight">CRIIQ</span>
          </div>
          <div>
            <motion.div initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.3 }}>
              <h1 className="font-display text-5xl font-bold text-white leading-tight mb-4">
                Data-driven<br /><em className="text-[#AAFF57] not-italic">selection.</em><br />Decisive wins.
              </h1>
              <p className="text-[#8A8970] text-base leading-relaxed max-w-sm">
                The analytics platform trusted by elite coaches to pick the right eleven — every time. Form, matchups, and AI intelligence in one place.
              </p>
            </motion.div>
            {/* Live stat row */}
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 1 }}
              className="mt-10 flex gap-8">
              {[{ val: "287+", label: "Players tracked" }, { val: "94%", label: "Prediction accuracy" }, { val: "12", label: "Teams onboarded" }].map(s => (
                <div key={s.label}>
                  <div className="font-display text-2xl font-bold text-[#AAFF57]">{s.val}</div>
                  <div className="text-[11px] text-[#6B6A5A] mt-0.5">{s.label}</div>
                </div>
              ))}
            </motion.div>
          </div>
          <div className="text-[11px] text-[#4A4A3A]">© 2025 Criiq Analytics. All rights reserved.</div>
        </div>
      </div>

      {/* Right form panel */}
      <div className="flex-1 flex items-center justify-center p-8 bg-background">
        <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.5, delay: 0.2 }}
          className="w-full max-w-sm">
          <div className="mb-8">
            <h2 className="font-display text-3xl font-bold text-foreground">Sign in</h2>
            <p className="text-muted-foreground text-sm mt-1">Access your coaching dashboard</p>
          </div>
          <motion.form onSubmit={handleSubmit} animate={shake ? { x: [0, -8, 8, -8, 8, 0] } : {}} transition={{ duration: 0.4 }} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-[13px] font-medium text-foreground">Email</label>
              <div className="relative">
                <Mail size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="coach@teamcricket.com"
                  className="w-full pl-9 pr-4 py-2.5 text-sm bg-input-background border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40 focus:border-[#AAFF57] text-foreground placeholder:text-muted-foreground transition-all" />
              </div>
            </div>
            <div className="space-y-1.5">
              <label className="text-[13px] font-medium text-foreground">Password</label>
              <div className="relative">
                <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••"
                  className="w-full pl-9 pr-4 py-2.5 text-sm bg-input-background border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40 focus:border-[#AAFF57] text-foreground placeholder:text-muted-foreground transition-all" />
              </div>
            </div>
            <div className="flex items-center justify-between text-[12px]">
              <label className="flex items-center gap-2 text-muted-foreground cursor-pointer">
                <input type="checkbox" className="rounded" /> Remember me
              </label>
              <button type="button" className="text-[#AAFF57] hover:underline">Forgot password?</button>
            </div>
            <button type="submit" disabled={loading}
              className="w-full py-2.5 bg-[#AAFF57] text-[#0D0D06] text-sm font-semibold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all flex items-center justify-center gap-2 disabled:opacity-60">
              {loading ? <><RefreshCw size={14} className="animate-spin" /> Signing in…</> : "Sign in"}
            </button>
          </motion.form>
          <p className="text-center text-[12px] text-muted-foreground mt-6">
            No account? <button className="text-[#AAFF57] hover:underline">Request access</button>
          </p>
          {onAdminAccess && (
            <p className="text-center text-[11px] text-muted-foreground/60 mt-3">
              <button type="button" onClick={onAdminAccess} className="hover:text-muted-foreground hover:underline transition-colors">
                Admin access
              </button>
            </p>
          )}
        </motion.div>
      </div>
    </div>
  );
}

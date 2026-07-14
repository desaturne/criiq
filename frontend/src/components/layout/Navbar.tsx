import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useNavigate } from "react-router";
import { Settings, Bell, ChevronDown, Moon, Sun, Menu, LogOut, User } from "lucide-react";
import { CricketBall } from "../common/CricketBall";
import { useApp } from "../../context/AppContext";

export function Navbar({ sidebarOpen, setSidebarOpen, onLogout }: { sidebarOpen: boolean; setSidebarOpen: (v: boolean) => void; onLogout: () => void }) {
  const { dark, setDark } = useApp();
  const navigate = useNavigate();
  const [userOpen, setUserOpen] = useState(false);
  return (
    <header className="h-12 flex-shrink-0 border-b border-border flex items-center px-3 gap-3 bg-sidebar z-30">
      <button onClick={() => setSidebarOpen(!sidebarOpen)} className="p-1.5 rounded hover:bg-sidebar-accent transition-colors text-muted-foreground hover:text-foreground">
        <Menu size={16} />
      </button>
      <button onClick={() => navigate("/dashboard")} className="flex items-center gap-2 font-display font-bold text-lg tracking-tight text-foreground">
        <CricketBall size={16} className="text-[#AAFF57]" />
        CRIIQ
      </button>
      <div className="ml-auto flex items-center gap-2">
        <button onClick={() => setDark(!dark)} className="p-1.5 rounded hover:bg-sidebar-accent text-muted-foreground hover:text-foreground transition-colors">
          {dark ? <Sun size={15} /> : <Moon size={15} />}
        </button>
        <button className="relative p-1.5 rounded hover:bg-sidebar-accent text-muted-foreground hover:text-foreground transition-colors">
          <Bell size={15} />
          <span className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-[#AAFF57]" />
        </button>
        <div className="relative">
          <button onClick={() => setUserOpen(!userOpen)} className="flex items-center gap-2 pl-2 pr-1 py-1 rounded hover:bg-sidebar-accent transition-colors">
            <div className="w-6 h-6 rounded-full bg-[#AAFF57] flex items-center justify-center text-[10px] font-bold text-[#0D0D06]">RC</div>
            <div className="hidden sm:flex flex-col items-start">
              <span className="text-[12px] font-medium text-foreground leading-tight">Rahul Coach</span>
              <span className="text-[10px] px-1.5 rounded-full leading-tight bg-blue-500/20 text-blue-400">Coach</span>
            </div>
            <ChevronDown size={12} className="text-muted-foreground" />
          </button>
          <AnimatePresence>
            {userOpen && (
              <motion.div initial={{ opacity: 0, y: -6, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6, scale: 0.96 }} transition={{ duration: 0.15 }}
                className="absolute right-0 top-full mt-1 w-44 bg-card border border-border rounded-lg shadow-xl overflow-hidden z-50">
                {[{ icon: User, label: "Profile", action: () => { navigate("/profile"); setUserOpen(false); } }, { icon: Settings, label: "Settings", action: () => { navigate("/settings"); setUserOpen(false); } }].map(item => (
                  <button key={item.label} onClick={item.action} className="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] hover:bg-secondary transition-colors text-foreground">
                    <item.icon size={13} className="text-muted-foreground" /> {item.label}
                  </button>
                ))}
                <div className="border-t border-border" />
                <button onClick={() => { setUserOpen(false); onLogout(); }} className="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] hover:bg-secondary transition-colors text-destructive">
                  <LogOut size={13} /> Logout
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </header>
  );
}

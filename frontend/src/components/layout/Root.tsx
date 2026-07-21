import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Outlet, useNavigate, useLocation } from "react-router";
import { LayoutDashboard, Calendar, Star, Activity } from "lucide-react";
import { Navbar } from "./Navbar";
import { Sidebar } from "./Sidebar";
import { useApp } from "../../context/AppContext";

export function Root() {
  const { dark } = useApp();
  const [sidebarOpen, setSidebarOpen] = useState(() => typeof window !== "undefined" ? window.innerWidth > 768 : true);
  const location = useLocation();
  const navigate = useNavigate();
  const activePath = location.pathname.replace(/^\//, "") || "dashboard";

  const mobileNavItems = [
    { path: "dashboard",       label: "Home",    icon: LayoutDashboard },
    { path: "players",         label: "Players", icon: Activity },
    { path: "matches",         label: "Matches", icon: Calendar },
    { path: "recommendations", label: "Picks",   icon: Star },
  ];

  return (
    <div className={`${dark ? "dark" : ""} h-screen`} style={{ fontFamily: "var(--font-sans)" }}>
      <div className="bg-background text-foreground h-full flex flex-col overflow-hidden">
        <Navbar sidebarOpen={sidebarOpen} setSidebarOpen={setSidebarOpen} />
        <div className="flex flex-1 overflow-hidden">
          <Sidebar open={sidebarOpen} />
          <div className="flex flex-col flex-1 overflow-hidden">
            <main className="flex-1 overflow-auto pb-16 sm:pb-0" style={{ scrollbarWidth: "thin", scrollbarColor: "var(--border) transparent" }}>
              <AnimatePresence mode="wait">
                <motion.div key={location.pathname} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.18 }} className="h-full">
                  <Outlet />
                </motion.div>
              </AnimatePresence>
            </main>
          </div>
        </div>
        {/* Mobile bottom nav */}
        <div className="sm:hidden fixed bottom-0 left-0 right-0 z-40 bg-sidebar border-t border-border flex">
          {mobileNavItems.map(item => {
            const Icon = item.icon;
            const active = activePath === item.path || activePath.startsWith(item.path + "/");
            return (
              <button key={item.path} onClick={() => navigate("/" + item.path)}
                className={`flex-1 flex flex-col items-center justify-center py-2 gap-0.5 text-[10px] font-medium transition-colors ${active ? "text-[#AAFF57]" : "text-muted-foreground"}`}>
                <Icon size={18} />
                {item.label}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

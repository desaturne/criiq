import { motion, AnimatePresence } from "motion/react";
import { useNavigate, useLocation } from "react-router";
import { Settings } from "lucide-react";
import { NAV_ITEMS } from "../../data/nav";

export function Sidebar({ open }: { open: boolean }) {
  const navigate = useNavigate();
  const location = useLocation();
  const activePath = location.pathname.replace(/^\//, "") || "dashboard";
  return (
    <AnimatePresence>
      {open && (
        <motion.aside initial={{ width: 0, opacity: 0 }} animate={{ width: 184, opacity: 1 }} exit={{ width: 0, opacity: 0 }} transition={{ duration: 0.2, ease: "easeInOut" }}
          className="flex-shrink-0 h-full bg-sidebar border-r border-sidebar-border overflow-hidden flex flex-col">
          <div className="p-3 space-y-0.5 overflow-auto flex-1">
            {NAV_ITEMS.map(item => {
              const Icon = item.icon;
              const active = activePath === item.path || (item.path === "dashboard" && activePath === "");
              return (
                <button key={item.id} onClick={() => navigate("/" + item.path)}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-[13px] transition-colors text-left ${active ? "bg-sidebar-accent font-medium text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-sidebar-accent/60"}`}>
                  <Icon size={14} className="flex-shrink-0" /> {item.label}
                </button>
              );
            })}
          </div>
          <div className="p-3 border-t border-sidebar-border">
            <button onClick={() => navigate("/settings")}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-[13px] transition-colors text-left ${activePath === "settings" ? "bg-sidebar-accent font-medium text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-sidebar-accent/60"}`}>
              <Settings size={14} className="flex-shrink-0" /> Settings
            </button>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

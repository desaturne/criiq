import { motion, AnimatePresence } from "motion/react";
import { useNavigate, useLocation } from "react-router";
import { Settings } from "lucide-react";
import { NAV_ITEMS } from "../../data/nav";

// Duolingo-style nav: chunky, rounded, generously spaced buttons. The active
// item gets a soft accent fill + a solid accent outline (like Duolingo's
// selected tab); inactive items keep a transparent border of the same width so
// nothing shifts when selection moves.
export function Sidebar({ open }: { open: boolean }) {
  const navigate = useNavigate();
  const location = useLocation();
  const activePath = location.pathname.replace(/^\//, "") || "dashboard";

  const buttonClass = (active: boolean) =>
    `w-full flex items-center gap-3 px-4 py-3 rounded-2xl text-[14px] font-bold text-left ` +
    `border-2 transition-all duration-150 active:scale-[0.96] ` +
    (active
      ? "bg-[#AAFF57]/15 border-[#AAFF57] text-foreground shadow-[0_2px_0_rgba(170,255,87,0.25)]"
      : "border-transparent text-muted-foreground hover:text-foreground hover:bg-sidebar-accent/70");

  return (
    <AnimatePresence>
      {open && (
        <motion.aside initial={{ width: 0, opacity: 0 }} animate={{ width: 214, opacity: 1 }} exit={{ width: 0, opacity: 0 }} transition={{ duration: 0.2, ease: "easeInOut" }}
          className="flex-shrink-0 h-full bg-sidebar border-r border-sidebar-border overflow-hidden flex flex-col">
          <div className="p-3.5 space-y-2 overflow-auto flex-1">
            {NAV_ITEMS.map(item => {
              const Icon = item.icon;
              const active = activePath === item.path || (item.path === "dashboard" && activePath === "");
              return (
                <button key={item.id} onClick={() => navigate("/" + item.path)} className={buttonClass(active)}>
                  <Icon size={19} className="flex-shrink-0" strokeWidth={active ? 2.5 : 2} /> {item.label}
                </button>
              );
            })}
          </div>
          <div className="p-3.5 border-t border-sidebar-border">
            <button onClick={() => navigate("/settings")} className={buttonClass(activePath === "settings")}>
              <Settings size={19} className="flex-shrink-0" strokeWidth={activePath === "settings" ? 2.5 : 2} /> Settings
            </button>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

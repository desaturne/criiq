import { motion } from "motion/react";
import { FileText, MapPin, Eye, Plus, Download } from "lucide-react";

export function ReportsPage() {
  const reports = [
    { id: "r1", match: "India vs Australia", venue: "MCG, Melbourne", date: "Jan 13, 2025", status: "Final", pages: 12 },
    { id: "r2", match: "India vs England", venue: "Lord's, London", date: "Jan 6, 2025", status: "Final", pages: 9 },
    { id: "r3", match: "India vs South Africa", venue: "Eden Gardens, Kolkata", date: "Dec 26, 2024", status: "Draft", pages: 7 },
    { id: "r4", match: "India vs New Zealand", venue: "Wankhede, Mumbai", date: "Jan 20, 2025", status: "Draft", pages: 4 },
  ];
  return (
    <div className="p-5 max-w-screen-xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="font-display text-2xl font-bold text-foreground">Reports</h1>
          <p className="text-sm text-muted-foreground mt-0.5">Pre-match scouting documents</p>
        </div>
        <button className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#AAFF57] text-[#0D0D06] rounded-lg font-medium hover:opacity-90">
          <Plus size={12} /> New Report
        </button>
      </div>
      <div className="grid gap-3">
        {reports.map((r, i) => (
          <motion.div key={r.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}
            className="bg-card border border-border rounded-xl p-5 hover:border-[#AAFF57]/30 transition-all cursor-pointer group flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-[#AAFF57]/10 flex items-center justify-center flex-shrink-0">
              <FileText size={18} className="text-[#AAFF57]" />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="font-semibold text-foreground text-[14px]">{r.match}</h3>
              <div className="flex items-center gap-3 mt-0.5 text-[12px] text-muted-foreground">
                <span className="flex items-center gap-1"><MapPin size={10} /> {r.venue}</span>
                <span>{r.date}</span>
                <span>{r.pages} pages</span>
              </div>
            </div>
            <span className={`text-[11px] px-2.5 py-1 rounded-full font-medium ${r.status === "Final" ? "bg-green-500/15 text-green-400" : "bg-amber-500/15 text-amber-400"}`}>{r.status}</span>
            <div className="flex gap-1.5">
              <button className="p-1.5 rounded hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors"><Eye size={13} /></button>
              <button className="p-1.5 rounded hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors"><Download size={13} /></button>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

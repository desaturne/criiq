import { useState, useEffect } from "react";

export function PhaseBar({ powerplay, middle, death }: { powerplay: number; middle: number; death: number }) {
  const [animated, setAnimated] = useState(false);
  useEffect(() => { const t = setTimeout(() => setAnimated(true), 500); return () => clearTimeout(t); }, []);
  const bar = (label: string, val: number, color: string) => (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-muted-foreground w-16 flex-shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-border overflow-hidden">
        <div className="h-full rounded-full transition-all duration-1000 ease-out" style={{ width: animated ? `${val}%` : "0%", backgroundColor: color }} />
      </div>
      <span className="font-mono text-[10px] w-6 text-right" style={{ color }}>{val}</span>
    </div>
  );
  return (
    <div className="space-y-1.5">
      {bar("Powerplay", powerplay, "#60A5FA")}
      {bar("Middle", middle, "#AAFF57")}
      {bar("Death", death, "#FB923C")}
    </div>
  );
}

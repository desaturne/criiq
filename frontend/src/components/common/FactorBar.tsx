import { useState, useEffect } from "react";

export function FactorBar({ label, value }: { label: string; value: number }) {
  const [animated, setAnimated] = useState(false);
  useEffect(() => { const t = setTimeout(() => setAnimated(true), 600); return () => clearTimeout(t); }, []);
  const color = value >= 80 ? "#AAFF57" : value >= 60 ? "#60A5FA" : value >= 40 ? "#FB923C" : "#F87171";
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-[10px]">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono" style={{ color }}>{value}</span>
      </div>
      <div className="h-1 rounded-full bg-border overflow-hidden">
        <div className="h-full rounded-full transition-all duration-1000" style={{ width: animated ? `${value}%` : "0%", backgroundColor: color }} />
      </div>
    </div>
  );
}

import { useState, useEffect } from "react";

export function RadialGauge({ value, max = 100, size = 72, strokeWidth = 5, color = "#AAFF57", label, decimals = 0 }: { value: number; max?: number; size?: number; strokeWidth?: number; color?: string; label?: string; decimals?: number }) {
  const r = (size - strokeWidth * 2) / 2;
  const circ = 2 * Math.PI * r;
  const [filled, setFilled] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => setFilled((value / max) * circ), 400);
    return () => clearTimeout(t);
  }, [value, max, circ]);
  return (
    <div style={{ width: size, height: size }} className="relative flex-shrink-0">
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={strokeWidth} className="text-border opacity-60" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round"
          strokeDasharray={`${filled} ${circ}`} style={{ transition: "stroke-dasharray 1.3s cubic-bezier(0.4,0,0.2,1)" }} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="leading-none font-mono text-xs font-medium" style={{ color, fontSize: size < 60 ? "0.65rem" : "0.8rem" }}>{value.toFixed(decimals)}</span>
        {label && <span className="text-[9px] text-muted-foreground mt-0.5 leading-none">{label}</span>}
      </div>
    </div>
  );
}

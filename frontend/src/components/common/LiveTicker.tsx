import { TICKER_ITEMS } from "../../data/ticker";

export function LiveTicker() {
  const items = [...TICKER_ITEMS, ...TICKER_ITEMS];

  return (
    <div className="flex-shrink-0 overflow-hidden border-b border-border relative bg-card" style={{ height: "28px" }}>
      {/* Edge fades */}
      <div className="absolute left-0 top-0 bottom-0 w-10 z-10 pointer-events-none"
           style={{ background: "linear-gradient(to right, var(--card), transparent)" }} />
      <div className="absolute right-0 top-0 bottom-0 w-10 z-10 pointer-events-none"
           style={{ background: "linear-gradient(to left, var(--card), transparent)" }} />

      {/* Scrolling track */}
      <div
        className="flex items-center h-full px-4"
        style={{ animation: "ticker-scroll 55s linear infinite", width: "max-content", willChange: "transform" }}
      >
        {items.map((item, i) => (
          <div key={i} className="flex items-center flex-shrink-0">
            {i > 0 && <span className="mx-4 text-muted-foreground opacity-30 text-[10px]">·</span>}

            {item.type === "live" ? (
              <div className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full animate-pulse flex-shrink-0 bg-red-500" />
                <span className="text-[10px] font-bold tracking-widest text-red-500">{item.text}</span>
                <span className="text-[11px] font-mono font-bold text-foreground ml-1">{item.value}</span>
                <span className="text-[10px] text-muted-foreground ml-0.5">{item.context}</span>
              </div>
            ) : item.type === "form" ? (
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] font-bold tracking-widest text-foreground">{item.text}</span>
                <div className="flex gap-0.5 ml-1">
                  {item.value.split("·").map((r, ri) => (
                    <span key={ri} className="text-[10px] font-bold"
                          style={{ color: r.trim() === "W" ? "#16a34a" : r.trim() === "L" ? "#dc2626" : "var(--muted-foreground)" }}>
                      {r.trim()}
                    </span>
                  ))}
                </div>
                <span className="text-[9px] text-muted-foreground uppercase tracking-wider ml-1">{item.context}</span>
              </div>
            ) : (
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] font-bold tracking-wider text-foreground">{item.text}</span>
                <span className="text-[11px] font-mono font-bold" style={{ color: item.color }}>{item.value}</span>
                <span className="text-[10px] text-muted-foreground">{item.context}</span>
              </div>
            )}
          </div>
        ))}
      </div>

      <style>{`
        @keyframes ticker-scroll {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>
    </div>
  );
}

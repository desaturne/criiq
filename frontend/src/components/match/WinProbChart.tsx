import { Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer, ComposedChart } from "recharts";

// Shared between the Simulator (Monte Carlo mean + p10/p90 band per ball)
// and a real past match's replayed win-probability timeline (a single exact
// line, no band -- a real match only happened once). `band` is optional so
// the same chart renders both shapes without a second component.
export interface WinProbPoint {
  match_ball_index: number;
  mean?: number;   // simulated: 0-1 fraction
  p10?: number;
  p90?: number;
  win_prob_team1_pct?: number; // real match: already a 0-100 percentage
}

export function WinProbChart({ timeline, team1, team2, title }: { timeline: WinProbPoint[]; team1: string; team2: string; title?: string }) {
  const hasBand = timeline.some(t => t.p10 !== undefined);
  const data = timeline.map(t => ({
    ball: t.match_ball_index,
    over: Math.floor(t.match_ball_index / 6),
    mean: t.mean !== undefined ? Math.round(t.mean * 1000) / 10 : t.win_prob_team1_pct,
    band: hasBand && t.p10 !== undefined && t.p90 !== undefined ? [Math.round(t.p10 * 1000) / 10, Math.round(t.p90 * 1000) / 10] : undefined,
  }));
  // ~240 ball-level rows (6/over) would otherwise render one x-axis tick per
  // row -- thin to roughly 10 evenly-spaced labels regardless of match length.
  const tickInterval = Math.max(1, Math.floor(data.length / 10));
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-1">
        <h4 className="text-[12px] font-semibold text-muted-foreground uppercase tracking-wider">{title ?? `Win Probability — ${team1}`}</h4>
        {hasBand && <span className="text-[10px] text-muted-foreground">shaded band = 10th–90th percentile across sims</span>}
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.4} vertical={false} />
          <XAxis dataKey="over" interval={tickInterval} tick={{ fontSize: 10, fill: "var(--muted-foreground)" }} tickLine={false} axisLine={{ stroke: "var(--border)" }}
            tickFormatter={v => `${v}`} label={{ value: "Over", position: "insideBottom", offset: -2, fontSize: 10, fill: "var(--muted-foreground)" }} />
          <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fontSize: 10, fill: "var(--muted-foreground)" }} tickLine={false} axisLine={false}
            tickFormatter={v => `${v}%`} width={34} />
          <ReferenceLine y={50} stroke="var(--muted-foreground)" strokeDasharray="4 4" strokeOpacity={0.5} />
          <Tooltip
            contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
            labelFormatter={v => `Over ${v}`}
            formatter={(value: any, name: string) => name === "mean" ? [`${value}%`, `${team1} win %`] : [null, null]}
          />
          {hasBand && <Area dataKey="band" stroke="none" fill="#AAFF57" fillOpacity={0.12} isAnimationActive={false} />}
          <Line type="monotone" dataKey="mean" stroke="#AAFF57" strokeWidth={2} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="flex justify-between text-[10px] text-muted-foreground mt-1 px-1">
        <span>{team1} favoured above 50%</span>
        <span>{team2} favoured below 50%</span>
      </div>
    </div>
  );
}

// batting_scorecard/bowling_scorecard-shaped rows -- identical shape for a
// simulated match (criiq_models.simulate.scorecard) and a real past match
// (backend's GET /matches/{id}/scorecard), so this one component renders
// both. Real <table> markup, not flex rows -- a flex row with a long
// highlight string (e.g. "Fastest scoring innings (SR 133.3)") pushed the
// numeric columns onto a second line and broke alignment between rows.
export interface BattingRow { player_id: string; name: string; runs: number; balls: number; strike_rate: number | null; status: string; highlight: string | null; }
export interface BowlingRow { player_id: string; name: string; overs: string; runs_conceded: number; wickets: number; economy: number | null; highlight: string | null; }

// A real cricket scorecard: a header row of column labels, then one row per
// player with runs / balls / strike-rate in their own aligned columns.
const TH = "px-2 py-1.5 font-semibold text-[10px] uppercase tracking-wider text-muted-foreground";

function BattingTable({ team, rows }: { team: string; rows: BattingRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12px] border-collapse">
        <thead>
          <tr className="border-b border-border">
            <th className={`${TH} text-left`}>{team} — Batting</th>
            <th className={`${TH} text-right w-12`}>R</th>
            <th className={`${TH} text-right w-12`}>B</th>
            <th className={`${TH} text-right w-16`}>SR</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(b => (
            <tr key={b.player_id} className="border-b border-border/40">
              <td className="px-2 py-1.5 align-top">
                <div className="text-foreground font-medium">
                  {b.name}{b.status === "not out" ? <span className="text-[#AAFF57]"> *</span> : ""}
                </div>
                {b.status && b.status !== "not out" && b.status !== "out" && (
                  <div className="text-muted-foreground text-[10px] leading-tight italic">{b.status}</div>
                )}
                {b.highlight && <div className="text-[#AAFF57] text-[10px] leading-tight">{b.highlight}</div>}
              </td>
              <td className="px-2 py-1.5 font-mono font-bold text-foreground text-right align-top">{b.runs}</td>
              <td className="px-2 py-1.5 font-mono text-muted-foreground text-right align-top">{b.balls}</td>
              <td className="px-2 py-1.5 font-mono text-muted-foreground text-right align-top">{b.strike_rate ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BowlingTable({ team, rows }: { team: string; rows: BowlingRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12px] border-collapse">
        <thead>
          <tr className="border-b border-border">
            <th className={`${TH} text-left`}>{team} — Bowling</th>
            <th className={`${TH} text-right w-12`}>O</th>
            <th className={`${TH} text-right w-12`}>R</th>
            <th className={`${TH} text-right w-10`}>W</th>
            <th className={`${TH} text-right w-16`}>Econ</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(b => (
            <tr key={b.player_id} className="border-b border-border/40">
              <td className="px-2 py-1.5 align-top">
                <div className="text-foreground font-medium">{b.name}</div>
                {b.highlight && <div className="text-[#AAFF57] text-[10px] leading-tight">{b.highlight}</div>}
              </td>
              <td className="px-2 py-1.5 font-mono text-muted-foreground text-right align-top">{b.overs}</td>
              <td className="px-2 py-1.5 font-mono text-muted-foreground text-right align-top">{b.runs_conceded}</td>
              <td className="px-2 py-1.5 font-mono font-bold text-foreground text-right align-top">{b.wickets}</td>
              <td className="px-2 py-1.5 font-mono text-muted-foreground text-right align-top">{b.economy ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function InningsScorecard({ battingTeam, bowlingTeam, batting, bowling }: {
  battingTeam?: string; bowlingTeam?: string; batting: BattingRow[]; bowling: BowlingRow[];
}) {
  return (
    <div className="space-y-3">
      <BattingTable team={battingTeam ?? "Batting"} rows={batting} />
      <BowlingTable team={bowlingTeam ?? "Bowling"} rows={bowling} />
    </div>
  );
}

// Simulated-match shape: result.first_innings_scorecard/second_innings_scorecard.
export function Scorecard({ result }: { result: any }) {
  return (
    <div className="bg-card border border-border rounded-xl p-4 space-y-4">
      <h4 className="text-[12px] font-semibold text-muted-foreground uppercase tracking-wider">Scorecard</h4>
      <InningsScorecard
        battingTeam={result.first_innings?.team} bowlingTeam={result.second_innings?.team}
        batting={result.first_innings_scorecard?.batting ?? []} bowling={result.first_innings_scorecard?.bowling ?? []}
      />
      <div className="border-t border-border pt-4">
        <InningsScorecard
          battingTeam={result.second_innings?.team} bowlingTeam={result.first_innings?.team}
          batting={result.second_innings_scorecard?.batting ?? []} bowling={result.second_innings_scorecard?.bowling ?? []}
        />
      </div>
    </div>
  );
}

// Real-match shape: GET /matches/{id}/scorecard's `innings` array, one entry
// per innings with its own batting_team/bowling_team (unlike the simulator,
// a real match's second innings' bowling team is just whichever team didn't
// bat first -- no need to infer it from a paired first_innings object).
export interface RealInningsCard {
  innings: number; batting_team: string; bowling_team: string;
  batting: BattingRow[]; bowling: BowlingRow[];
}

export function RealMatchScorecard({ innings }: { innings: RealInningsCard[] }) {
  return (
    <div className="bg-card border border-border rounded-xl p-4 space-y-4">
      <h4 className="text-[12px] font-semibold text-muted-foreground uppercase tracking-wider">Scorecard</h4>
      {innings.map((inn, i) => (
        <div key={inn.innings} className={i > 0 ? "border-t border-border pt-4" : ""}>
          <InningsScorecard battingTeam={inn.batting_team} bowlingTeam={inn.bowling_team} batting={inn.batting} bowling={inn.bowling} />
        </div>
      ))}
    </div>
  );
}

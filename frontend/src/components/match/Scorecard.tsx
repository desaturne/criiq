// batting_scorecard/bowling_scorecard-shaped rows -- identical shape for a
// simulated match (criiq_models.simulate.scorecard) and a real past match
// (backend's GET /matches/{id}/scorecard), so this one component renders
// both. Real <table> markup, not flex rows -- a flex row with a long
// highlight string (e.g. "Fastest scoring innings (SR 133.3)") pushed the
// numeric columns onto a second line and broke alignment between rows.
export interface BattingRow { player_id: string; name: string; runs: number; balls: number; strike_rate: number | null; status: string; highlight: string | null; }
export interface BowlingRow { player_id: string; name: string; overs: string; runs_conceded: number; wickets: number; economy: number | null; highlight: string | null; }

function BattingTable({ team, rows }: { team: string; rows: BattingRow[] }) {
  return (
    <div>
      <h5 className="text-[11px] font-semibold text-foreground mb-1.5">{team} batting</h5>
      <table className="w-full text-[11px] border-collapse">
        <colgroup><col /><col className="w-16" /><col className="w-14" /></colgroup>
        <tbody>
          {rows.map(b => (
            <tr key={b.player_id} className="odd:bg-secondary/30">
              <td className="px-2 py-1 align-top">
                <div className="text-foreground truncate">{b.name}</div>
                {b.highlight && <div className="text-[#AAFF57] text-[10px] leading-tight">{b.highlight}</div>}
              </td>
              <td className="px-2 py-1 font-mono text-foreground text-right whitespace-nowrap align-top">
                {b.runs} ({b.balls}){b.status === "not out" ? "*" : ""}
              </td>
              <td className="px-2 py-1 font-mono text-muted-foreground text-right whitespace-nowrap align-top">
                {b.strike_rate ?? "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BowlingTable({ team, rows }: { team: string; rows: BowlingRow[] }) {
  return (
    <div>
      <h5 className="text-[11px] font-semibold text-foreground mb-1.5">{team} bowling</h5>
      <table className="w-full text-[11px] border-collapse">
        <colgroup><col /><col className="w-10" /><col className="w-14" /><col className="w-12" /></colgroup>
        <tbody>
          {rows.map(b => (
            <tr key={b.player_id} className="odd:bg-secondary/30">
              <td className="px-2 py-1 align-top">
                <div className="text-foreground truncate">{b.name}</div>
                {b.highlight && <div className="text-[#AAFF57] text-[10px] leading-tight">{b.highlight}</div>}
              </td>
              <td className="px-2 py-1 font-mono text-foreground text-right whitespace-nowrap align-top">{b.overs}</td>
              <td className="px-2 py-1 font-mono text-foreground text-right whitespace-nowrap align-top">{b.wickets}/{b.runs_conceded}</td>
              <td className="px-2 py-1 font-mono text-muted-foreground text-right whitespace-nowrap align-top">{b.economy ?? "-"}</td>
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

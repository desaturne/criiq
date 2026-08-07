import { useEffect, useState } from "react";
import * as api from "../../lib/api";

// Real grounds (GET /venues, 370+ real venues) instead of five hardcoded
// stadium names -- grouped into "Likely grounds" (real match history for
// this specific team1/team2 pairing) and every other ground, so a name
// that doesn't exist in the DB can never be selected (which used to
// silently fail to fuzzy-match and make venue conditioning a no-op).
export function VenueSelect({ label = "Venue", value, onChange, team1, team2 }: {
  label?: string; value: string; onChange: (v: string) => void; team1?: string; team2?: string;
}) {
  const [venues, setVenues] = useState<{ venue_id: string; name: string; matches_here: number }[]>([]);

  useEffect(() => {
    api.listVenues({ team1, team2 }).then(setVenues).catch(() => setVenues([]));
  }, [team1, team2]);

  const likely = venues.filter(v => v.matches_here > 0);
  const others = venues.filter(v => v.matches_here === 0);
  const valueMissing = value && !venues.some(v => v.name === value);

  return (
    <div className="flex-1 space-y-1">
      <label className="text-[11px] text-muted-foreground">{label} <span className="opacity-60">(optional)</span></label>
      <select value={value} onChange={e => onChange(e.target.value)}
        className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
        <option value="">No preference</option>
        {valueMissing && <option value={value}>{value}</option>}
        {likely.length > 0 && (
          <optgroup label="Likely grounds for this matchup">
            {likely.map(v => <option key={v.venue_id} value={v.name}>{v.name} ({v.matches_here})</option>)}
          </optgroup>
        )}
        <optgroup label={likely.length > 0 ? "All other grounds" : "All grounds"}>
          {others.map(v => <option key={v.venue_id} value={v.name}>{v.name}</option>)}
        </optgroup>
      </select>
    </div>
  );
}

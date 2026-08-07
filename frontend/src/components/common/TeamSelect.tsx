import { useEffect, useState } from "react";
import * as api from "../../lib/api";

// Real, gender-scoped international team list (GET /teams) instead of a
// handful of hardcoded countries -- grouped into "Likely matchups" (real
// head-to-head history against `against`) and everything else, so the
// dropdown surfaces realistic opponents first without hiding the rest.
export function TeamSelect({ label, value, onChange, gender, against, disabled }: {
  label: string; value: string; onChange: (v: string) => void;
  gender: "female" | "male"; against?: string; disabled?: boolean;
}) {
  const [teams, setTeams] = useState<{ team: string; matches_played: number }[]>([]);

  useEffect(() => {
    api.listTeams({ gender, against }).then(setTeams).catch(() => setTeams([]));
  }, [gender, against]);

  if (disabled) {
    return (
      <div className="flex-1 space-y-1">
        <label className="text-[11px] text-muted-foreground">{label}</label>
        <button type="button" disabled
          className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2 text-foreground text-left cursor-default">
          {value}
        </button>
      </div>
    );
  }

  const likely = teams.filter(t => t.matches_played > 0);
  const others = teams.filter(t => t.matches_played === 0);
  // If the current value isn't in the fetched list yet (still loading, or a
  // stale selection from before a gender switch), keep it selectable rather
  // than silently blanking the field out.
  const valueMissing = value && !teams.some(t => t.team === value);

  return (
    <div className="flex-1 space-y-1">
      <label className="text-[11px] text-muted-foreground">{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)}
        className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
        {valueMissing && <option value={value}>{value}</option>}
        {likely.length > 0 && (
          <optgroup label="Likely matchups">
            {likely.map(t => <option key={t.team} value={t.team}>{t.team} ({t.matches_played})</option>)}
          </optgroup>
        )}
        <optgroup label={likely.length > 0 ? "Other teams" : "All teams"}>
          {others.map(t => <option key={t.team} value={t.team}>{t.team}</option>)}
        </optgroup>
      </select>
    </div>
  );
}

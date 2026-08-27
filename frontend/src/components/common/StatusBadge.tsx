import { PlayerStatus } from "../../types/index";

export function StatusBadge({ status }: { status: PlayerStatus }) {
  const cfg = { ACTIVE: "bg-green-500/15 text-green-400", INCONSISTENT: "bg-amber-500/15 text-amber-400", INACTIVE: "bg-red-500/15 text-red-400", RETIRED: "bg-slate-500/15 text-slate-300", UNKNOWN: "bg-muted text-muted-foreground" }[status];
  return <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${cfg}`}>{status}</span>;
}

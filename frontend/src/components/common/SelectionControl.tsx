import { CheckCircle, XCircle, MinusCircle } from "lucide-react";
import { SelectionState } from "../../types/index";

export function SelectionControl({ state, onChange }: { state: SelectionState; onChange: (s: SelectionState) => void }) {
  const toggle = (val: SelectionState) => onChange(state === val ? "undecided" : val);
  return (
    <div className="grid w-full grid-cols-3 rounded-lg overflow-hidden text-[11px] font-medium border border-border sm:w-auto sm:flex">
      <button
        onClick={() => toggle("select")}
        className="flex min-w-0 items-center justify-center gap-1 px-2 py-1.5 transition-all duration-150 active:scale-95 whitespace-nowrap"
        style={state === "select" ? { background: "#5FA800", color: "#fff" } : { background: "var(--secondary)", color: "var(--muted-foreground)" }}
        title="Select for XI"
      >
        <CheckCircle size={11} /> Select
      </button>
      <button
        onClick={() => toggle("reserve")}
        className="flex min-w-0 items-center justify-center gap-1 px-2 py-1.5 border-x border-border transition-all duration-150 active:scale-95 whitespace-nowrap"
        style={state === "reserve" ? { background: "#8A8970", color: "#fff" } : { background: "var(--secondary)", color: "var(--muted-foreground)" }}
        title="Mark as Reserve"
      >
        <MinusCircle size={11} /> Reserve
      </button>
      <button
        onClick={() => toggle("exclude")}
        className="flex min-w-0 items-center justify-center gap-1 px-2 py-1.5 transition-all duration-150 active:scale-95 whitespace-nowrap"
        style={state === "exclude" ? { background: "#E5484D", color: "#fff" } : { background: "var(--secondary)", color: "var(--muted-foreground)" }}
        title="Exclude from selection"
      >
        <XCircle size={11} /> Exclude
      </button>
    </div>
  );
}

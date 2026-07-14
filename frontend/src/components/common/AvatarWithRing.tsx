import React from "react";
import { motion } from "motion/react";
import { SelectionState } from "../../types/index";

export function AvatarWithRing({ initials, color, selection, size = 40 }: { initials: string; color: string; selection: SelectionState; size?: number }) {
  const ringStyle: React.CSSProperties =
    selection === "select"  ? { border: "2.5px solid #5FA800" } :
    selection === "exclude" ? { border: "2.5px solid #E5484D" } :
    selection === "reserve" ? { border: "2px dashed #8A8970"  } :
                              { border: "2.5px solid transparent" };
  return (
    <motion.div
      animate={selection !== "undecided" ? { scale: [1, 1.08, 1] } : {}}
      transition={{ duration: 0.25 }}
      style={{ width: size + 8, height: size + 8, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, transition: "border 0.2s", ...ringStyle }}
    >
      <div style={{ width: size, height: size, borderRadius: "50%", backgroundColor: color + "33", color, display: "flex", alignItems: "center", justifyContent: "center", fontSize: size < 36 ? "10px" : "12px", fontWeight: "bold" }}>
        {initials}
      </div>
    </motion.div>
  );
}

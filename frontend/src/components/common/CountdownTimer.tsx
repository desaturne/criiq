import { useState, useEffect } from "react";
import { motion } from "motion/react";

export function CountdownTimer({ targetDate }: { targetDate: string }) {
  const [time, setTime] = useState({ days: 3, hours: 14, minutes: 22, seconds: 0 });
  useEffect(() => {
    const target = new Date(targetDate);
    const update = () => {
      const diff = target.getTime() - Date.now();
      if (diff > 0) {
        setTime({
          days:    Math.floor(diff / 86400000),
          hours:   Math.floor((diff % 86400000) / 3600000),
          minutes: Math.floor((diff % 3600000) / 60000),
          seconds: Math.floor((diff % 60000) / 1000),
        });
      }
    };
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, [targetDate]);
  return (
    <div className="flex items-end gap-4">
      {[{ v: time.days, l: "DAYS" }, { v: time.hours, l: "HRS" }, { v: time.minutes, l: "MIN" }, { v: time.seconds, l: "SEC" }].map((t) => (
        <div key={t.l} className="text-center">
          <motion.div
            key={t.v}
            initial={{ y: -6, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            className="font-mono font-bold tabular-nums leading-none"
            style={{ fontSize: "2.6rem", color: "#AAFF57", textShadow: "0 0 24px rgba(170,255,87,0.5)" }}
          >
            {String(t.v).padStart(2, "0")}
          </motion.div>
          <div className="text-[9px] font-semibold text-muted-foreground tracking-[0.15em] mt-1.5">{t.l}</div>
        </div>
      ))}
    </div>
  );
}

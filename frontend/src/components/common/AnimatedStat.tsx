import { useRef } from "react";
import { useCountUp } from "../../hooks/useCountUp";
import { useInView } from "../../hooks/useInView";

export function AnimatedStat({ value, suffix = "", prefix = "" }: { value: number; suffix?: string; prefix?: string }) {
  const ref = useRef<HTMLSpanElement>(null!);
  const inView = useInView(ref);
  const counted = useCountUp(inView ? value : 0, 1000, 100);
  return <span ref={ref}>{prefix}{counted}{suffix}</span>;
}

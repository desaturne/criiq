export function CricketBall({ size = 18, className = "" }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={className} fill="currentColor">
      <circle cx="12" cy="12" r="10" />
      <path d="M8.5 3.5C6.5 7 6.5 17 8.5 20.5" stroke="rgba(0,0,0,0.4)" strokeWidth="1.8" fill="none" strokeLinecap="round" />
      <path d="M15.5 3.5C17.5 7 17.5 17 15.5 20.5" stroke="rgba(0,0,0,0.4)" strokeWidth="1.8" fill="none" strokeLinecap="round" />
      <line x1="8.5" y1="9" x2="10.5" y2="9" stroke="rgba(0,0,0,0.35)" strokeWidth="1.2" strokeLinecap="round" />
      <line x1="8.5" y1="12" x2="10.5" y2="12" stroke="rgba(0,0,0,0.35)" strokeWidth="1.2" strokeLinecap="round" />
      <line x1="8.5" y1="15" x2="10.5" y2="15" stroke="rgba(0,0,0,0.35)" strokeWidth="1.2" strokeLinecap="round" />
      <line x1="13.5" y1="9" x2="15.5" y2="9" stroke="rgba(0,0,0,0.35)" strokeWidth="1.2" strokeLinecap="round" />
      <line x1="13.5" y1="12" x2="15.5" y2="12" stroke="rgba(0,0,0,0.35)" strokeWidth="1.2" strokeLinecap="round" />
      <line x1="13.5" y1="15" x2="15.5" y2="15" stroke="rgba(0,0,0,0.35)" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

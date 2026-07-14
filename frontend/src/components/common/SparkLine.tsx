export function SparkLine({ values, color = "#AAFF57", height = 28, width = 72 }: { values: number[]; color?: string; height?: number; width?: number }) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * width;
    const y = height - ((v - min) / range) * (height - 4) - 2;
    return `${x},${y}`;
  }).join(" ");
  const lastX = ((values.length - 1) / (values.length - 1)) * width;
  const lastY = height - ((values[values.length - 1] - min) / range) * (height - 4) - 2;
  return (
    <svg width={width} height={height} className="overflow-visible">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.6" />
      <circle cx={lastX} cy={lastY} r={2.5} fill={color} />
    </svg>
  );
}

import type { PricePoint } from "@/types";

interface Props {
  points: PricePoint[];
  width?: number;
  height?: number;
  maxPoints?: number;
}

/** Tiny inline-SVG sparkline. Colour follows first→last direction. */
export default function Sparkline({ points, width = 84, height = 24, maxPoints = 120 }: Props) {
  const pts = points.length > maxPoints ? points.slice(points.length - maxPoints) : points;
  if (pts.length < 2) {
    return (
      <svg width={width} height={height} aria-hidden data-testid="sparkline">
        <line x1={0} x2={width} y1={height / 2} y2={height / 2} stroke="#30363d" strokeDasharray="2 3" />
      </svg>
    );
  }
  let min = Infinity;
  let max = -Infinity;
  for (const p of pts) {
    if (p.value < min) min = p.value;
    if (p.value > max) max = p.value;
  }
  const range = max - min || 1;
  const pad = 2;
  const step = (width - pad * 2) / (pts.length - 1);
  const d = pts
    .map((p, i) => {
      const x = pad + i * step;
      const y = pad + (1 - (p.value - min) / range) * (height - pad * 2);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join("");
  const up = pts[pts.length - 1].value >= pts[0].value;
  const color = up ? "#26d07c" : "#ff5c5c";
  return (
    <svg width={width} height={height} aria-hidden data-testid="sparkline">
      <path d={d} fill="none" stroke={color} strokeWidth={1.25} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

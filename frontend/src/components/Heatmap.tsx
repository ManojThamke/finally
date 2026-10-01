"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Position } from "@/types";
import { formatPercent, formatSignedUsd } from "@/utils/format";
import { squarify } from "@/utils/treemap";

/** P&L % at which a tile reaches full colour intensity. */
const PNL_CLAMP = 5;

function mix(a: [number, number, number], b: [number, number, number], t: number) {
  return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * t)).join(",")})`;
}

const NEUTRAL: [number, number, number] = [33, 38, 45];
const GAIN: [number, number, number] = [22, 163, 90];
const LOSS: [number, number, number] = [214, 58, 58];

export function pnlColor(pnlPercent: number): string {
  if (!Number.isFinite(pnlPercent) || Math.abs(pnlPercent) < 0.005) return mix(NEUTRAL, NEUTRAL, 0);
  const t = Math.min(Math.abs(pnlPercent) / PNL_CLAMP, 1);
  return mix(NEUTRAL, pnlPercent > 0 ? GAIN : LOSS, 0.3 + 0.7 * t);
}

interface Props {
  positions: Position[];
  onSelect?: (ticker: string) => void;
}

export default function Heatmap({ positions, onSelect }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 160, h: 100 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) setSize({ w: r.width, h: r.height });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const rects = useMemo(
    () =>
      squarify(
        positions.map((p) => ({ value: p.market_value, data: p })),
        size.w,
        size.h,
      ),
    [positions, size],
  );

  return (
    <section data-testid="heatmap" className="panel h-full">
      <div className="panel-title">
        <span>Heatmap</span>
        <span className="flex items-center gap-1.5 font-mono text-[9.5px] normal-case tracking-normal text-ink-500">
          <span>−{PNL_CLAMP}%</span>
          <span
            className="h-1.5 w-16 rounded-full"
            style={{ background: `linear-gradient(90deg, ${pnlColor(-PNL_CLAMP)}, ${pnlColor(0)}, ${pnlColor(PNL_CLAMP)})` }}
          />
          <span>+{PNL_CLAMP}%</span>
        </span>
      </div>
      <div ref={ref} className="relative min-h-0 flex-1 overflow-hidden">
        {rects.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center text-[11px] uppercase tracking-[0.18em] text-ink-500">
            No positions
          </div>
        ) : (
          rects.map((r) => {
            const p = r.data;
            const big = r.w > 70 && r.h > 40;
            return (
              <button
                type="button"
                key={p.ticker}
                data-testid={`heatmap-tile-${p.ticker}`}
                data-pnl={p.unrealized_pnl >= 0 ? "gain" : "loss"}
                onClick={() => onSelect?.(p.ticker)}
                title={`${p.ticker}  ${formatSignedUsd(p.unrealized_pnl)} (${formatPercent(p.unrealized_pnl_percent)})  weight ${p.weight.toFixed(1)}%`}
                className="absolute flex flex-col items-start justify-between overflow-hidden p-1.5 text-left transition-[filter] hover:brightness-125"
                style={{
                  left: `${(r.x / size.w) * 100}%`,
                  top: `${(r.y / size.h) * 100}%`,
                  width: `${(r.w / size.w) * 100}%`,
                  height: `${(r.h / size.h) * 100}%`,
                  background: pnlColor(p.unrealized_pnl_percent),
                  boxShadow: "inset 0 0 0 1px #0d1117",
                }}
              >
                <span className="font-mono text-[12px] font-bold leading-none text-white/95">{p.ticker}</span>
                {big && (
                  <span className="font-mono text-[10.5px] leading-tight text-white/85">
                    {formatPercent(p.unrealized_pnl_percent)}
                    <br />
                    <span className="text-white/60">{p.weight.toFixed(1)}% wt</span>
                  </span>
                )}
              </button>
            );
          })
        )}
      </div>
    </section>
  );
}

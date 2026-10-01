"use client";

import { useEffect, useMemo, useRef } from "react";
import { AreaSeries, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import type { Snapshot } from "@/types";
import { formatSignedUsd, toneClass } from "@/utils/format";
import { baseChartOptions, toChartData } from "./chartTheme";

interface Props {
  snapshots: Snapshot[];
  liveValue: number | null;
}

export function snapshotsToPoints(snapshots: Snapshot[], liveValue: number | null, now = Date.now() / 1000) {
  const pts = snapshots
    .map((s) => ({ time: Date.parse(s.recorded_at) / 1000, value: s.total_value }))
    .filter((p) => Number.isFinite(p.time) && Number.isFinite(p.value))
    .sort((a, b) => a.time - b.time);
  if (liveValue != null && Number.isFinite(liveValue)) {
    const last = pts[pts.length - 1];
    if (!last || now > last.time) pts.push({ time: now, value: liveValue });
  }
  return toChartData(pts);
}

export default function PnlChart({ snapshots, liveValue }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);

  // Live value moves every tick; only re-plot when it changes by a cent to keep things calm.
  const roundedLive = liveValue == null ? null : Math.round(liveValue * 100) / 100;
  const points = useMemo(() => snapshotsToPoints(snapshots, roundedLive), [snapshots, roundedLive]);
  const first = points[0]?.value;
  const last = points[points.length - 1]?.value;
  const change = first != null && last != null ? last - first : null;
  const gain = (change ?? 0) >= 0;

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      ...baseChartOptions(),
      timeScale: { borderColor: "#21262d", timeVisible: true, secondsVisible: false },
    });
    seriesRef.current = chart.addSeries(AreaSeries, {
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    chartRef.current = chart;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    series.applyOptions(
      gain
        ? { lineColor: "#26d07c", topColor: "rgba(38,208,124,0.25)", bottomColor: "rgba(38,208,124,0)" }
        : { lineColor: "#ff5c5c", topColor: "rgba(255,92,92,0.25)", bottomColor: "rgba(255,92,92,0)" },
    );
    series.setData(points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    chartRef.current?.timeScale().fitContent();
  }, [points, gain]);

  return (
    <section data-testid="pnl-chart" data-points={points.length} className="panel h-full">
      <div className="panel-title">
        <span>Portfolio Value</span>
        <span className={`font-mono text-[11px] normal-case tracking-normal ${toneClass(change)}`}>
          {change == null ? "—" : `${formatSignedUsd(change)} session`}
        </span>
      </div>
      <div className="relative min-h-0 flex-1">
        <div ref={containerRef} className="absolute inset-0" />
        {points.length < 2 && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-[11px] uppercase tracking-[0.18em] text-ink-500">
            Collecting snapshots…
          </div>
        )}
      </div>
    </section>
  );
}

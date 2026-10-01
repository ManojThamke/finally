"use client";

import { useEffect, useRef } from "react";
import { AreaSeries, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import type { PricePoint, PriceTick } from "@/types";
import { formatPercent, formatPrice, toneClass } from "@/utils/format";
import { baseChartOptions, toChartData } from "./chartTheme";

interface Props {
  ticker: string | null;
  points: PricePoint[];
  tick: PriceTick | undefined;
  version: number;
}

export default function MainChart({ ticker, points, tick, version }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, baseChartOptions());
    const series = chart.addSeries(AreaSeries, {
      lineColor: "#209dd7",
      lineWidth: 2,
      topColor: "rgba(32,157,215,0.28)",
      bottomColor: "rgba(32,157,215,0.0)",
      priceLineColor: "#ecad0a",
      priceLineStyle: 2,
      lastValueVisible: true,
    });
    chartRef.current = chart;
    seriesRef.current = series;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    const data = toChartData(points).map((p) => ({ time: p.time as UTCTimestamp, value: p.value }));
    series.setData(data);
    chartRef.current?.timeScale().fitContent();
    // `version` changes whenever new SSE points arrive (points array is mutated in place).
  }, [ticker, points, version]);

  const up = (tick?.day_change_percent ?? 0) >= 0;

  return (
    <section data-testid="main-chart" className="panel h-full">
      <div className="panel-title">
        <span className="flex items-baseline gap-3">
          <span>Chart</span>
          <span data-testid="selected-ticker" className="font-mono text-[13px] font-bold normal-case tracking-normal text-accent">
            {ticker ?? "—"}
          </span>
        </span>
        {tick && (
          <span className="flex items-baseline gap-3 font-mono normal-case tracking-normal">
            <span className="text-[14px] font-semibold text-ink-100">{formatPrice(tick.price)}</span>
            <span className={`text-[11px] ${toneClass(tick.day_change_percent)}`}>
              {up ? "▲" : "▼"} {formatPercent(tick.day_change_percent)} day
            </span>
          </span>
        )}
      </div>
      <div className="relative min-h-0 flex-1">
        <div ref={containerRef} className="absolute inset-0" />
        {points.length < 2 && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-[11px] uppercase tracking-[0.18em] text-ink-500">
            {ticker ? "Accumulating ticks…" : "Select a ticker"}
          </div>
        )}
      </div>
    </section>
  );
}

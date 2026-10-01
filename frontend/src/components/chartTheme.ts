import { ColorType, CrosshairMode, LineStyle } from "lightweight-charts";

/** Shared lightweight-charts options for the terminal theme. */
export function baseChartOptions() {
  return {
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: "#8b949e",
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
      fontSize: 10,
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: "rgba(48,54,61,0.35)", style: LineStyle.Dotted },
      horzLines: { color: "rgba(48,54,61,0.35)", style: LineStyle.Dotted },
    },
    rightPriceScale: { borderColor: "#21262d" },
    timeScale: { borderColor: "#21262d", timeVisible: true, secondsVisible: true },
    crosshair: {
      mode: CrosshairMode.Magnet,
      vertLine: { color: "#484f58", labelBackgroundColor: "#21262d" },
      horzLine: { color: "#484f58", labelBackgroundColor: "#21262d" },
    },
    handleScroll: false,
    handleScale: false,
  };
}

/** lightweight-charts needs strictly increasing integer-second times: keep the last value per second. */
export function toChartData(points: { time: number; value: number }[]) {
  const out: { time: number; value: number }[] = [];
  for (const p of points) {
    const t = Math.floor(p.time);
    const last = out[out.length - 1];
    if (last && last.time === t) last.value = p.value;
    else if (!last || t > last.time) out.push({ time: t, value: p.value });
  }
  return out;
}

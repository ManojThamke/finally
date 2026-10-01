import { describe, expect, it } from "vitest";
import { computeLivePortfolio } from "@/utils/portfolio";
import { squarify } from "@/utils/treemap";
import { formatPercent, formatSignedUsd, formatUsd } from "@/utils/format";
import type { Portfolio, PriceMap } from "@/types";

const base: Portfolio = {
  cash_balance: 5000,
  positions_value: 0,
  total_value: 0,
  unrealized_pnl: 0,
  unrealized_pnl_percent: 0,
  positions: [
    { ticker: "AAPL", quantity: 10, avg_cost: 100, current_price: 100, market_value: 1000, unrealized_pnl: 0, unrealized_pnl_percent: 0, weight: 0 },
    { ticker: "TSLA", quantity: 5, avg_cost: 200, current_price: 200, market_value: 1000, unrealized_pnl: 0, unrealized_pnl_percent: 0, weight: 0 },
  ],
};

const tick = (ticker: string, price: number) => ({ ticker, price, previous_price: price, timestamp: 1, direction: "flat" as const });

describe("computeLivePortfolio", () => {
  it("returns null without a portfolio", () => {
    expect(computeLivePortfolio(null, {})).toBeNull();
  });

  it("revalues positions with live prices", () => {
    const prices: PriceMap = { AAPL: tick("AAPL", 110), TSLA: tick("TSLA", 180) };
    const p = computeLivePortfolio(base, prices)!;
    const aapl = p.positions.find((x) => x.ticker === "AAPL")!;
    const tsla = p.positions.find((x) => x.ticker === "TSLA")!;
    expect(aapl.market_value).toBe(1100);
    expect(aapl.unrealized_pnl).toBe(100);
    expect(aapl.unrealized_pnl_percent).toBeCloseTo(10);
    expect(tsla.unrealized_pnl).toBe(-100);
    expect(tsla.unrealized_pnl_percent).toBeCloseTo(-10);
    expect(p.positions_value).toBe(2000);
    expect(p.total_value).toBe(7000);
    expect(p.unrealized_pnl).toBe(0);
    expect(aapl.weight).toBeCloseTo((1100 / 7000) * 100);
  });

  it("falls back to server current price when no live tick", () => {
    const p = computeLivePortfolio({ ...base, positions: [{ ...base.positions[0], current_price: 120 }] }, {})!;
    expect(p.positions[0].market_value).toBe(1200);
    expect(p.total_value).toBe(6200);
  });

  it("handles an empty portfolio", () => {
    const p = computeLivePortfolio({ ...base, cash_balance: 10000, positions: [] }, {})!;
    expect(p.total_value).toBe(10000);
    expect(p.unrealized_pnl_percent).toBe(0);
  });
});

describe("squarify", () => {
  it("tiles the full area proportionally", () => {
    const rects = squarify(
      [
        { value: 6, data: "a" },
        { value: 3, data: "b" },
        { value: 1, data: "c" },
      ],
      100,
      50,
    );
    expect(rects).toHaveLength(3);
    const area = rects.reduce((s, r) => s + r.w * r.h, 0);
    expect(area).toBeCloseTo(5000);
    const a = rects.find((r) => r.data === "a")!;
    expect(a.w * a.h).toBeCloseTo(3000);
    for (const r of rects) {
      expect(r.x).toBeGreaterThanOrEqual(-1e-9);
      expect(r.y).toBeGreaterThanOrEqual(-1e-9);
      expect(r.x + r.w).toBeLessThanOrEqual(100 + 1e-9);
      expect(r.y + r.h).toBeLessThanOrEqual(50 + 1e-9);
    }
  });

  it("drops non-positive values and handles empty input", () => {
    expect(squarify([{ value: 0, data: 1 }], 10, 10)).toEqual([]);
    expect(squarify([], 10, 10)).toEqual([]);
  });
});

describe("format", () => {
  it("formats currency and signs", () => {
    expect(formatUsd(10000)).toBe("$10,000.00");
    expect(formatSignedUsd(12.5)).toBe("+$12.50");
    expect(formatSignedUsd(-12.5)).toBe("−$12.50");
    expect(formatPercent(1.234)).toBe("+1.23%");
    expect(formatPercent(null)).toBe("—");
  });
});

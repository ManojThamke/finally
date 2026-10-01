import { describe, expect, it } from "vitest";
import { appendTicks } from "@/hooks/usePriceStream";
import { toChartData } from "@/components/chartTheme";
import { snapshotsToPoints } from "@/components/PnlChart";
import { fromHistory } from "@/utils/chat";
import type { PricePoint } from "@/types";

const t = (ticker: string, price: number, timestamp: number) => ({ ticker, price, previous_price: price, timestamp, direction: "flat" as const });

describe("appendTicks", () => {
  it("accumulates points, skipping duplicate/out-of-order timestamps and capping length", () => {
    const h: Record<string, PricePoint[]> = {};
    appendTicks(h, [t("AAPL", 1, 1), t("MSFT", 5, 1)]);
    appendTicks(h, [t("AAPL", 2, 1)]); // duplicate timestamp
    appendTicks(h, [t("AAPL", 3, 0.5)]); // older
    appendTicks(h, [t("AAPL", 4, 2), t("AAPL", 5, 3)], 2);
    expect(h.AAPL.map((p) => p.value)).toEqual([4, 5]);
    expect(h.MSFT).toHaveLength(1);
  });
});

describe("toChartData", () => {
  it("buckets to whole seconds keeping the last value", () => {
    expect(
      toChartData([
        { time: 10.1, value: 1 },
        { time: 10.6, value: 2 },
        { time: 11.2, value: 3 },
      ]),
    ).toEqual([
      { time: 10, value: 2 },
      { time: 11, value: 3 },
    ]);
  });
});

describe("snapshotsToPoints", () => {
  it("sorts snapshots and appends the live value", () => {
    const pts = snapshotsToPoints(
      [
        { total_value: 10100, recorded_at: "2026-01-01T00:01:00Z" },
        { total_value: 10000, recorded_at: "2026-01-01T00:00:00Z" },
      ],
      10200,
      Date.parse("2026-01-01T00:02:00Z") / 1000,
    );
    expect(pts.map((p) => p.value)).toEqual([10000, 10100, 10200]);
  });
});

describe("fromHistory", () => {
  it("normalises dict, list and null actions", () => {
    const base = { id: "1", role: "assistant" as const, content: "hi", created_at: "" };
    expect(fromHistory({ ...base, actions: null }).trades).toEqual([]);
    const dict = fromHistory({
      ...base,
      actions: {
        trades: [{ ticker: "AAPL", side: "buy", quantity: 1, status: "executed" }],
        watchlist_changes: [{ ticker: "PYPL", action: "add", status: "executed" }],
      },
    });
    expect(dict.trades).toHaveLength(1);
    expect(dict.watchlist_changes).toHaveLength(1);
    const list = fromHistory({
      ...base,
      actions: [
        { ticker: "AAPL", side: "sell", quantity: 1, status: "failed", error: "nope" },
        { ticker: "PYPL", action: "remove", status: "executed" },
      ],
    });
    expect(list.trades[0].side).toBe("sell");
    expect(list.watchlist_changes[0].action).toBe("remove");
  });
});

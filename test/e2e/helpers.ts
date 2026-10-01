import { APIRequestContext, Locator, Page, expect } from "@playwright/test";

export const DEFAULT_TICKERS = [
  "AAPL", "GOOGL", "MSFT", "AMZN", "TSLA",
  "NVDA", "META", "JPM", "V", "NFLX",
];

export const FRESH_DB = process.env.FRESH_DB === "1" || process.env.FRESH_DB === "true";

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_percent: number;
  weight: number;
}

export interface Portfolio {
  cash_balance: number;
  positions_value: number;
  total_value: number;
  unrealized_pnl: number;
  unrealized_pnl_percent: number;
  positions: Position[];
}

/** Parse a displayed money/number string like "$10,000.00" or "-1,234.5" into a number. */
export function parseMoney(text: string | null): number {
  const cleaned = (text ?? "").replace(/[^0-9.\-]/g, "");
  const n = parseFloat(cleaned);
  if (Number.isNaN(n)) throw new Error(`Could not parse number from "${text}"`);
  return n;
}

export async function moneyOf(locator: Locator): Promise<number> {
  return parseMoney(await locator.innerText());
}

export async function getPortfolio(request: APIRequestContext): Promise<Portfolio> {
  const res = await request.get("/api/portfolio");
  expect(res.status()).toBe(200);
  return res.json();
}

export function positionQty(p: Portfolio, ticker: string): number {
  return p.positions.find((x) => x.ticker === ticker)?.quantity ?? 0;
}

export async function getWatchlist(request: APIRequestContext): Promise<string[]> {
  const res = await request.get("/api/watchlist");
  expect(res.status()).toBe(200);
  const body = await res.json();
  return body.tickers.map((t: { ticker: string }) => t.ticker);
}

export async function trade(
  request: APIRequestContext,
  ticker: string,
  side: "buy" | "sell",
  quantity: number,
) {
  return request.post("/api/portfolio/trade", { data: { ticker, side, quantity } });
}

/** Make sure a ticker is (or is not) on the watchlist, via the API. */
export async function ensureWatched(request: APIRequestContext, ticker: string, watched: boolean) {
  const current = await getWatchlist(request);
  if (watched && !current.includes(ticker)) {
    const res = await request.post("/api/watchlist", { data: { ticker } });
    expect([201, 409]).toContain(res.status());
  } else if (!watched && current.includes(ticker)) {
    const res = await request.delete(`/api/watchlist/${ticker}`);
    expect([200, 404]).toContain(res.status());
  }
}

/** Sell any held quantity of a ticker so tests start from a known state. */
export async function flatten(request: APIRequestContext, ticker: string) {
  const qty = positionQty(await getPortfolio(request), ticker);
  if (qty > 0) {
    const res = await trade(request, ticker, "sell", qty);
    expect(res.status(), await res.text()).toBe(200);
  }
}

/** Wait until the API has a live price for the ticker (the simulator needs a tick after an add). */
export async function waitForPrice(request: APIRequestContext, ticker: string) {
  await expect
    .poll(
      async () => {
        const res = await request.get("/api/watchlist");
        const body = await res.json();
        return body.tickers.find((t: { ticker: string }) => t.ticker === ticker)?.price ?? null;
      },
      { timeout: 15_000, message: `no live price for ${ticker}` },
    )
    .not.toBeNull();
}

/** Open the app and wait for the SSE connection to come up. Surfaces client-side exceptions. */
export async function openApp(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(`${err.message}\n${err.stack ?? ""}`));
  await page.goto("/");
  try {
    await expect(page.getByTestId("connection-status")).toHaveAttribute("data-status", "connected", {
      timeout: 20_000,
    });
  } catch (e) {
    if (errors.length) throw new Error(`App failed to load; page errors:\n${errors.join("\n---\n")}`);
    throw e;
  }
}

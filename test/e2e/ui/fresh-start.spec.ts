import { expect, test } from "@playwright/test";
import { DEFAULT_TICKERS, FRESH_DB, getPortfolio, moneyOf, openApp } from "../helpers";

test("fresh start: default watchlist, cash, live prices, connected", async ({ page, request }) => {
  await openApp(page);

  const watchlist = page.getByTestId("watchlist");
  await expect(watchlist).toBeVisible();
  for (const t of DEFAULT_TICKERS) {
    await expect(page.getByTestId(`watchlist-row-${t}`)).toBeVisible();
  }
  if (FRESH_DB) {
    await expect(watchlist.locator('[data-testid^="watchlist-row-"]')).toHaveCount(DEFAULT_TICKERS.length);
  }

  // Cash in the header matches the backend (exactly $10,000 on a fresh DB).
  const portfolio = await getPortfolio(request);
  const expectedCash = FRESH_DB ? 10_000 : portfolio.cash_balance;
  if (FRESH_DB) expect(portfolio.cash_balance).toBe(10_000);
  await expect.poll(() => moneyOf(page.getByTestId("header-cash"))).toBeCloseTo(expectedCash, 0);
  if (FRESH_DB) await expect(page.getByTestId("header-cash")).toContainText("10,000");
  await expect(page.getByTestId("header-total-value")).toBeVisible();

  // Prices are streaming: at least one watchlist price changes within a few seconds.
  const priceTexts = async () =>
    Promise.all(DEFAULT_TICKERS.map((t) => page.getByTestId(`watchlist-price-${t}`).innerText()));
  const first = await priceTexts();
  for (const p of first) expect(p).toMatch(/\d/);
  await expect
    .poll(async () => (await priceTexts()).some((p, i) => p !== first[i]), { timeout: 15_000 })
    .toBe(true);

  // Main chart and the other panels render.
  for (const id of ["main-chart", "positions-table", "heatmap", "pnl-chart", "chat-panel"]) {
    await expect(page.getByTestId(id), id).toBeVisible();
  }
});

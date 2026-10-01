import { expect, test } from "@playwright/test";
import { ensureWatched, getWatchlist, openApp } from "../helpers";

const T = "PYPL";

test.describe("watchlist UI", () => {
  test.beforeEach(async ({ request }) => {
    await ensureWatched(request, T, false);
  });

  test.afterAll(async ({ request }) => {
    await ensureWatched(request, T, false);
  });

  test("add a ticker, see it stream, then remove it", async ({ page, request }) => {
    await openApp(page);
    await expect(page.getByTestId(`watchlist-row-${T}`)).toHaveCount(0);

    await page.getByTestId("watchlist-add-input").fill(T.toLowerCase());
    await page.getByTestId("watchlist-add-button").click();

    const row = page.getByTestId(`watchlist-row-${T}`);
    await expect(row).toBeVisible();
    await expect(page.getByTestId(`watchlist-price-${T}`)).toHaveText(/\d/, { timeout: 15_000 });
    expect(await getWatchlist(request)).toContain(T);

    // Survives a reload (persisted server-side)
    await page.reload();
    await expect(page.getByTestId(`watchlist-row-${T}`)).toBeVisible();

    await page.getByTestId(`watchlist-remove-${T}`).click();
    await expect(page.getByTestId(`watchlist-row-${T}`)).toHaveCount(0);
    await expect.poll(() => getWatchlist(request)).not.toContain(T);
  });

  test("clicking a ticker selects it in the main chart", async ({ page }) => {
    await openApp(page);
    await page.getByTestId("watchlist-row-MSFT").click();
    await expect(page.getByTestId("selected-ticker")).toContainText("MSFT");
    await page.getByTestId("watchlist-row-TSLA").click();
    await expect(page.getByTestId("selected-ticker")).toContainText("TSLA");
    await expect(page.getByTestId("main-chart")).toBeVisible();
  });
});

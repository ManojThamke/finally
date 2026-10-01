import { expect, test } from "@playwright/test";
import { flatten, getPortfolio, moneyOf, openApp, positionQty, trade, waitForPrice } from "../helpers";

const T = "NVDA";

test.describe("trading UI", () => {
  test.beforeEach(async ({ request }) => {
    await waitForPrice(request, T);
    await flatten(request, T);
  });

  test.afterAll(async ({ request }) => {
    await flatten(request, T);
  });

  test("buy shares: cash decreases and position row appears", async ({ page, request }) => {
    await openApp(page);
    const cash = page.getByTestId("header-cash");
    const before = (await getPortfolio(request)).cash_balance;
    await expect.poll(() => moneyOf(cash)).toBeCloseTo(before, 0);
    await expect(page.getByTestId(`position-row-${T}`)).toHaveCount(0);

    await page.getByTestId("trade-ticker").fill(T);
    await page.getByTestId("trade-quantity").fill("3");
    await page.getByTestId("trade-buy").click();

    const row = page.getByTestId(`position-row-${T}`);
    await expect(row).toBeVisible();
    await expect(row).toContainText(T);
    await expect.poll(async () => parseFloat(await page.getByTestId(`position-qty-${T}`).innerText())).toBe(3);

    const after = await getPortfolio(request);
    expect(positionQty(after, T)).toBeCloseTo(3, 6);
    expect(after.cash_balance).toBeLessThan(before);
    await expect.poll(() => moneyOf(cash)).toBeCloseTo(after.cash_balance, 0);
    await expect(page.getByTestId("trade-error")).toHaveCount(0);
  });

  test("sell shares: cash increases, position updates then disappears", async ({ page, request }) => {
    const seeded = await trade(request, T, "buy", 4);
    expect(seeded.status(), await seeded.text()).toBe(200);

    await openApp(page);
    const cash = page.getByTestId("header-cash");
    const row = page.getByTestId(`position-row-${T}`);
    await expect(row).toBeVisible();
    const before = (await getPortfolio(request)).cash_balance;
    await expect.poll(() => moneyOf(cash)).toBeCloseTo(before, 0);

    await page.getByTestId("trade-ticker").fill(T);
    await page.getByTestId("trade-quantity").fill("1");
    await page.getByTestId("trade-sell").click();

    await expect.poll(async () => positionQty(await getPortfolio(request), T)).toBeCloseTo(3, 6);
    const mid = (await getPortfolio(request)).cash_balance;
    expect(mid).toBeGreaterThan(before);
    await expect.poll(() => moneyOf(cash)).toBeCloseTo(mid, 0);
    await expect.poll(async () => parseFloat(await page.getByTestId(`position-qty-${T}`).innerText())).toBe(3);

    await page.getByTestId("trade-quantity").fill("3");
    await page.getByTestId("trade-sell").click();
    await expect(row).toHaveCount(0);
    expect(positionQty(await getPortfolio(request), T)).toBe(0);
  });

  test("insufficient cash shows a trade error and changes nothing", async ({ page, request }) => {
    await openApp(page);
    const before = await getPortfolio(request);

    await page.getByTestId("trade-ticker").fill(T);
    await page.getByTestId("trade-quantity").fill("1000000");
    await page.getByTestId("trade-buy").click();

    await expect(page.getByTestId("trade-error")).toBeVisible();
    await expect(page.getByTestId("trade-error")).toContainText(/insufficient/i);
    const after = await getPortfolio(request);
    expect(after.cash_balance).toBeCloseTo(before.cash_balance, 6);
    await expect(page.getByTestId(`position-row-${T}`)).toHaveCount(0);
  });

  test("selling shares not owned shows a trade error", async ({ page }) => {
    await openApp(page);
    await page.getByTestId("trade-ticker").fill(T);
    await page.getByTestId("trade-quantity").fill("1");
    await page.getByTestId("trade-sell").click();
    await expect(page.getByTestId("trade-error")).toContainText(/insufficient/i);
  });
});

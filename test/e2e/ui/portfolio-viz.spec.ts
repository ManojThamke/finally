import { expect, test } from "@playwright/test";
import { flatten, openApp, trade, waitForPrice } from "../helpers";

const T = "META";

test.describe("portfolio visualizations", () => {
  test.beforeAll(async ({ request }) => {
    await waitForPrice(request, T);
    await flatten(request, T);
    const res = await trade(request, T, "buy", 2);
    expect(res.status(), await res.text()).toBe(200);
  });

  test.afterAll(async ({ request }) => {
    await flatten(request, T);
  });

  test("heatmap shows held positions", async ({ page }) => {
    await openApp(page);
    const heatmap = page.getByTestId("heatmap");
    await expect(heatmap).toBeVisible();
    await expect(heatmap).toContainText(T);
    const box = await heatmap.boundingBox();
    expect(box!.width).toBeGreaterThan(50);
    expect(box!.height).toBeGreaterThan(50);
    // Each position is a tile colored by P&L (green gain / red loss).
    const tile = page.getByTestId(`heatmap-tile-${T}`);
    await expect(tile).toBeVisible();
    const pnl = await tile.getAttribute("data-pnl");
    expect(["gain", "loss"]).toContain(pnl);
    const bg = await tile.evaluate((el) => getComputedStyle(el).backgroundColor);
    const [r, g] = (bg.match(/\d+(\.\d+)?/g) ?? []).map(Number);
    expect(bg, "tile has no background color").not.toMatch(/rgba\(0, 0, 0, 0\)|transparent/);
    if (pnl === "gain") expect(g, `gain tile should be green-ish, got ${bg}`).toBeGreaterThanOrEqual(r);
    else expect(r, `loss tile should be red-ish, got ${bg}`).toBeGreaterThanOrEqual(g);
  });

  test("P&L chart renders with snapshot data", async ({ page, request }) => {
    const res = await request.get("/api/portfolio/history");
    const { snapshots } = await res.json();
    expect(snapshots.length).toBeGreaterThan(0);

    await openApp(page);
    const chart = page.getByTestId("pnl-chart");
    await expect(chart).toBeVisible();
    // Frontend exposes the plotted point count.
    await expect.poll(async () => Number(await chart.getAttribute("data-points"))).toBeGreaterThan(0);
    // Charting library draws to canvas or SVG; either must be present and non-trivial in size.
    const drawn = chart.locator("canvas, svg").first();
    await expect(drawn).toBeVisible();
    const box = await drawn.boundingBox();
    expect(box!.width).toBeGreaterThan(50);
    expect(box!.height).toBeGreaterThan(30);
  });

  test("positions table lists the position with its columns", async ({ page }) => {
    await openApp(page);
    const row = page.getByTestId(`position-row-${T}`);
    await expect(row).toBeVisible();
    await expect(row).toContainText(T);
    await expect(row).toContainText("2");
    // ticker, qty, avg cost, current price, unrealized P&L, % change
    expect(await row.locator("td, [role=cell]").count()).toBeGreaterThanOrEqual(6);
  });

  test("header total value tracks cash + positions", async ({ page, request }) => {
    await openApp(page);
    const res = await request.get("/api/portfolio");
    const p = await res.json();
    const total = page.getByTestId("header-total-value");
    await expect(total).toHaveText(/\d/);
    const shown = parseFloat((await total.innerText()).replace(/[^0-9.\-]/g, ""));
    // Prices move continuously; allow 5% drift between the API read and the render.
    expect(Math.abs(shown - p.total_value) / p.total_value).toBeLessThan(0.05);
  });
});

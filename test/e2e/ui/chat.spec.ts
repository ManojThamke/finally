import { expect, test } from "@playwright/test";
import { getPortfolio, openApp, positionQty, waitForPrice } from "../helpers";

test.describe("AI chat (LLM_MOCK=true)", () => {
  test("plain message gets the mock response", async ({ page }) => {
    await openApp(page);
    const panel = page.getByTestId("chat-panel");
    await expect(panel).toBeVisible();

    const assistant = page.locator('[data-testid="chat-message"][data-role="assistant"]');
    const startCount = await assistant.count();

    await page.getByTestId("chat-input").fill("How is my portfolio doing?");
    await page.getByTestId("chat-send").click();

    await expect(
      page.locator('[data-testid="chat-message"][data-role="user"]').last(),
    ).toContainText("How is my portfolio doing?");
    await expect(assistant).toHaveCount(startCount + 1, { timeout: 20_000 });
    await expect(assistant.last()).toContainText("Mock response: I am FinAlly, your AI trading assistant.");
    await expect(page.getByTestId("chat-loading")).toHaveCount(0);
  });

  test("shows a loading indicator while waiting", async ({ page }) => {
    await openApp(page);
    // Slow the chat call down so the indicator is observable.
    await page.route("**/api/chat", async (route) => {
      await new Promise((r) => setTimeout(r, 1500));
      await route.continue();
    });
    await page.getByTestId("chat-input").fill("hello");
    await page.getByTestId("chat-send").click();
    await expect(page.getByTestId("chat-loading")).toBeVisible();
    await expect(page.getByTestId("chat-loading")).toHaveCount(0, { timeout: 20_000 });
  });

  test("'buy 1 AAPL' executes a trade shown inline and in positions", async ({ page, request }) => {
    await waitForPrice(request, "AAPL");
    const before = positionQty(await getPortfolio(request), "AAPL");
    await openApp(page);

    const actions = page.getByTestId("chat-action");
    const startActions = await actions.count();

    await page.getByTestId("chat-input").fill("buy 1 AAPL");
    await page.getByTestId("chat-send").click();

    await expect(
      page.locator('[data-testid="chat-message"][data-role="assistant"]').last(),
    ).toContainText("Mock: buying 1 AAPL.", { timeout: 20_000 });
    await expect(actions).toHaveCount(startActions + 1);
    await expect(actions.last()).toContainText("AAPL");
    await expect(actions.last()).toContainText(/buy/i);
    await expect(actions.last()).toHaveAttribute("data-status", "executed");

    await expect(page.getByTestId("position-row-AAPL")).toBeVisible();
    expect(positionQty(await getPortfolio(request), "AAPL")).toBeCloseTo(before + 1, 6);
  });

  test("chat history is restored after reload", async ({ page }) => {
    await openApp(page);
    const marker = `remember me ${Date.now()}`;
    await page.getByTestId("chat-input").fill(marker);
    await page.getByTestId("chat-send").click();
    const assistant = page.locator('[data-testid="chat-message"][data-role="assistant"]');
    await expect(assistant.last()).toContainText("Mock response", { timeout: 20_000 });

    await page.reload();
    await expect(
      page.locator('[data-testid="chat-message"][data-role="user"]', { hasText: marker }),
    ).toBeVisible({ timeout: 15_000 });
  });
});

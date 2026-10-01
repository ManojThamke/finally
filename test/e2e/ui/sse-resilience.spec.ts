import { expect, test } from "@playwright/test";
import { openApp } from "../helpers";

test("SSE resilience: status leaves 'connected' on loss and recovers", async ({ page }) => {
  // Track EventSource instances so the live stream can be dropped from the page. (Browser offline
  // emulation does not tear down an already-open stream, so we simulate the drop directly.)
  await page.addInitScript(() => {
    const Native = window.EventSource;
    const live: EventSource[] = [];
    class Tracked extends Native {
      constructor(url: string | URL, init?: EventSourceInit) {
        super(url, init);
        live.push(this);
      }
    }
    window.EventSource = Tracked as typeof EventSource;
    (window as unknown as { __dropStreams: () => void }).__dropStreams = () => {
      for (const es of live.splice(0)) {
        es.close();
        es.dispatchEvent(new Event("error"));
      }
    };
  });

  let blocked = false;
  await page.route("**/api/stream/prices", (route) => (blocked ? route.abort("internetdisconnected") : route.continue()));

  await openApp(page);
  const status = page.getByTestId("connection-status");

  // Lose the connection; every reconnect attempt is refused while blocked.
  blocked = true;
  await page.evaluate(() => (window as unknown as { __dropStreams: () => void }).__dropStreams());
  await expect(status).toHaveAttribute("data-status", /reconnecting|disconnected/, { timeout: 10_000 });
  // Stays down while the server is unreachable (survives at least one retry cycle).
  await page.waitForTimeout(4_000);
  await expect(status).not.toHaveAttribute("data-status", "connected");

  // Restore: the client retries on its own and the indicator returns to connected.
  blocked = false;
  await expect(status).toHaveAttribute("data-status", "connected", { timeout: 30_000 });

  // Prices flow again after reconnection.
  const tickers = ["AAPL", "GOOGL", "MSFT", "TSLA", "NVDA"];
  const snapshot = () => Promise.all(tickers.map((t) => page.getByTestId(`watchlist-price-${t}`).innerText()));
  const first = await snapshot();
  await expect.poll(async () => (await snapshot()).some((p, i) => p !== first[i]), { timeout: 15_000 }).toBe(true);
});

test("SSE resilience: server-closed stream is reconnected automatically", async ({ page }) => {
  // First connection gets a short, complete response (server "drops" it); later ones pass through.
  let served = 0;
  await page.route("**/api/stream/prices", async (route) => {
    served += 1;
    if (served === 1) {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "text/event-stream", "cache-control": "no-cache" },
        body: "retry: 500\n\n",
      });
    } else {
      await route.continue();
    }
  });

  await page.goto("/");
  await expect(page.getByTestId("connection-status")).toHaveAttribute("data-status", "connected", {
    timeout: 30_000,
  });
  await expect.poll(() => served, { timeout: 15_000 }).toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId("watchlist-price-AAPL")).toHaveText(/\d/);
});

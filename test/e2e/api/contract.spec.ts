import { expect, test } from "@playwright/test";
import {
  DEFAULT_TICKERS,
  ensureWatched,
  flatten,
  getPortfolio,
  getWatchlist,
  positionQty,
  trade,
  waitForPrice,
} from "../helpers";

test.describe("health", () => {
  test("GET /api/health returns ok", async ({ request }) => {
    const res = await request.get("/api/health");
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.status).toBe("ok");
  });
});

test.describe("watchlist API", () => {
  const T = "PYPL";

  test.beforeEach(async ({ request }) => {
    await ensureWatched(request, T, false);
  });

  test.afterAll(async ({ request }) => {
    await ensureWatched(request, T, false);
  });

  test("GET returns default tickers with price fields", async ({ request }) => {
    const res = await request.get("/api/watchlist");
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body.tickers)).toBe(true);
    const tickers = body.tickers.map((t: { ticker: string }) => t.ticker);
    for (const d of DEFAULT_TICKERS) expect(tickers).toContain(d);
    const aapl = body.tickers.find((t: { ticker: string }) => t.ticker === "AAPL");
    for (const key of ["ticker", "price", "previous_price", "change", "change_percent", "direction"]) {
      expect(aapl).toHaveProperty(key);
    }
    expect(typeof aapl.price).toBe("number");
  });

  test("POST adds (201), duplicate is 409, DELETE removes (200), missing is 404", async ({ request }) => {
    let res = await request.post("/api/watchlist", { data: { ticker: T } });
    expect(res.status()).toBe(201);
    expect(await res.json()).toMatchObject({ ticker: T, added: true });
    expect(await getWatchlist(request)).toContain(T);

    res = await request.post("/api/watchlist", { data: { ticker: T } });
    expect(res.status()).toBe(409);
    expect(await res.json()).toHaveProperty("detail");

    res = await request.delete(`/api/watchlist/${T}`);
    expect(res.status()).toBe(200);
    expect(await res.json()).toMatchObject({ ticker: T, removed: true });
    expect(await getWatchlist(request)).not.toContain(T);

    res = await request.delete(`/api/watchlist/${T}`);
    expect(res.status()).toBe(404);
    expect(await res.json()).toHaveProperty("detail");
  });

  test("POST normalizes lower-case tickers", async ({ request }) => {
    const res = await request.post("/api/watchlist", { data: { ticker: " pypl " } });
    expect(res.status()).toBe(201);
    expect((await res.json()).ticker).toBe(T);
  });

  test("POST rejects invalid tickers with 400", async ({ request }) => {
    for (const bad of ["", "   ", "TOOLONGTICKER", "AB1", "A$B"]) {
      const res = await request.post("/api/watchlist", { data: { ticker: bad } });
      expect(res.status(), `ticker=${JSON.stringify(bad)}`).toBe(400);
      expect(await res.json()).toHaveProperty("detail");
    }
  });

  test("POST with malformed body is 422", async ({ request }) => {
    const res = await request.post("/api/watchlist", { data: { nope: 1 } });
    expect(res.status()).toBe(422);
  });
});

test.describe("portfolio API", () => {
  const T = "MSFT";

  test.beforeAll(async ({ request }) => {
    await waitForPrice(request, T);
  });

  test("GET /api/portfolio has the contract shape", async ({ request }) => {
    const p = await getPortfolio(request);
    for (const key of ["cash_balance", "positions_value", "total_value", "unrealized_pnl", "unrealized_pnl_percent"]) {
      expect(typeof (p as unknown as Record<string, unknown>)[key], key).toBe("number");
    }
    expect(Array.isArray(p.positions)).toBe(true);
    expect(p.total_value).toBeCloseTo(p.cash_balance + p.positions_value, 2);
  });

  test("buy then sell updates cash and position", async ({ request }) => {
    await flatten(request, T);
    const before = await getPortfolio(request);

    let res = await trade(request, T, "buy", 2);
    expect(res.status(), await res.text()).toBe(200);
    let body = await res.json();
    expect(body.trade).toMatchObject({ ticker: T, side: "buy", quantity: 2 });
    for (const key of ["id", "price", "executed_at"]) expect(body.trade).toHaveProperty(key);
    const buyPrice: number = body.trade.price;
    expect(body.portfolio.cash_balance).toBeCloseTo(before.cash_balance - 2 * buyPrice, 2);
    const pos = body.portfolio.positions.find((x: { ticker: string }) => x.ticker === T);
    expect(pos).toBeTruthy();
    expect(pos.quantity).toBeCloseTo(2, 6);
    expect(pos.avg_cost).toBeCloseTo(buyPrice, 4);
    for (const key of ["current_price", "market_value", "unrealized_pnl", "unrealized_pnl_percent", "weight"]) {
      expect(pos).toHaveProperty(key);
    }

    // Partial sell keeps the position
    res = await trade(request, T, "sell", 1);
    expect(res.status(), await res.text()).toBe(200);
    body = await res.json();
    expect(positionQty(body.portfolio, T)).toBeCloseTo(1, 6);

    // Full sell removes it
    res = await trade(request, T, "sell", 1);
    expect(res.status(), await res.text()).toBe(200);
    body = await res.json();
    expect(body.portfolio.positions.find((x: { ticker: string }) => x.ticker === T)).toBeUndefined();
  });

  test("fractional quantities are supported", async ({ request }) => {
    await flatten(request, T);
    let res = await trade(request, T, "buy", 0.5);
    expect(res.status(), await res.text()).toBe(200);
    expect(positionQty((await res.json()).portfolio, T)).toBeCloseTo(0.5, 6);
    res = await trade(request, T, "sell", 0.5);
    expect(res.status(), await res.text()).toBe(200);
  });

  test("lower-case ticker is normalized on trade", async ({ request }) => {
    await flatten(request, T);
    const res = await trade(request, T.toLowerCase(), "buy", 1);
    expect(res.status(), await res.text()).toBe(200);
    expect((await res.json()).trade.ticker).toBe(T);
    await flatten(request, T);
  });

  test("insufficient cash is 400 and leaves state unchanged", async ({ request }) => {
    const before = await getPortfolio(request);
    const res = await trade(request, T, "buy", 10_000_000);
    expect(res.status()).toBe(400);
    expect((await res.json()).detail).toMatch(/insufficient cash/i);
    const after = await getPortfolio(request);
    expect(after.cash_balance).toBeCloseTo(before.cash_balance, 6);
    expect(positionQty(after, T)).toBeCloseTo(positionQty(before, T), 6);
  });

  test("selling more than owned is 400", async ({ request }) => {
    await flatten(request, T);
    const res = await trade(request, T, "sell", 1);
    expect(res.status()).toBe(400);
    expect((await res.json()).detail).toMatch(/insufficient shares/i);
  });

  test("non-positive quantity is rejected", async ({ request }) => {
    for (const q of [0, -5]) {
      const res = await trade(request, T, "buy", q);
      expect([400, 422], `quantity=${q}`).toContain(res.status());
    }
  });

  test("malformed trade body is 422", async ({ request }) => {
    let res = await request.post("/api/portfolio/trade", { data: { ticker: T, side: "hold", quantity: 1 } });
    expect([400, 422]).toContain(res.status());
    res = await request.post("/api/portfolio/trade", { data: { ticker: T } });
    expect(res.status()).toBe(422);
  });

  test("trading an unpriced ticker is 400", async ({ request }) => {
    const res = await trade(request, "ZZZZQ", "buy", 1);
    expect(res.status()).toBe(400);
    expect(await res.json()).toHaveProperty("detail");
  });

  test("history returns snapshots oldest first and grows after a trade", async ({ request }) => {
    const get = async () => {
      const res = await request.get("/api/portfolio/history");
      expect(res.status()).toBe(200);
      const body = await res.json();
      expect(Array.isArray(body.snapshots)).toBe(true);
      return body.snapshots as { total_value: number; recorded_at: string }[];
    };
    const before = await get();
    const r1 = await trade(request, T, "buy", 1);
    expect(r1.status()).toBe(200);
    await flatten(request, T);
    const after = await get();
    expect(after.length).toBeGreaterThan(before.length);
    for (const s of after) {
      expect(typeof s.total_value).toBe("number");
      expect(typeof s.recorded_at).toBe("string");
    }
    const times = after.map((s) => Date.parse(s.recorded_at));
    for (let i = 1; i < times.length; i++) expect(times[i]).toBeGreaterThanOrEqual(times[i - 1]);
  });
});

test.describe("chat API (LLM_MOCK=true)", () => {
  test("plain message returns the deterministic mock response", async ({ request }) => {
    const res = await request.post("/api/chat", { data: { message: "hello there" } });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.role).toBe("assistant");
    expect(body.message).toBe("Mock response: I am FinAlly, your AI trading assistant.");
    for (const key of ["id", "created_at", "trades", "watchlist_changes"]) expect(body).toHaveProperty(key);
    expect(body.trades).toEqual([]);
    expect(body.watchlist_changes).toEqual([]);
  });

  test("empty message is 400", async ({ request }) => {
    const res = await request.post("/api/chat", { data: { message: "   " } });
    expect(res.status()).toBe(400);
  });

  test("'buy 1 AAPL' executes a trade", async ({ request }) => {
    await waitForPrice(request, "AAPL");
    const before = await getPortfolio(request);
    const res = await request.post("/api/chat", { data: { message: "buy 1 AAPL" } });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.message).toBe("Mock: buying 1 AAPL.");
    expect(body.trades).toHaveLength(1);
    expect(body.trades[0]).toMatchObject({ ticker: "AAPL", side: "buy", quantity: 1, status: "executed", error: null });
    expect(typeof body.trades[0].price).toBe("number");
    const after = await getPortfolio(request);
    expect(positionQty(after, "AAPL")).toBeCloseTo(positionQty(before, "AAPL") + 1, 6);
    expect(after.cash_balance).toBeLessThan(before.cash_balance);
  });

  test("'sell' more than owned reports a failed trade, not an error", async ({ request }) => {
    const res = await request.post("/api/chat", { data: { message: "sell 99999 NFLX" } });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.trades).toHaveLength(1);
    expect(body.trades[0]).toMatchObject({ ticker: "NFLX", side: "sell", status: "failed" });
    expect(body.trades[0].error).toBeTruthy();
  });

  test("'add'/'remove' TICKER changes the watchlist", async ({ request }) => {
    await ensureWatched(request, "PYPL", false);
    let res = await request.post("/api/chat", { data: { message: "add PYPL" } });
    expect(res.status()).toBe(200);
    let body = await res.json();
    expect(body.watchlist_changes[0]).toMatchObject({ ticker: "PYPL", action: "add", status: "executed" });
    expect(await getWatchlist(request)).toContain("PYPL");

    res = await request.post("/api/chat", { data: { message: "remove PYPL" } });
    expect(res.status()).toBe(200);
    body = await res.json();
    expect(body.watchlist_changes[0]).toMatchObject({ ticker: "PYPL", action: "remove", status: "executed" });
    expect(await getWatchlist(request)).not.toContain("PYPL");
  });

  test("history contains user and assistant messages oldest first", async ({ request }) => {
    const marker = `history check ${Date.now()}`;
    await request.post("/api/chat", { data: { message: marker } });
    const res = await request.get("/api/chat/history");
    expect(res.status()).toBe(200);
    const { messages } = await res.json();
    expect(Array.isArray(messages)).toBe(true);
    const idx = messages.findIndex((m: { role: string; content: string }) => m.role === "user" && m.content === marker);
    expect(idx).toBeGreaterThanOrEqual(0);
    expect(messages[idx + 1]?.role).toBe("assistant");
    for (const key of ["id", "role", "content", "actions", "created_at"]) expect(messages[idx]).toHaveProperty(key);
  });
});

test.describe("SSE stream", () => {
  test("GET /api/stream/prices emits price events in the contract shape", async ({ page, baseURL }) => {
    // APIRequestContext buffers the whole body, so read the stream with fetch() in a browser.
    await page.goto(`${baseURL}/api/health`);
    const payload = await page.evaluate(async () => {
      const ctrl = new AbortController();
      const res = await fetch("/api/stream/prices", { signal: ctrl.signal });
      const reader = res.body!.getReader();
      const dec = new TextDecoder();
      let buf = "";
      const deadline = Date.now() + 10_000;
      while (Date.now() < deadline) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const m = buf.match(/event: prices\ndata: (.*)\n\n/);
        if (m) {
          ctrl.abort();
          return { contentType: res.headers.get("content-type"), data: JSON.parse(m[1]) };
        }
      }
      ctrl.abort();
      return null;
    });
    expect(payload, "no prices event within 10s").not.toBeNull();
    expect(payload!.contentType).toContain("text/event-stream");
    const aapl = payload!.data.AAPL;
    expect(aapl).toBeTruthy();
    for (const key of ["ticker", "price", "previous_price", "timestamp", "change", "change_percent", "direction"]) {
      expect(aapl).toHaveProperty(key);
    }
    expect(["up", "down", "flat"]).toContain(aapl.direction);
  });
});

test.describe("static frontend", () => {
  test("/ serves the app and unknown paths fall back to index.html", async ({ request }) => {
    let res = await request.get("/");
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("text/html");
    res = await request.get("/some/client/route");
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("text/html");
    res = await request.get("/api/does-not-exist");
    expect(res.status()).toBe(404);
  });
});

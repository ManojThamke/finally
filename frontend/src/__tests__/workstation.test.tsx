import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Workstation from "@/components/Workstation";

class MockEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static instances: MockEventSource[] = [];
  readyState = 0;
  url: string;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(fn);
  }
  removeEventListener() {}
  close() {
    this.readyState = 2;
  }
  emitPrices(data: unknown) {
    const ev = { data: JSON.stringify(data) } as MessageEvent;
    this.listeners.prices?.forEach((fn) => fn(ev));
  }
}

let portfolio = {
  cash_balance: 10000,
  positions_value: 0,
  total_value: 10000,
  unrealized_pnl: 0,
  unrealized_pnl_percent: 0,
  positions: [] as unknown[],
};
let watch = ["AAPL", "MSFT"];
let chatResolve: ((v: Response) => void) | null = null;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  MockEventSource.instances = [];
  vi.stubGlobal("EventSource", MockEventSource);
  watch = ["AAPL", "MSFT"];
  portfolio = { ...portfolio, cash_balance: 10000, positions: [] };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url === "/api/watchlist" && method === "GET") return json({ tickers: watch.map((ticker) => ({ ticker, price: null })) });
      if (url === "/api/watchlist" && method === "POST") {
        const { ticker } = JSON.parse(String(init!.body));
        watch = [...watch, ticker];
        return json({ ticker, added: true }, 201);
      }
      if (url.startsWith("/api/watchlist/") && method === "DELETE") {
        const t = url.split("/").pop()!;
        watch = watch.filter((x) => x !== t);
        return json({ ticker: t, removed: true });
      }
      if (url === "/api/portfolio") return json(portfolio);
      if (url === "/api/portfolio/history") return json({ snapshots: [{ total_value: 10000, recorded_at: "2026-01-01T00:00:00Z" }] });
      if (url === "/api/chat/history") return json({ messages: [] });
      if (url === "/api/portfolio/trade") {
        const body = JSON.parse(String(init!.body));
        if (body.quantity > 100) return json({ detail: "Insufficient cash" }, 400);
        portfolio = {
          ...portfolio,
          cash_balance: 10000 - body.quantity * 190,
          positions: [
            { ticker: body.ticker, quantity: body.quantity, avg_cost: 190, current_price: 190, market_value: 190 * body.quantity, unrealized_pnl: 0, unrealized_pnl_percent: 0, weight: 0 },
          ],
        };
        return json({ trade: { id: "t1", ticker: body.ticker, side: body.side, quantity: body.quantity, price: 190, executed_at: "" }, portfolio });
      }
      if (url === "/api/chat") return new Promise<Response>((r) => (chatResolve = r));
      return json({ detail: "not found" }, 404);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Workstation", () => {
  it("loads data, streams prices and updates connection status", async () => {
    render(<Workstation />);
    expect(await screen.findByTestId("watchlist-row-AAPL")).toBeInTheDocument();
    expect(screen.getByTestId("header-cash")).toHaveTextContent("$10,000.00");
    expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", "reconnecting");
    await waitFor(() => expect(screen.getByTestId("selected-ticker")).toHaveTextContent("AAPL"));

    const es = MockEventSource.instances[0];
    expect(es.url).toBe("/api/stream/prices");
    act(() => {
      es.emitPrices({ AAPL: { ticker: "AAPL", price: 191.25, previous_price: 191, timestamp: 1, direction: "up", day_change_percent: 0.5 } });
    });
    expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", "connected");
    expect(screen.getByTestId("watchlist-price-AAPL")).toHaveTextContent("191.25");
  });

  it("adds and removes watchlist tickers", async () => {
    render(<Workstation />);
    await screen.findByTestId("watchlist-row-AAPL");
    const user = userEvent.setup();
    await user.type(screen.getByTestId("watchlist-add-input"), "PYPL");
    await user.click(screen.getByTestId("watchlist-add-button"));
    expect(await screen.findByTestId("watchlist-row-PYPL")).toBeInTheDocument();
    await user.click(screen.getByTestId("watchlist-remove-MSFT"));
    await waitFor(() => expect(screen.queryByTestId("watchlist-row-MSFT")).not.toBeInTheDocument());
  });

  it("executes a trade and refreshes cash + positions", async () => {
    render(<Workstation />);
    await screen.findByTestId("watchlist-row-AAPL");
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByTestId("trade-ticker")).toHaveValue("AAPL"));
    await user.type(screen.getByTestId("trade-quantity"), "500");
    await user.click(screen.getByTestId("trade-buy"));
    expect(await screen.findByTestId("trade-error")).toHaveTextContent("Insufficient cash");

    await user.clear(screen.getByTestId("trade-quantity"));
    await user.type(screen.getByTestId("trade-quantity"), "10");
    await user.click(screen.getByTestId("trade-buy"));
    expect(await screen.findByTestId("position-row-AAPL")).toBeInTheDocument();
    expect(screen.getByTestId("header-cash")).toHaveTextContent("$8,100.00");
    expect(screen.getByTestId("header-total-value")).toHaveTextContent("$10,000.00");
  });

  it("shows chat loading state then the assistant reply with actions", async () => {
    render(<Workstation />);
    await screen.findByTestId("watchlist-row-AAPL");
    const user = userEvent.setup();
    await user.type(screen.getByTestId("chat-input"), "buy 5 AAPL");
    await user.click(screen.getByTestId("chat-send"));
    expect(await screen.findByTestId("chat-loading")).toBeInTheDocument();
    expect(screen.getAllByTestId("chat-message")[0]).toHaveAttribute("data-role", "user");

    await act(async () => {
      chatResolve!(
        json({
          id: "a1",
          role: "assistant",
          message: "Mock: buying 5 AAPL.",
          created_at: "",
          trades: [{ ticker: "AAPL", side: "buy", quantity: 5, status: "executed", price: 190, error: null }],
          watchlist_changes: [],
        }),
      );
    });
    await waitFor(() => expect(screen.queryByTestId("chat-loading")).not.toBeInTheDocument());
    expect(screen.getAllByTestId("chat-message")[1]).toHaveTextContent("Mock: buying 5 AAPL.");
    expect(screen.getByTestId("chat-action")).toHaveAttribute("data-status", "executed");
  });
});

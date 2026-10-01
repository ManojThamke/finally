import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import WatchlistRow, { FLASH_MS } from "@/components/WatchlistRow";
import Watchlist from "@/components/Watchlist";
import Header from "@/components/Header";
import PositionsTable from "@/components/PositionsTable";
import Heatmap from "@/components/Heatmap";
import ChatPanel from "@/components/ChatPanel";
import TradeBar from "@/components/TradeBar";
import type { ChatMessage, Position, PriceMap } from "@/types";

afterEach(() => {
  vi.useRealTimers();
});

const rowProps = {
  ticker: "AAPL",
  dayChangePercent: 1.5,
  points: [],
  selected: false,
  version: 0,
  onSelect: () => {},
  onRemove: () => {},
};

describe("WatchlistRow price flash", () => {
  it("flashes green on uptick and clears after ~500ms", () => {
    vi.useFakeTimers();
    const { rerender } = render(<WatchlistRow {...rowProps} price={100} />);
    const cell = screen.getByTestId("watchlist-price-AAPL");
    expect(cell).toHaveTextContent("100.00");
    expect(cell.className).not.toMatch(/flash-/);

    rerender(<WatchlistRow {...rowProps} price={101} />);
    expect(cell).toHaveClass("flash-up");
    expect(cell).toHaveAttribute("data-flash", "up");

    act(() => {
      vi.advanceTimersByTime(FLASH_MS + 10);
    });
    expect(cell.className).not.toMatch(/flash-/);
  });

  it("flashes red on downtick", () => {
    const { rerender } = render(<WatchlistRow {...rowProps} price={100} />);
    rerender(<WatchlistRow {...rowProps} price={99} />);
    expect(screen.getByTestId("watchlist-price-AAPL")).toHaveClass("flash-down");
  });

  it("does not flash on first price or unchanged price", () => {
    const { rerender } = render(<WatchlistRow {...rowProps} price={null} />);
    rerender(<WatchlistRow {...rowProps} price={100} />);
    expect(screen.getByTestId("watchlist-price-AAPL").className).not.toMatch(/flash-/);
  });
});

describe("Watchlist", () => {
  const prices: PriceMap = {
    AAPL: { ticker: "AAPL", price: 190.5, previous_price: 190, timestamp: 1, direction: "up", day_change_percent: 0.8 },
  };

  it("renders rows, selects, adds and removes tickers", async () => {
    const onAdd = vi.fn().mockResolvedValue(undefined);
    const onRemove = vi.fn().mockResolvedValue(undefined);
    const onSelect = vi.fn();
    render(
      <Watchlist
        tickers={["AAPL", "MSFT"]}
        prices={prices}
        history={{}}
        version={0}
        selected="AAPL"
        onSelect={onSelect}
        onAdd={onAdd}
        onRemove={onRemove}
      />,
    );
    expect(screen.getByTestId("watchlist-row-AAPL")).toBeInTheDocument();
    expect(screen.getByTestId("watchlist-price-AAPL")).toHaveTextContent("190.50");
    expect(screen.getByTestId("watchlist-price-MSFT")).toHaveTextContent("—");

    fireEvent.click(screen.getByTestId("watchlist-row-MSFT"));
    expect(onSelect).toHaveBeenCalledWith("MSFT");

    fireEvent.click(screen.getByTestId("watchlist-remove-MSFT"));
    expect(onRemove).toHaveBeenCalledWith("MSFT");
    expect(onSelect).toHaveBeenCalledTimes(1); // remove click doesn't select

    const user = userEvent.setup();
    await user.type(screen.getByTestId("watchlist-add-input"), "pypl");
    await user.click(screen.getByTestId("watchlist-add-button"));
    expect(onAdd).toHaveBeenCalledWith("PYPL");
    await waitFor(() => expect(screen.getByTestId("watchlist-add-input")).toHaveValue(""));
  });

  it("shows an error when adding fails", async () => {
    const onAdd = vi.fn().mockRejectedValue(new Error("Ticker already in watchlist"));
    render(
      <Watchlist tickers={[]} prices={{}} history={{}} version={0} selected={null} onSelect={() => {}} onAdd={onAdd} onRemove={vi.fn()} />,
    );
    const user = userEvent.setup();
    await user.type(screen.getByTestId("watchlist-add-input"), "AAPL");
    await user.click(screen.getByTestId("watchlist-add-button"));
    expect(await screen.findByRole("alert")).toHaveTextContent("already");
  });
});

describe("Header", () => {
  it("shows values and connection status", () => {
    render(
      <Header
        totalValue={10250.5}
        cash={8000}
        unrealizedPnl={250.5}
        unrealizedPnlPercent={2.5}
        status="reconnecting"
        chatOpen
        onToggleChat={() => {}}
      />,
    );
    expect(screen.getByTestId("header-total-value")).toHaveTextContent("$10,250.50");
    expect(screen.getByTestId("header-cash")).toHaveTextContent("$8,000.00");
    expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", "reconnecting");
  });
});

const positions: Position[] = [
  { ticker: "AAPL", quantity: 10, avg_cost: 100, current_price: 110, market_value: 1100, unrealized_pnl: 100, unrealized_pnl_percent: 10, weight: 11 },
  { ticker: "TSLA", quantity: 2, avg_cost: 250, current_price: 200, market_value: 400, unrealized_pnl: -100, unrealized_pnl_percent: -20, weight: 4 },
];

describe("PositionsTable", () => {
  it("renders positions sorted by market value with P&L", () => {
    render(<PositionsTable positions={positions} />);
    const rows = screen.getAllByTestId(/^position-row-/);
    expect(rows.map((r) => r.dataset.testid)).toEqual(["position-row-AAPL", "position-row-TSLA"]);
    expect(rows[0]).toHaveTextContent("+$100.00");
    expect(rows[1]).toHaveTextContent("−$100.00");
    expect(rows[1]).toHaveTextContent("−20.00%");
  });

  it("renders an empty state", () => {
    render(<PositionsTable positions={[]} />);
    expect(screen.getByTestId("positions-table")).toHaveTextContent("No open positions");
  });
});

describe("Heatmap", () => {
  it("renders a tile per position coloured by P&L", () => {
    render(<Heatmap positions={positions} />);
    expect(screen.getByTestId("heatmap-tile-AAPL")).toHaveAttribute("data-pnl", "gain");
    expect(screen.getByTestId("heatmap-tile-TSLA")).toHaveAttribute("data-pnl", "loss");
  });
});

describe("TradeBar", () => {
  it("submits a trade and shows API errors", async () => {
    const onTrade = vi.fn().mockRejectedValueOnce(new Error("Insufficient cash")).mockResolvedValueOnce({ price: 190 });
    render(<TradeBar selectedTicker="AAPL" onTrade={onTrade} />);
    expect(screen.getByTestId("trade-ticker")).toHaveValue("AAPL");
    const user = userEvent.setup();
    await user.type(screen.getByTestId("trade-quantity"), "1000");
    await user.click(screen.getByTestId("trade-buy"));
    expect(onTrade).toHaveBeenCalledWith("AAPL", 1000, "buy");
    expect(await screen.findByTestId("trade-error")).toHaveTextContent("Insufficient cash");

    await user.click(screen.getByTestId("trade-sell"));
    expect(onTrade).toHaveBeenLastCalledWith("AAPL", 1000, "sell");
    await waitFor(() => expect(screen.queryByTestId("trade-error")).not.toBeInTheDocument());
  });

  it("validates quantity locally", async () => {
    const onTrade = vi.fn();
    render(<TradeBar selectedTicker="AAPL" onTrade={onTrade} />);
    await userEvent.setup().click(screen.getByTestId("trade-buy"));
    expect(onTrade).not.toHaveBeenCalled();
    expect(screen.getByTestId("trade-error")).toBeInTheDocument();
  });
});

describe("ChatPanel", () => {
  const messages: ChatMessage[] = [
    { id: "1", role: "user", content: "buy 5 AAPL", created_at: "", trades: [], watchlist_changes: [] },
    {
      id: "2",
      role: "assistant",
      content: "Mock: buying 5 AAPL.",
      created_at: "",
      trades: [
        { ticker: "AAPL", side: "buy", quantity: 5, status: "executed", price: 190.1, error: null },
        { ticker: "TSLA", side: "sell", quantity: 5, status: "failed", error: "Insufficient shares" },
      ],
      watchlist_changes: [{ ticker: "PYPL", action: "add", status: "executed", error: null }],
    },
  ];

  it("renders messages and inline action confirmations", () => {
    render(<ChatPanel messages={messages} loading={false} error={null} onSend={() => {}} onClose={() => {}} />);
    const msgs = screen.getAllByTestId("chat-message");
    expect(msgs.map((m) => m.dataset.role)).toEqual(["user", "assistant"]);
    const actions = screen.getAllByTestId("chat-action");
    expect(actions).toHaveLength(3);
    expect(actions[0]).toHaveTextContent("BUY 5 AAPL @ 190.10");
    expect(actions[1]).toHaveAttribute("data-status", "failed");
    expect(actions[1]).toHaveTextContent("Insufficient shares");
    expect(actions[2]).toHaveTextContent("PYPL");
    expect(screen.queryByTestId("chat-loading")).not.toBeInTheDocument();
  });

  it("shows loading indicator and disables send", () => {
    render(<ChatPanel messages={messages} loading error={null} onSend={() => {}} onClose={() => {}} />);
    expect(screen.getByTestId("chat-loading")).toBeInTheDocument();
    expect(screen.getByTestId("chat-send")).toBeDisabled();
  });

  it("sends on Enter and clears the input", async () => {
    const onSend = vi.fn();
    render(<ChatPanel messages={[]} loading={false} error={null} onSend={onSend} onClose={() => {}} />);
    const user = userEvent.setup();
    await user.type(screen.getByTestId("chat-input"), "hello{Enter}");
    expect(onSend).toHaveBeenCalledWith("hello");
    expect(screen.getByTestId("chat-input")).toHaveValue("");
  });
});

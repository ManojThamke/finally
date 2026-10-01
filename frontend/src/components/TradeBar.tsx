"use client";

import { useEffect, useState } from "react";
import type { TradeSide } from "@/types";
import { normalizeTicker } from "@/utils/chat";
import { formatPrice, formatQty } from "@/utils/format";

interface Props {
  selectedTicker: string | null;
  onTrade: (ticker: string, quantity: number, side: TradeSide) => Promise<{ price: number } | void>;
}

export default function TradeBar({ selectedTicker, onTrade }: Props) {
  const [ticker, setTicker] = useState(selectedTicker ?? "");
  const [qty, setQty] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<TradeSide | null>(null);

  // Clicking a ticker elsewhere pre-fills the trade ticker.
  useEffect(() => {
    if (selectedTicker) setTicker(selectedTicker);
  }, [selectedTicker]);

  const submit = async (side: TradeSide) => {
    const t = normalizeTicker(ticker);
    const q = Number(qty);
    setError(null);
    setNotice(null);
    if (!t) return setError("Enter a ticker");
    if (!qty.trim() || !Number.isFinite(q) || q <= 0) return setError("Enter a quantity greater than 0");
    setBusy(side);
    try {
      const res = await onTrade(t, q, side);
      setNotice(
        `${side === "buy" ? "Bought" : "Sold"} ${formatQty(q)} ${t}${res && "price" in res ? ` @ ${formatPrice(res.price)}` : ""}`,
      );
      setQty("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="panel">
      <form
        className="flex flex-wrap items-center gap-2 px-3 py-2"
        onSubmit={(e) => {
          e.preventDefault();
          void submit("buy");
        }}
      >
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-ink-300">
          Order <span className="text-accent">· MKT</span>
        </span>
        <input
          data-testid="trade-ticker"
          aria-label="Trade ticker"
          placeholder="TICKER"
          value={ticker}
          maxLength={10}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          className="input w-24 uppercase"
        />
        <input
          data-testid="trade-quantity"
          aria-label="Trade quantity"
          placeholder="Qty"
          inputMode="decimal"
          type="number"
          min="0"
          step="any"
          value={qty}
          onChange={(e) => setQty(e.target.value)}
          className="input w-24"
        />
        <button
          data-testid="trade-buy"
          type="button"
          disabled={busy !== null}
          onClick={() => void submit("buy")}
          className="btn bg-up/15 text-up ring-1 ring-inset ring-up/40 hover:bg-up/25"
        >
          {busy === "buy" ? "…" : "Buy"}
        </button>
        <button
          data-testid="trade-sell"
          type="button"
          disabled={busy !== null}
          onClick={() => void submit("sell")}
          className="btn bg-down/15 text-down ring-1 ring-inset ring-down/40 hover:bg-down/25"
        >
          {busy === "sell" ? "…" : "Sell"}
        </button>
        <div className="min-w-0 flex-1 truncate text-[11.5px]">
          {error ? (
            <span data-testid="trade-error" role="alert" className="text-down">
              {error}
            </span>
          ) : notice ? (
            <span data-testid="trade-notice" className="font-mono text-ink-300">
              ✓ {notice}
            </span>
          ) : null}
        </div>
      </form>
    </section>
  );
}

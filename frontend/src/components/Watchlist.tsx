"use client";

import { useState } from "react";
import type { PriceMap, PricePoint } from "@/types";
import { normalizeTicker } from "@/utils/chat";
import WatchlistRow from "./WatchlistRow";

interface Props {
  tickers: string[];
  prices: PriceMap;
  history: Record<string, PricePoint[]>;
  version: number;
  selected: string | null;
  onSelect: (ticker: string) => void;
  onAdd: (ticker: string) => Promise<void>;
  onRemove: (ticker: string) => Promise<void>;
}

const EMPTY: PricePoint[] = [];

export default function Watchlist({ tickers, prices, history, version, selected, onSelect, onAdd, onRemove }: Props) {
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const t = normalizeTicker(input);
    if (!t) return;
    setBusy(true);
    setError(null);
    try {
      await onAdd(t);
      setInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (t: string) => {
    setError(null);
    try {
      await onRemove(t);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <section data-testid="watchlist" className="panel h-full">
      <div className="panel-title">
        <span>
          Watchlist <span className="tag">· {tickers.length}</span>
        </span>
        <span className="font-mono text-[9.5px] normal-case tracking-normal text-ink-500">day %</span>
      </div>

      <div role="table" className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        {tickers.length === 0 && (
          <p className="px-3 py-6 text-center text-[12px] text-ink-400">No tickers. Add one below.</p>
        )}
        {tickers.map((t) => {
          const tick = prices[t];
          return (
            <WatchlistRow
              key={t}
              ticker={t}
              price={tick?.price ?? null}
              dayChangePercent={tick?.day_change_percent ?? tick?.change_percent ?? null}
              points={history[t] ?? EMPTY}
              version={version}
              selected={selected === t}
              onSelect={onSelect}
              onRemove={remove}
            />
          );
        })}
      </div>

      <form onSubmit={submit} className="flex shrink-0 gap-1.5 border-t border-ink-700 p-2">
        <input
          data-testid="watchlist-add-input"
          value={input}
          onChange={(e) => setInput(e.target.value.toUpperCase())}
          placeholder="Add ticker"
          aria-label="Ticker to add"
          maxLength={10}
          className="input min-w-0 flex-1 uppercase"
        />
        <button
          data-testid="watchlist-add-button"
          type="submit"
          disabled={busy || !input.trim()}
          className="btn border border-primary/50 text-primary hover:bg-primary/15"
        >
          Add
        </button>
      </form>
      {error && (
        <p role="alert" className="shrink-0 px-2 pb-2 text-[11px] text-down">
          {error}
        </p>
      )}
    </section>
  );
}

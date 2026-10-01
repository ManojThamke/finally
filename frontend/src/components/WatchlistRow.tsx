"use client";

import { memo, useEffect, useRef, useState } from "react";
import type { PricePoint } from "@/types";
import { formatPercent, formatPrice, toneClass } from "@/utils/format";
import Sparkline from "./Sparkline";

/** How long the flash is tracked (data-flash attr). */
export const FLASH_MS = 500;
/** How long the solid highlight holds before the CSS transition fades it (~500ms). */
export const FLASH_HOLD_MS = 150;

interface Props {
  ticker: string;
  price: number | null;
  dayChangePercent: number | null;
  points: PricePoint[];
  selected: boolean;
  version: number;
  onSelect: (ticker: string) => void;
  onRemove: (ticker: string) => void;
}

function WatchlistRow({ ticker, price, dayChangePercent, points, selected, onSelect, onRemove }: Props) {
  const prev = useRef<number | null>(price);
  const [flash, setFlash] = useState<"up" | "down" | null>(null);
  const [hot, setHot] = useState(false);

  useEffect(() => {
    const before = prev.current;
    prev.current = price;
    if (price == null || before == null || price === before) return;
    setFlash(price > before ? "up" : "down");
    setHot(true);
    const hold = setTimeout(() => setHot(false), FLASH_HOLD_MS);
    const t = setTimeout(() => setFlash(null), FLASH_MS);
    return () => {
      clearTimeout(hold);
      clearTimeout(t);
    };
  }, [price]);

  return (
    <div
      role="row"
      data-testid={`watchlist-row-${ticker}`}
      aria-selected={selected}
      onClick={() => onSelect(ticker)}
      className={`group grid cursor-pointer grid-cols-[1fr_auto_auto] items-center gap-x-2 border-b border-ink-800 px-3 py-1.5 transition-colors ${
        selected ? "bg-primary/10 shadow-[inset_2px_0_0_#209dd7]" : "hover:bg-ink-800/70"
      }`}
    >
      <div className="flex min-w-0 flex-col">
        <span className={`font-mono text-[13px] font-semibold ${selected ? "text-primary" : "text-ink-100"}`}>
          {ticker}
        </span>
        <span className={`num text-[10.5px] ${toneClass(dayChangePercent)}`}>{formatPercent(dayChangePercent)}</span>
      </div>
      <Sparkline points={points} />
      <div className="flex items-center gap-1">
        <span
          data-testid={`watchlist-price-${ticker}`}
          data-flash={flash ?? undefined}
          className={`price-cell num w-[72px] rounded-[2px] px-1 py-0.5 text-right text-[13px] text-ink-100 ${
            hot && flash === "up" ? "flash-up" : hot && flash === "down" ? "flash-down" : ""
          }`}
        >
          {formatPrice(price)}
        </span>
        <button
          type="button"
          data-testid={`watchlist-remove-${ticker}`}
          aria-label={`Remove ${ticker} from watchlist`}
          onClick={(e) => {
            e.stopPropagation();
            onRemove(ticker);
          }}
          className="flex h-5 w-5 items-center justify-center rounded-[2px] text-ink-500 opacity-0 transition-opacity hover:bg-down/15 hover:text-down focus:opacity-100 group-hover:opacity-100"
        >
          ×
        </button>
      </div>
    </div>
  );
}

export default memo(WatchlistRow);

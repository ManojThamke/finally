"use client";

import type { Position } from "@/types";
import { formatPercent, formatPrice, formatQty, formatSignedUsd, formatUsd, toneClass } from "@/utils/format";

interface Props {
  positions: Position[];
  onSelect?: (ticker: string) => void;
}

const TH = "px-3 py-1.5 font-medium text-right first:text-left";
const TD = "px-3 py-1.5 text-right first:text-left";

export default function PositionsTable({ positions, onSelect }: Props) {
  const sorted = [...positions].sort((a, b) => b.market_value - a.market_value);
  return (
    <section className="panel h-full">
      <div className="panel-title">
        <span>
          Positions <span className="tag">· {positions.length}</span>
        </span>
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-auto">
        <table data-testid="positions-table" className="w-full border-collapse text-[12px]">
          <thead className="sticky top-0 bg-ink-850 text-[9.5px] uppercase tracking-[0.14em] text-ink-400">
            <tr className="border-b border-ink-700">
              <th className={TH}>Ticker</th>
              <th className={TH}>Qty</th>
              <th className={TH}>Avg Cost</th>
              <th className={TH}>Price</th>
              <th className={TH}>Mkt Value</th>
              <th className={TH}>Unrl P&amp;L</th>
              <th className={TH}>%</th>
              <th className={TH}>Wt</th>
            </tr>
          </thead>
          <tbody className="num">
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center font-sans text-[12px] text-ink-400">
                  No open positions — use the trade bar or ask the AI copilot.
                </td>
              </tr>
            ) : (
              sorted.map((p) => (
                <tr
                  key={p.ticker}
                  data-testid={`position-row-${p.ticker}`}
                  onClick={() => onSelect?.(p.ticker)}
                  className="cursor-pointer border-b border-ink-800 hover:bg-ink-800/60"
                >
                  <td className={`${TD} font-semibold text-ink-100`}>{p.ticker}</td>
                  <td className={TD} data-testid={`position-qty-${p.ticker}`}>{formatQty(p.quantity)}</td>
                  <td className={`${TD} text-ink-300`}>{formatPrice(p.avg_cost)}</td>
                  <td className={`${TD} text-ink-100`}>{formatPrice(p.current_price)}</td>
                  <td className={TD}>{formatUsd(p.market_value)}</td>
                  <td className={`${TD} ${toneClass(p.unrealized_pnl)}`}>{formatSignedUsd(p.unrealized_pnl)}</td>
                  <td className={`${TD} ${toneClass(p.unrealized_pnl_percent)}`}>{formatPercent(p.unrealized_pnl_percent)}</td>
                  <td className={`${TD} text-ink-300`}>{p.weight.toFixed(1)}%</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

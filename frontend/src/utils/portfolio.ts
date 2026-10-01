import type { Portfolio, Position, PriceMap } from "@/types";

/**
 * Re-value a server portfolio snapshot against live SSE prices.
 * Quantity, avg cost and cash come from the server; prices come from the stream.
 */
export function computeLivePortfolio(portfolio: Portfolio | null, prices: PriceMap): Portfolio | null {
  if (!portfolio) return null;
  const positions: Position[] = portfolio.positions.map((p) => {
    const live = prices[p.ticker]?.price;
    const current = live != null && Number.isFinite(live) ? live : p.current_price ?? p.avg_cost;
    const marketValue = p.quantity * current;
    const cost = p.quantity * p.avg_cost;
    const pnl = marketValue - cost;
    return {
      ...p,
      current_price: current,
      market_value: marketValue,
      unrealized_pnl: pnl,
      unrealized_pnl_percent: cost > 0 ? (pnl / cost) * 100 : 0,
      weight: 0,
    };
  });
  const positionsValue = positions.reduce((s, p) => s + p.market_value, 0);
  const totalValue = portfolio.cash_balance + positionsValue;
  const totalCost = positions.reduce((s, p) => s + p.quantity * p.avg_cost, 0);
  const unrealized = positionsValue - totalCost;
  for (const p of positions) {
    p.weight = totalValue > 0 ? (p.market_value / totalValue) * 100 : 0;
  }
  return {
    cash_balance: portfolio.cash_balance,
    positions_value: positionsValue,
    total_value: totalValue,
    unrealized_pnl: unrealized,
    unrealized_pnl_percent: totalCost > 0 ? (unrealized / totalCost) * 100 : 0,
    positions,
  };
}

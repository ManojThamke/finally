export type Direction = "up" | "down" | "flat";

export interface PriceTick {
  ticker: string;
  price: number;
  previous_price: number;
  session_open?: number;
  timestamp: number; // unix seconds
  change?: number;
  change_percent?: number;
  day_change_percent?: number;
  direction: Direction;
}

export type PriceMap = Record<string, PriceTick>;

export interface PricePoint {
  time: number; // unix seconds
  value: number;
}

export type ConnectionStatus = "connected" | "reconnecting" | "disconnected";

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_percent: number;
  weight: number;
}

export interface Portfolio {
  cash_balance: number;
  positions_value: number;
  total_value: number;
  unrealized_pnl: number;
  unrealized_pnl_percent: number;
  positions: Position[];
}

export interface Snapshot {
  total_value: number;
  recorded_at: string;
}

export interface WatchlistEntry {
  ticker: string;
  price: number | null;
  previous_price?: number | null;
  change?: number | null;
  change_percent?: number | null;
  day_change_percent?: number | null;
  direction?: Direction | null;
}

export type TradeSide = "buy" | "sell";

export interface Trade {
  id: string;
  ticker: string;
  side: TradeSide;
  quantity: number;
  price: number;
  executed_at: string;
}

export type ActionStatus = "executed" | "failed";

export interface ChatTradeAction {
  ticker: string;
  side: TradeSide;
  quantity: number;
  status: ActionStatus;
  price?: number | null;
  error?: string | null;
}

export interface ChatWatchlistAction {
  ticker: string;
  action: "add" | "remove";
  status: ActionStatus;
  error?: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  trades: ChatTradeAction[];
  watchlist_changes: ChatWatchlistAction[];
  pending?: boolean;
}

export interface ChatResponse {
  id: string;
  role: "assistant";
  message: string;
  created_at: string;
  trades: ChatTradeAction[];
  watchlist_changes: ChatWatchlistAction[];
}

export interface ChatHistoryMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  actions: unknown;
  created_at: string;
}

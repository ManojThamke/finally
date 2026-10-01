import type { ChatHistoryMessage, ChatMessage, ChatTradeAction, ChatWatchlistAction } from "@/types";

/** Normalise a stored chat row (actions may be null, a dict, or a list) into a ChatMessage. */
export function fromHistory(m: ChatHistoryMessage): ChatMessage {
  let trades: ChatTradeAction[] = [];
  let watchlist: ChatWatchlistAction[] = [];
  const a = m.actions as unknown;
  if (a && typeof a === "object" && !Array.isArray(a)) {
    const obj = a as { trades?: unknown; watchlist_changes?: unknown };
    if (Array.isArray(obj.trades)) trades = obj.trades as ChatTradeAction[];
    if (Array.isArray(obj.watchlist_changes)) watchlist = obj.watchlist_changes as ChatWatchlistAction[];
  } else if (Array.isArray(a)) {
    for (const item of a) {
      if (item && typeof item === "object") {
        if ("side" in item) trades.push(item as ChatTradeAction);
        else if ("action" in item) watchlist.push(item as ChatWatchlistAction);
      }
    }
  }
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    created_at: m.created_at,
    trades,
    watchlist_changes: watchlist,
  };
}

export function normalizeTicker(raw: string): string {
  return raw.trim().toUpperCase();
}

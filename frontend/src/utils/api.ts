import type {
  ChatHistoryMessage,
  ChatResponse,
  Portfolio,
  Snapshot,
  Trade,
  TradeSide,
  WatchlistEntry,
} from "@/types";

/** Base URL for API calls. Empty string = same origin (production static export). */
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function detailToMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  // FastAPI 422 validation errors: [{loc, msg, type}, ...]
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
      .filter(Boolean);
    if (msgs.length) return msgs.join("; ");
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError("Network error — is the server running?", 0);
  }
  let body: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!res.ok) {
    const detail = body && typeof body === "object" ? (body as { detail?: unknown }).detail : body;
    throw new ApiError(detailToMessage(detail, `Request failed (${res.status})`), res.status);
  }
  return body as T;
}

export const api = {
  getPortfolio: () => request<Portfolio>("/api/portfolio"),
  getHistory: () => request<{ snapshots: Snapshot[] }>("/api/portfolio/history"),
  trade: (ticker: string, quantity: number, side: TradeSide) =>
    request<{ trade: Trade; portfolio: Portfolio }>("/api/portfolio/trade", {
      method: "POST",
      body: JSON.stringify({ ticker, quantity, side }),
    }),
  getWatchlist: () => request<{ tickers: WatchlistEntry[] }>("/api/watchlist"),
  addTicker: (ticker: string) =>
    request<{ ticker: string; added: boolean }>("/api/watchlist", {
      method: "POST",
      body: JSON.stringify({ ticker }),
    }),
  removeTicker: (ticker: string) =>
    request<{ ticker: string; removed: boolean }>(`/api/watchlist/${encodeURIComponent(ticker)}`, {
      method: "DELETE",
    }),
  chat: (message: string) =>
    request<ChatResponse>("/api/chat", { method: "POST", body: JSON.stringify({ message }) }),
  chatHistory: () => request<{ messages: ChatHistoryMessage[] }>("/api/chat/history"),
};

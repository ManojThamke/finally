"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/utils/api";
import { fromHistory } from "@/utils/chat";
import type { ChatMessage, Portfolio, Snapshot, TradeSide } from "@/types";

const POLL_MS = 30_000;

function errMsg(err: unknown) {
  return err instanceof Error ? err.message : String(err);
}

/** Server state for the workstation: watchlist, portfolio, snapshots, chat. */
export function useTerminal() {
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const tempId = useRef(0);

  const refreshWatchlist = useCallback(async () => {
    try {
      const res = await api.getWatchlist();
      setWatchlist(res.tickers.map((t) => t.ticker));
    } catch {
      /* keep last known */
    }
  }, []);

  const refreshPortfolio = useCallback(async () => {
    try {
      setPortfolio(await api.getPortfolio());
    } catch {
      /* keep last known */
    }
  }, []);

  const refreshHistory = useCallback(async () => {
    try {
      setSnapshots((await api.getHistory()).snapshots);
    } catch {
      /* keep last known */
    }
  }, []);

  useEffect(() => {
    void refreshWatchlist();
    void refreshPortfolio();
    void refreshHistory();
    api
      .chatHistory()
      .then((res) => setMessages((cur) => (cur.length ? cur : res.messages.map(fromHistory))))
      .catch(() => {});
    const id = setInterval(() => {
      void refreshPortfolio();
      void refreshHistory();
    }, POLL_MS);
    return () => clearInterval(id);
  }, [refreshWatchlist, refreshPortfolio, refreshHistory]);

  const addTicker = useCallback(
    async (ticker: string) => {
      await api.addTicker(ticker);
      await refreshWatchlist();
    },
    [refreshWatchlist],
  );

  const removeTicker = useCallback(
    async (ticker: string) => {
      // Optimistic: drop it immediately, restore on failure.
      setWatchlist((w) => w.filter((t) => t !== ticker));
      try {
        await api.removeTicker(ticker);
      } finally {
        await refreshWatchlist();
      }
    },
    [refreshWatchlist],
  );

  const trade = useCallback(
    async (ticker: string, quantity: number, side: TradeSide) => {
      const res = await api.trade(ticker, quantity, side);
      setPortfolio(res.portfolio);
      void refreshHistory();
      return { price: res.trade.price };
    },
    [refreshHistory],
  );

  const sendChat = useCallback(
    async (text: string) => {
      const userMsg: ChatMessage = {
        id: `local-${++tempId.current}`,
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
        trades: [],
        watchlist_changes: [],
      };
      setMessages((m) => [...m, userMsg]);
      setChatLoading(true);
      setChatError(null);
      try {
        const res = await api.chat(text);
        const reply: ChatMessage = {
          id: res.id,
          role: "assistant",
          content: res.message,
          created_at: res.created_at,
          trades: res.trades ?? [],
          watchlist_changes: res.watchlist_changes ?? [],
        };
        setMessages((m) => [...m, reply]);
        if (reply.trades.length) {
          await Promise.all([refreshPortfolio(), refreshHistory()]);
        }
        if (reply.watchlist_changes.length) {
          await refreshWatchlist();
        }
      } catch (err) {
        setChatError(errMsg(err));
      } finally {
        setChatLoading(false);
      }
    },
    [refreshPortfolio, refreshHistory, refreshWatchlist],
  );

  return {
    watchlist,
    portfolio,
    snapshots,
    messages,
    chatLoading,
    chatError,
    addTicker,
    removeTicker,
    trade,
    sendChat,
  };
}

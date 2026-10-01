"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/utils/api";
import type { ConnectionStatus, PriceMap, PricePoint, PriceTick } from "@/types";

/** Max points kept per ticker (~10 min at 500ms cadence). */
export const HISTORY_LIMIT = 1200;

export interface PriceStream {
  prices: PriceMap;
  /** Accumulated price history per ticker since page load. Mutated in place; `version` changes on every update. */
  history: Record<string, PricePoint[]>;
  status: ConnectionStatus;
  version: number;
}

export function appendTicks(history: Record<string, PricePoint[]>, ticks: PriceTick[], limit = HISTORY_LIMIT) {
  for (const t of ticks) {
    if (!t || typeof t.price !== "number") continue;
    const series = (history[t.ticker] ??= []);
    const last = series[series.length - 1];
    // Same timestamp → the cache hasn't moved for this ticker; skip duplicates.
    if (last && last.time === t.timestamp) continue;
    if (last && t.timestamp < last.time) continue;
    series.push({ time: t.timestamp, value: t.price });
    if (series.length > limit) series.splice(0, series.length - limit);
  }
}

export function usePriceStream(url = `${API_BASE}/api/stream/prices`): PriceStream {
  const [prices, setPrices] = useState<PriceMap>({});
  const [status, setStatus] = useState<ConnectionStatus>("reconnecting");
  const [version, setVersion] = useState(0);
  const historyRef = useRef<Record<string, PricePoint[]>>({});

  useEffect(() => {
    if (typeof window === "undefined" || typeof EventSource === "undefined") {
      setStatus("disconnected");
      return;
    }
    let es: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;

    const handle = (ev: MessageEvent) => {
      let payload: unknown;
      try {
        payload = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (!payload || typeof payload !== "object") return;
      const ticks = Object.values(payload as Record<string, PriceTick>);
      appendTicks(historyRef.current, ticks);
      setPrices((prev) => ({ ...prev, ...(payload as PriceMap) }));
      setStatus("connected");
      setVersion((v) => v + 1);
    };

    const connect = () => {
      if (disposed) return;
      const source = new EventSource(url);
      es = source;
      source.onopen = () => setStatus("connected");
      source.onerror = () => {
        if (source.readyState === EventSource.CLOSED) {
          // The browser gave up (e.g. non-200 response); retry ourselves.
          setStatus("disconnected");
          source.close();
          retryTimer = setTimeout(connect, 3000);
        } else {
          // Browser is auto-retrying.
          setStatus("reconnecting");
        }
      };
      source.addEventListener("prices", handle as EventListener);
      source.onmessage = handle;
    };

    connect();

    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      es?.close();
    };
  }, [url]);

  return { prices, history: historyRef.current, status, version };
}

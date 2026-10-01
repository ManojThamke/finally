"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "@/types";
import { formatPrice, formatQty } from "@/utils/format";

interface Props {
  messages: ChatMessage[];
  loading: boolean;
  error: string | null;
  onSend: (text: string) => void;
  onClose: () => void;
}

const SUGGESTIONS = ["How is my portfolio doing?", "Buy 5 AAPL", "Add PYPL to my watchlist"];

export default function ChatPanel({ messages, loading, error, onSend, onClose }: Props) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, loading]);

  const send = (e?: React.FormEvent) => {
    e?.preventDefault();
    const t = text.trim();
    if (!t || loading) return;
    onSend(t);
    setText("");
  };

  return (
    <aside data-testid="chat-panel" className="panel h-full">
      <div className="panel-title">
        <span className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-secondary shadow-[0_0_6px_#753991]" />
          AI Copilot
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Collapse chat"
          className="text-[14px] leading-none text-ink-400 hover:text-ink-100"
        >
          »
        </button>
      </div>

      <div className="scroll-thin min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {messages.length === 0 && !loading && (
          <div className="space-y-3 pt-2">
            <p className="text-[12.5px] leading-relaxed text-ink-300">
              I&apos;m <span className="text-accent">FinAlly</span>, your trading copilot. Ask me to analyse your
              portfolio, place trades, or manage your watchlist.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => onSend(s)}
                  className="rounded-[3px] border border-ink-600 px-2 py-1 text-[11px] text-ink-300 hover:border-primary/60 hover:text-primary"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <Message key={m.id} m={m} />
        ))}

        {loading && (
          <div data-testid="chat-loading" role="status" aria-label="Assistant is thinking" className="flex items-center gap-2">
            <span className="typing flex gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-primary" />
              <span className="h-1.5 w-1.5 rounded-full bg-primary" />
              <span className="h-1.5 w-1.5 rounded-full bg-primary" />
            </span>
            <span className="text-[11px] uppercase tracking-[0.14em] text-ink-400">Thinking</span>
          </div>
        )}
        {error && (
          <p role="alert" className="text-[11.5px] text-down">
            {error}
          </p>
        )}
        <div ref={endRef} />
      </div>

      <form onSubmit={send} className="flex shrink-0 gap-1.5 border-t border-ink-700 p-2">
        <textarea
          data-testid="chat-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          rows={2}
          maxLength={4000}
          placeholder="Ask FinAlly…"
          aria-label="Chat message"
          className="input h-auto min-w-0 flex-1 resize-none overflow-hidden py-1.5 font-sans"
        />
        <button
          data-testid="chat-send"
          type="submit"
          disabled={loading || !text.trim()}
          className="btn self-stretch bg-secondary text-white hover:bg-secondary/85 h-auto"
        >
          Send
        </button>
      </form>
    </aside>
  );
}

function Message({ m }: { m: ChatMessage }) {
  const user = m.role === "user";
  return (
    <div data-testid="chat-message" data-role={m.role} className={`flex flex-col ${user ? "items-end" : "items-start"}`}>
      <span className="mb-0.5 text-[9.5px] uppercase tracking-[0.16em] text-ink-500">{user ? "You" : "FinAlly"}</span>
      <div
        className={`max-w-[92%] whitespace-pre-wrap rounded-[3px] px-2.5 py-1.5 text-[12.5px] leading-relaxed ${
          user ? "bg-primary/15 text-ink-100 ring-1 ring-inset ring-primary/30" : "bg-ink-800 text-ink-200 ring-1 ring-inset ring-ink-700"
        }`}
      >
        {m.content}
      </div>
      {(m.trades.length > 0 || m.watchlist_changes.length > 0) && (
        <div className="mt-1 flex w-full max-w-[92%] flex-col gap-1">
          {m.trades.map((t, i) => (
            <ActionChip key={`t${i}`} ok={t.status === "executed"} error={t.error}>
              {t.side === "buy" ? "BUY" : "SELL"} {formatQty(t.quantity)} {t.ticker}
              {t.status === "executed" && t.price != null ? ` @ ${formatPrice(t.price)}` : ""}
            </ActionChip>
          ))}
          {m.watchlist_changes.map((w, i) => (
            <ActionChip key={`w${i}`} ok={w.status === "executed"} error={w.error}>
              WATCHLIST {w.action === "add" ? "+" : "−"} {w.ticker}
            </ActionChip>
          ))}
        </div>
      )}
    </div>
  );
}

function ActionChip({ ok, error, children }: { ok: boolean; error?: string | null; children: React.ReactNode }) {
  return (
    <div
      data-testid="chat-action"
      data-status={ok ? "executed" : "failed"}
      className={`flex items-start gap-1.5 rounded-[3px] border px-2 py-1 font-mono text-[11px] ${
        ok ? "border-up/30 bg-up/10 text-up" : "border-down/30 bg-down/10 text-down"
      }`}
    >
      <span>{ok ? "✓" : "✕"}</span>
      <span className="min-w-0">
        {children}
        {!ok && error ? <span className="block font-sans text-[10.5px] opacity-80">{error}</span> : null}
      </span>
    </div>
  );
}

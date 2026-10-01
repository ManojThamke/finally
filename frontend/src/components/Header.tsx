"use client";

import type { ConnectionStatus } from "@/types";
import { formatPercent, formatSignedUsd, formatUsd, toneClass } from "@/utils/format";

const STATUS_STYLE: Record<ConnectionStatus, { dot: string; label: string }> = {
  connected: { dot: "bg-up shadow-[0_0_8px_rgba(38,208,124,0.8)]", label: "LIVE" },
  reconnecting: { dot: "bg-accent dot-pulse shadow-[0_0_8px_rgba(236,173,10,0.7)]", label: "RECONNECTING" },
  disconnected: { dot: "bg-down shadow-[0_0_8px_rgba(255,92,92,0.7)]", label: "OFFLINE" },
};

interface Props {
  totalValue: number | null;
  cash: number | null;
  unrealizedPnl: number | null;
  unrealizedPnlPercent: number | null;
  status: ConnectionStatus;
  chatOpen: boolean;
  onToggleChat: () => void;
}

export default function Header({
  totalValue,
  cash,
  unrealizedPnl,
  unrealizedPnlPercent,
  status,
  chatOpen,
  onToggleChat,
}: Props) {
  const s = STATUS_STYLE[status];
  return (
    <header className="flex h-12 shrink-0 items-center gap-6 border-b border-ink-700 bg-ink-900/95 px-4">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-[17px] font-bold tracking-tight text-ink-100">
          Fin<span className="text-accent">Ally</span>
        </span>
        <span className="hidden text-[10px] uppercase tracking-[0.2em] text-ink-400 md:inline">
          AI Trading Workstation
        </span>
      </div>

      <div className="ml-auto flex items-center gap-6">
        <Stat label="Portfolio">
          <span data-testid="header-total-value" className="num text-[15px] font-semibold text-ink-100">
            {formatUsd(totalValue)}
          </span>
        </Stat>
        <Stat label="Unrealized P&L" className="hidden sm:flex">
          <span className={`num text-[13px] ${toneClass(unrealizedPnl)}`}>
            {formatSignedUsd(unrealizedPnl)}{" "}
            <span className="text-[11px] opacity-80">({formatPercent(unrealizedPnlPercent)})</span>
          </span>
        </Stat>
        <Stat label="Cash">
          <span data-testid="header-cash" className="num text-[13px] text-ink-200">
            {formatUsd(cash)}
          </span>
        </Stat>

        <div
          data-testid="connection-status"
          data-status={status}
          title={`Price stream: ${status}`}
          className="flex items-center gap-2 rounded-[3px] border border-ink-700 bg-ink-850 px-2 py-1"
        >
          <span className={`h-2 w-2 rounded-full ${s.dot}`} />
          <span className="font-mono text-[10px] tracking-[0.14em] text-ink-300">{s.label}</span>
        </div>

        <button
          type="button"
          onClick={onToggleChat}
          aria-pressed={chatOpen}
          className={`btn border ${
            chatOpen
              ? "border-primary/60 bg-primary/15 text-primary"
              : "border-ink-600 text-ink-300 hover:border-primary/60 hover:text-primary"
          }`}
        >
          AI Copilot
        </button>
      </div>
    </header>
  );
}

function Stat({ label, children, className = "" }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`flex flex-col items-end leading-tight ${className}`}>
      <span className="text-[9.5px] uppercase tracking-[0.16em] text-ink-400">{label}</span>
      {children}
    </div>
  );
}

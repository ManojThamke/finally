"use client";

import { useEffect, useMemo, useState } from "react";
import { usePriceStream } from "@/hooks/usePriceStream";
import { useTerminal } from "@/hooks/useTerminal";
import { computeLivePortfolio } from "@/utils/portfolio";
import ChatPanel from "./ChatPanel";
import Header from "./Header";
import Heatmap from "./Heatmap";
import MainChart from "./MainChart";
import PnlChart from "./PnlChart";
import PositionsTable from "./PositionsTable";
import TradeBar from "./TradeBar";
import Watchlist from "./Watchlist";

const EMPTY: never[] = [];

export default function Workstation() {
  const stream = usePriceStream();
  const t = useTerminal();
  const [selected, setSelected] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(true);

  // Default selection: first watchlist ticker; move on if the selected one is removed.
  useEffect(() => {
    if (!t.watchlist.length) return;
    if (!selected || (!t.watchlist.includes(selected) && !t.portfolio?.positions.some((p) => p.ticker === selected))) {
      setSelected(t.watchlist[0]);
    }
  }, [t.watchlist, t.portfolio, selected]);

  const live = useMemo(() => computeLivePortfolio(t.portfolio, stream.prices), [t.portfolio, stream.prices]);

  return (
    <div className="flex h-screen min-h-[640px] flex-col">
      <Header
        totalValue={live?.total_value ?? null}
        cash={live?.cash_balance ?? null}
        unrealizedPnl={live?.unrealized_pnl ?? null}
        unrealizedPnlPercent={live?.unrealized_pnl_percent ?? null}
        status={stream.status}
        chatOpen={chatOpen}
        onToggleChat={() => setChatOpen((o) => !o)}
      />

      <main className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-2 lg:flex-row lg:overflow-hidden">
        <div className="h-[420px] shrink-0 lg:h-auto lg:w-[290px]">
          <Watchlist
            tickers={t.watchlist}
            prices={stream.prices}
            history={stream.history}
            version={stream.version}
            selected={selected}
            onSelect={setSelected}
            onAdd={t.addTicker}
            onRemove={t.removeTicker}
          />
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-2 lg:grid lg:grid-rows-[minmax(200px,1.25fr)_auto_minmax(170px,1fr)_minmax(140px,0.85fr)]">
          <div className="h-[340px] lg:h-auto lg:min-h-0">
            <MainChart
              ticker={selected}
              points={(selected && stream.history[selected]) || EMPTY}
              tick={selected ? stream.prices[selected] : undefined}
              version={stream.version}
            />
          </div>
          <TradeBar selectedTicker={selected} onTrade={t.trade} />
          <div className="grid min-h-0 grid-cols-1 gap-2 md:grid-cols-2">
            <div className="h-[240px] md:h-auto md:min-h-0">
              <Heatmap positions={live?.positions ?? EMPTY} onSelect={setSelected} />
            </div>
            <div className="h-[240px] md:h-auto md:min-h-0">
              <PnlChart snapshots={t.snapshots} liveValue={live?.total_value ?? null} />
            </div>
          </div>
          <div className="h-[260px] lg:h-auto lg:min-h-0">
            <PositionsTable positions={live?.positions ?? EMPTY} onSelect={setSelected} />
          </div>
        </div>

        {chatOpen && (
          <div className="h-[520px] shrink-0 lg:h-auto lg:w-[340px]">
            <ChatPanel
              messages={t.messages}
              loading={t.chatLoading}
              error={t.chatError}
              onSend={(m) => void t.sendChat(m)}
              onClose={() => setChatOpen(false)}
            />
          </div>
        )}
      </main>
    </div>
  );
}

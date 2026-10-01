# Massive API Reference (formerly Polygon.io)

Reference for the parts of the Massive REST API that FinAlly uses to fetch live and end-of-day stock prices for multiple tickers. Written for the Backend / Market Data agent. For how this plugs into the app, see `MARKET_INTERFACE.md`.

> Polygon.io rebranded to **Massive** on 2025-10-30. Existing API keys keep working. The new base URL is `https://api.massive.com`, and the legacy `https://api.polygon.io` is still accepted for now. The Python package was renamed from `polygon-api-client` to `massive`.

---

## 1. Basics

| Item | Value |
|---|---|
| Base URL | `https://api.massive.com` |
| Auth (option A) | Query string `?apiKey=YOUR_KEY` |
| Auth (option B) | Header `Authorization: Bearer YOUR_KEY` (preferred: keeps the key out of logs) |
| Format | JSON |
| Python client | `pip install -U massive` / `uv add massive`, then `from massive import RESTClient` |
| Key in FinAlly | `MASSIVE_API_KEY` env var (from `.env`) |
| Timestamps | Unix epoch. **Milliseconds** for aggregates (`t`), **nanoseconds** for trades, quotes and snapshot `updated` |

### Plans and what they mean for us

| Plan | Price | Rate limit | Data freshness | Snapshots? |
|---|---|---|---|---|
| Stocks Basic (free) | $0 | **5 calls/min** | End of day | **No** |
| Stocks Starter | $29/mo | Unlimited (stay under ~100 req/s) | 15-min delayed | Yes |
| Stocks Developer | $79/mo | Unlimited | 15-min delayed | Yes |
| Stocks Advanced | $199/mo | Unlimited | Real-time | Yes |

**Implication:** the free tier **cannot** use the snapshot endpoint (it returns `403 NOT_AUTHORIZED`). A free key can only get end-of-day data, such as the previous close or the grouped daily bars. The FinAlly client must detect this and fall back (see §6).

---

## 2. Endpoints we use

| Purpose | Endpoint | Tickers per call | Free tier? |
|---|---|---|---|
| **Live prices, many tickers** (primary) | `GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,...` | Many (comma-separated) | No |
| Live price, one ticker | `GET /v2/snapshot/locale/us/markets/stocks/tickers/{ticker}` | 1 | No |
| **EOD bars for the whole market** (free fallback) | `GET /v2/aggs/grouped/locale/us/market/stocks/{YYYY-MM-DD}` | All (~10k) | Yes |
| Previous day bar | `GET /v2/aggs/ticker/{ticker}/prev` | 1 | Yes |
| Daily open/close | `GET /v1/open-close/{ticker}/{YYYY-MM-DD}` | 1 | Yes |
| Historical bars | `GET /v2/aggs/ticker/{ticker}/range/{mult}/{timespan}/{from}/{to}` | 1 | Yes |
| Last trade | `GET /v2/last/trade/{ticker}` | 1 | No (paid) |

For many tickers, the **snapshot** endpoint (paid) and the **grouped daily** endpoint (free) are the two that matter. Each covers every ticker we care about in **one** request.

---

## 3. Full Market Snapshot (primary live source)

`GET /v2/snapshot/locale/us/markets/stocks/tickers`

| Param | Type | Notes |
|---|---|---|
| `tickers` | string | Comma-separated and case-insensitive, e.g. `AAPL,TSLA,GOOG`. If omitted, returns **all** tickers (large). |
| `include_otc` | bool | Default `false` |

The response returns, for each ticker, the latest trade, latest quote, current minute bar, today's bar, and the previous day's bar. Snapshot data is **cleared at 3:30 AM ET** and starts repopulating around 4:00 AM ET. Expect empty or zeroed `day` values in that window.

### Example response

```json
{
  "status": "OK",
  "count": 1,
  "tickers": [
    {
      "ticker": "AAPL",
      "todaysChange": -0.124,
      "todaysChangePerc": -0.601,
      "updated": 1605192894630916600,
      "day":      {"o": 20.64, "h": 20.64, "l": 20.506, "c": 20.506, "v": 37216, "vw": 20.616},
      "prevDay":  {"o": 20.79, "h": 21.0,  "l": 20.5,   "c": 20.63,  "v": 292738, "vw": 20.6939},
      "min":      {"o": 20.506, "h": 20.506, "l": 20.506, "c": 20.506, "v": 5000, "vw": 20.5105,
                   "av": 37216, "n": 1, "t": 1684428600000},
      "lastTrade": {"p": 20.506, "s": 2416, "t": 1605192894630916600, "x": 4, "c": [14, 41], "i": "71675577320245"},
      "lastQuote": {"p": 20.5, "s": 13, "P": 20.6, "S": 22, "t": 1605192959994246100}
    }
  ]
}
```

| JSON field | Python client attribute | Meaning |
|---|---|---|
| `ticker` | `ticker` | Symbol |
| `lastTrade.p` | `last_trade.price` | **Last trade price. Use this as "current price".** |
| `lastTrade.t` | `last_trade.sip_timestamp` | Trade time (ns) |
| `lastQuote.p` / `lastQuote.P` | `last_quote.bid_price` / `last_quote.ask_price` | Bid / ask |
| `min.c` | `min.close` | Close of current minute bar (fallback price) |
| `day.c` | `day.close` | Today's running close |
| `prevDay.c` | `prev_day.close` | Yesterday's close (basis for daily change %) |
| `todaysChange`, `todaysChangePerc` | `todays_change`, `todays_change_percent` | Change vs. previous close |
| `updated` | `updated` | Last update (ns) |

**Price selection rule:** use `lastTrade.p` if > 0, else `min.c` if > 0, else `day.c` if > 0, else `prevDay.c`. Outside market hours, `lastTrade.p` still holds the last (after-hours) trade.

### Raw HTTP (httpx)

```python
import os
import httpx

BASE = "https://api.massive.com"
headers = {"Authorization": f"Bearer {os.environ['MASSIVE_API_KEY']}"}

async def fetch_snapshot(tickers: list[str]) -> dict[str, float]:
    async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=10) as client:
        r = await client.get(
            "/v2/snapshot/locale/us/markets/stocks/tickers",
            params={"tickers": ",".join(tickers)},
        )
        r.raise_for_status()
        data = r.json()

    prices: dict[str, float] = {}
    for t in data.get("tickers", []):
        price = (
            (t.get("lastTrade") or {}).get("p")
            or (t.get("min") or {}).get("c")
            or (t.get("day") or {}).get("c")
            or (t.get("prevDay") or {}).get("c")
        )
        if price:
            prices[t["ticker"]] = float(price)
    return prices
```

### Official client

```python
from massive import RESTClient

client = RESTClient(api_key=os.environ["MASSIVE_API_KEY"])  # or RESTClient() to read MASSIVE_API_KEY

snapshots = client.get_snapshot_all("stocks", tickers=["AAPL", "MSFT", "NVDA"])
for s in snapshots:
    price = s.last_trade.price if s.last_trade and s.last_trade.price else s.day.close
    print(s.ticker, price, s.todays_change_percent)

one = client.get_snapshot_ticker("stocks", "AAPL")
print(one.last_trade.price, one.prev_day.close)
```

Signature: `get_snapshot_all(market_type, tickers=None, params=None, raw=False, include_otc=False)` → `List[TickerSnapshot]`.

---

## 4. End-of-Day Data

### 4a. Grouped Daily (all tickers, one call, free)

`GET /v2/aggs/grouped/locale/us/market/stocks/{date}` with `adjusted=true` (default) and `include_otc=false` (default).

```json
{
  "status": "OK",
  "adjusted": true,
  "queryCount": 3,
  "resultsCount": 3,
  "results": [
    {"T": "AAPL", "o": 26.07, "h": 26.25, "l": 25.91, "c": 25.9102, "v": 4369, "vw": 26.0407, "n": 74, "t": 1602705600000}
  ]
}
```

`T` = ticker, `o/h/l/c` = OHLC, `v` = volume, `vw` = VWAP, `n` = trade count, `t` = bar start (ms).

**Gotchas:**
- On weekends, holidays and today-before-close the result is empty (`resultsCount: 0`). Walk back day by day (up to ~5 days) until results appear.
- The response covers every US stock (~10k rows, a few MB). That is fine every few minutes, but don't poll it at 15 s intervals for no reason: EOD data only changes once a day.

```python
from datetime import date, timedelta

def latest_eod_closes(client: RESTClient, tickers: set[str]) -> dict[str, float]:
    d = date.today()
    for _ in range(7):
        bars = client.get_grouped_daily_aggs(d.isoformat(), adjusted=True)
        if bars:
            return {b.ticker: b.close for b in bars if b.ticker in tickers}
        d -= timedelta(days=1)
    return {}
```

### 4b. Previous day bar (per ticker)

`GET /v2/aggs/ticker/{ticker}/prev`

```json
{
  "status": "OK", "ticker": "AAPL", "adjusted": true, "resultsCount": 1,
  "results": [{"T": "AAPL", "o": 115.55, "h": 117.59, "l": 114.13, "c": 115.97, "v": 131704427, "vw": 116.3058, "t": 1605042000000}]
}
```

```python
prev = client.get_previous_close_agg("AAPL")  # PreviousCloseAgg (the client unwraps results)
print(prev.close if not isinstance(prev, list) else prev[0].close)
```

It costs one call per ticker. With 5 calls/min, ten tickers take two minutes, so prefer grouped daily.

### 4c. Daily open/close for a specific date

`GET /v1/open-close/{ticker}/{date}` returns `open, high, low, close, volume, preMarket, afterHours, symbol, from, status`.

```python
oc = client.get_daily_open_close_agg("AAPL", "2026-09-30")
print(oc.open, oc.close, oc.after_hours)
```

### 4d. Historical bars (for future chart backfill)

```python
bars = client.get_aggs("AAPL", 1, "day", "2026-01-01", "2026-09-30", adjusted=True, sort="asc", limit=5000)
for b in bars:
    print(b.timestamp, b.open, b.high, b.low, b.close, b.volume)
# list_aggs(...) is the paginating iterator version for large ranges.
```

`timespan` is one of `second, minute, hour, day, week, month, quarter, year`.

---

## 5. Errors and Rate Limits

| Status | Meaning | Handling |
|---|---|---|
| 200 + `status: "OK"` | Success | — |
| 200 + `status: "DELAYED"` | Plan has delayed data | Treat as success |
| 401 | Missing or invalid key | Log once and stop polling (config error) |
| 403 `NOT_AUTHORIZED` | Plan doesn't include endpoint (e.g. snapshot on free tier) | Switch to EOD fallback |
| 404 | Unknown ticker (single-ticker endpoints) | Mark the ticker as unavailable |
| 429 | Rate limit exceeded | Back off (double the interval, cap at 60 s) |
| 5xx / timeout | Transient | Keep last cached prices and retry next cycle |

Unknown tickers in the multi-ticker snapshot do **not** cause an error. They are simply missing from `tickers[]`.

The official `RESTClient` is **synchronous** (urllib3). In an asyncio app, call it via `await asyncio.to_thread(...)` so it doesn't block the event loop. It raises `massive.exceptions.BadResponse` on non-2xx responses, with the body in the message.

---

## 6. Recommended strategy for FinAlly

1. **Startup probe:** call the snapshot endpoint once for the current tickers.
   - Success → **live mode**. Poll the snapshot for the union of watched tickers every `MASSIVE_POLL_INTERVAL` seconds (default 15; 2 to 5 is fine on paid plans).
   - 403 → **EOD mode** (free key). Fetch grouped daily once, then refresh every 5 minutes. With a 5 calls/min budget this is safe. Prices are static during the day, and the UI will show few or no flashes. Log a clear warning: "Massive free tier: end-of-day prices only".
   - 401 → log an error. The app keeps running with whatever is in the cache, and the health endpoint reports a degraded status.
2. Always make **one request per cycle** for all tickers. Never loop per ticker.
3. Write each result into the shared `PriceCache`. The SSE layer never talks to Massive directly.

Sources: [Full Market Snapshot](https://massive.com/docs/rest/stocks/snapshots/full-market-snapshot), [Daily Market Summary](https://massive.com/docs/rest/stocks/aggregates/daily-market-summary), [Previous Day Bar](https://massive.com/docs/rest/stocks/aggregates/previous-day-bar), [Pricing](https://massive.com/pricing), [client-python](https://github.com/massive-com/client-python), [Massive + Python blog](https://massive.com/blog/polygon-io-with-python-for-stock-market-data).

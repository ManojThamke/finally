# Team Contracts — FinAlly Agent Team

Shared, binding interfaces between team members. `PLAN.md` is the spec; this file pins down
the details so everyone can build in parallel. If you must change a contract, edit this file
AND message every affected teammate.

## Team & File Ownership

Only edit files you own. Need a change elsewhere? Message the owner.

| Member | Name | Owns |
|---|---|---|
| Database Engineer | `db-engineer` | `backend/app/db/**`, `backend/tests/db/**` |
| Backend API Engineer | `backend-engineer` | `backend/app/main.py`, `backend/app/api/**` (except `chat.py`), `backend/app/services/**`, `backend/pyproject.toml`, `backend/uv.lock`, `backend/tests/api/**`, `backend/tests/services/**`, `backend/tests/conftest.py`, removal of `backend/dev_server.py` |
| LLM Engineer | `llm-engineer` | `backend/app/llm/**`, `backend/app/api/chat.py`, `backend/tests/llm/**` |
| Frontend Engineer | `frontend-engineer` | `frontend/**` |
| DevOps Engineer | `devops-engineer` | `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `scripts/**`, `.env.example`, `.gitignore`, `README.md`, `HOW_TO_RUN.md` |
| Integration Tester | `integration-tester` | `test/**` |

Existing `backend/app/market/**` is done — treat as read-only (backend-engineer may make small fixes if needed).
Python deps: LLM engineer needs `litellm`, `pydantic` — ask `backend-engineer` to add them (single owner of `pyproject.toml`), or add them yourself with `uv add` only after telling backend-engineer.

## Environment notes (this machine: WSL2)

- `uv` is not on PATH, and the sandbox blocks `pip install --user` (~/.local is read-only). Use a venv inside the session scratchpad dir (`$TMPDIR` / scratchpad) — db-engineer already has one with pytest there. Don't touch `backend/.venv` (it is a Windows venv).
- Node is the Windows build in `/mnt/c/Program Files/nodejs` (NOT `~/.local/bin`). Invoke via `cmd.exe /c "npm ..."` from a `/mnt/c` cwd (Windows interop may need the sandbox disabled).
- Docker Desktop engine is running (29.5.3). WSL integration is OFF: use `docker.exe` (outside the sandbox), not `docker`.
- The repo is on `/mnt/c` (slow FS). Keep `node_modules` installs to one place.
- `.gitignore` `lib/` rule is now scoped to `/backend/` (fixed by DevOps).
- Do NOT commit. The lead handles git.
- `.env` (project root) has `OPENROUTER_API_KEY`, `MASSIVE_API_KEY`, `LLM_MOCK`. Never print or copy its values.

## Python package layout (backend, package `app`)

```
backend/app/
  main.py              # FastAPI app: lifespan, routers, static files  (backend-engineer)
  market/              # done
  db/                  # (db-engineer)
    __init__.py        # re-exports public API below
    schema.sql         # CREATE TABLE IF NOT EXISTS ...
    connection.py, repository.py, seed.py ...
  services/            # (backend-engineer)
    portfolio.py       # execute_trade, build_portfolio, record_snapshot
    watchlist.py       # add_ticker, remove_ticker, list_watchlist_with_prices
  api/                 # routers
    portfolio.py, watchlist.py, health.py   (backend-engineer)
    chat.py                                  (llm-engineer)
  llm/                 # (llm-engineer) prompt, schema, client, mock, chat service
```

Note: PLAN.md mentions `backend/db/` for schema/seed; we place it at `backend/app/db/` so it ships inside the `app` package.

## Database API — `from app.db import ...`  (db-engineer)

- DB path: env `FINALLY_DB_PATH`; default `<repo root>/db/finally.db` (resolve relative to `backend/`). In Docker it is `/app/db/finally.db` (DevOps sets the env var).
- `DEFAULT_USER = "default"`; every function takes `user_id: str = DEFAULT_USER` as a keyword arg.
- `init_db(path: str | Path | None = None) -> None` — idempotent: creates dirs/tables, seeds default profile ($10,000) + 10 default tickers only if missing.
- `get_connection(path=None)` — context manager yielding `sqlite3.Connection` (`row_factory=sqlite3.Row`, foreign keys on, WAL). Commits on clean exit, rolls back on exception. Calls `init_db` lazily on first use for that path.
- Repository functions take `conn` first and do NOT commit:
  - `get_cash(conn) -> float`, `set_cash(conn, amount: float) -> None`
  - `list_watchlist(conn) -> list[str]` (ordered by `added_at`)
  - `add_watchlist_ticker(conn, ticker) -> bool` (False if already present)
  - `remove_watchlist_ticker(conn, ticker) -> bool` (False if absent)
  - `list_positions(conn) -> list[dict]` keys: `ticker, quantity, avg_cost, updated_at`
  - `get_position(conn, ticker) -> dict | None`
  - `upsert_position(conn, ticker, quantity, avg_cost) -> None`
  - `delete_position(conn, ticker) -> None`
  - `insert_trade(conn, ticker, side, quantity, price) -> dict` keys: `id, ticker, side, quantity, price, executed_at`
  - `list_trades(conn, limit: int = 50) -> list[dict]` newest first
  - `insert_snapshot(conn, total_value) -> dict` keys: `id, total_value, recorded_at`
  - `list_snapshots(conn, limit: int | None = None) -> list[dict]` oldest first
  - `insert_chat_message(conn, role, content, actions: dict | list | None = None) -> dict` keys: `id, role, content, actions (decoded JSON or None), created_at`
  - `list_chat_messages(conn, limit: int = 20) -> list[dict]` the most recent `limit`, returned oldest first
- Timestamps: ISO 8601 UTC strings (`datetime.now(timezone.utc).isoformat()`). IDs: `uuid4` strings.
- Tickers are stored upper-case (callers normalize with `app.market.normalize_ticker`).

## Services — `from app.services.portfolio import ...`  (backend-engineer)

- `class TradeError(Exception)` — message is user-facing ("Insufficient cash: need $X, have $Y", "Insufficient shares ...", "No price available for XYZ", "Quantity must be positive").
- `execute_trade(conn, price_cache, ticker, side, quantity) -> dict` — validates, updates cash/position (weighted avg cost on buy; delete position when qty hits ~0), inserts trade, records a snapshot. Returns the trade dict. Raises `TradeError`. Must not commit (caller's `get_connection` does).
- `build_portfolio(conn, price_cache) -> dict` — the `GET /api/portfolio` body below.
- `record_snapshot(conn, price_cache) -> dict`.
- `app.services.watchlist.add_ticker(conn, market_source, ticker) -> bool` / `remove_ticker(...)` — update DB and `market_source.add_ticker/remove_ticker` (don't remove from market source if a position still holds it). LLM engineer reuses these + `execute_trade`.
  - **As built:** `add_ticker` / `remove_ticker` are `async` (market source methods are async). `validate_ticker` + `InvalidTickerError(ValueError)` live in `app.services.watchlist`; trades on invalid tickers raise `TradeError` (→ 400). Trading a ticker that is neither watched nor held → 400 "No price available for X" (not auto-tracked).
- Background task in lifespan: snapshot every 30s (env `SNAPSHOT_INTERVAL`).
- App state: `app.state.price_cache`, `app.state.market_source`. Market source starts with union(watchlist, position tickers).

## HTTP API (all JSON; errors are `{"detail": "<message>"}`)

`GET /api/health` → `{"status":"ok", "source":..., "tickers":N, ...}`

`GET /api/stream/prices` (exists) → SSE `event: prices`, `data` = object keyed by ticker, each value:
`{ticker, price, previous_price, session_open, timestamp (unix s), change, change_percent, day_change_percent, direction: "up"|"down"|"flat"}`

`GET /api/portfolio` →
```json
{"cash_balance": 10000.0, "positions_value": 0.0, "total_value": 10000.0,
 "unrealized_pnl": 0.0, "unrealized_pnl_percent": 0.0,
 "positions": [{"ticker":"AAPL","quantity":10,"avg_cost":190.1,"current_price":191.0,
   "market_value":1910.0,"unrealized_pnl":9.0,"unrealized_pnl_percent":0.47,"weight":16.0}]}
```
(`weight` = % of total portfolio value; if no live price, use `avg_cost` as current price.)

`POST /api/portfolio/trade` body `{"ticker":"AAPL","quantity":10,"side":"buy"|"sell"}` →
200 `{"trade": {id,ticker,side,quantity,price,executed_at}, "portfolio": <GET /api/portfolio body>}`; 400 `{"detail": "..."}` on validation failure; 422 on malformed body.

`GET /api/portfolio/history` → `{"snapshots": [{"total_value": 10000.0, "recorded_at": "..."}]}` oldest first.

`GET /api/watchlist` → `{"tickers": [{"ticker":"AAPL","price":190.0|null,"previous_price":..,"change":..,"change_percent":..,"day_change_percent":..,"direction":..}]}`

`POST /api/watchlist` body `{"ticker":"PYPL"}` → 201 `{"ticker":"PYPL","added":true}`; 409 if already present; 400 if invalid (empty / non `^[A-Z.]{1,10}$` after normalize).

`DELETE /api/watchlist/{ticker}` → 200 `{"ticker":"PYPL","removed":true}`; 404 if not present.

`POST /api/chat` body `{"message":"..."}` →
```json
{"id":"uuid","role":"assistant","message":"text","created_at":"...",
 "trades":[{"ticker":"AAPL","side":"buy","quantity":10,"status":"executed","price":190.1,"error":null}],
 "watchlist_changes":[{"ticker":"PYPL","action":"add","status":"executed","error":null}]}
```
`status` is `"executed"` or `"failed"` (with `error` message). 400 on empty message. LLM errors → 200 with an apologetic `message` and empty actions (never a 500 to the UI).

`GET /api/chat/history` → `{"messages":[{id, role, content, actions, created_at}]}` oldest first (frontend restores chat on reload).

Static: FastAPI serves the Next.js export from `backend/static/` (Docker copies `frontend/out` there; override with env `FINALLY_STATIC_DIR`). `/` → `index.html`. Unknown non-`/api` paths fall back to `index.html`. If the dir is missing, API still works.

## LLM provider selection (added at user request)

Env `LLM_PROVIDER` = `auto` (default) | `openrouter` | `gemini`. `auto`: OpenRouter/Cerebras (PLAN §9) if `OPENROUTER_API_KEY` set, else Gemini; also retries once on Gemini when OpenRouter fails with an auth/credit error (400/401/402/403). Gemini model `gemini/gemini-2.5-flash`, override with `LLM_MODEL` (Gemini only). Keys: `OPENROUTER_API_KEY`, `GEMINI_API_KEY`.

## LLM mock mode (llm-engineer; relied on by integration-tester)

`LLM_MOCK=true` → no network. Deterministic rules on the lower-cased user message:
- contains `buy` and a ticker-like word + number, e.g. "buy 5 AAPL" → trade buy 5 AAPL, message `"Mock: buying 5 AAPL."`
- "sell N TICKER" → sell trade similarly
- "add TICKER" / "watch TICKER" → watchlist add; "remove TICKER" → watchlist remove
- otherwise → message `"Mock response: I am FinAlly, your AI trading assistant."` and no actions.

## Frontend test hooks (frontend-engineer; relied on by integration-tester)

Use these `data-testid`s:
`connection-status` (attr `data-status="connected|reconnecting|disconnected"`), `header-total-value`, `header-cash`,
`watchlist`, `watchlist-row-{TICKER}`, `watchlist-price-{TICKER}`, `watchlist-remove-{TICKER}`, `watchlist-add-input`, `watchlist-add-button`,
`main-chart`, `selected-ticker`,
`trade-ticker`, `trade-quantity`, `trade-buy`, `trade-sell`, `trade-error`,
`positions-table`, `position-row-{TICKER}`,
`heatmap`, `pnl-chart`,
`chat-panel`, `chat-input`, `chat-send`, `chat-message` (each message; attr `data-role`), `chat-loading`, `chat-action` (each inline trade/watchlist confirmation).

## Coordination protocol

- Message teammates by name with `SendMessage`. Keep messages short and concrete (file, endpoint, failing behaviour, expected behaviour).
- When your piece is usable, message `integration-tester` and the lead with what's ready and how to run it.
- Integration tester reports bugs directly to the owning member; owner fixes and replies "fixed: <summary>".
- Run your own unit tests before declaring done: backend `cd backend && uv run pytest`; frontend `npm test` in `frontend/`.

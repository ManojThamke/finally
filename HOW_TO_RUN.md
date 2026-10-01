# How to Run

FinAlly ships as a single Docker container that serves the API, the SSE price stream and the
frontend on port 8000. You can also run the backend and frontend directly for development.

## 1. Configure

```bash
cp .env.example .env
```

| Variable | Required | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | For AI chat* | Primary LLM provider (OpenRouter → Cerebras) |
| `GEMINI_API_KEY` | For AI chat* | Alternative LLM provider (Google Gemini) |
| `LLM_PROVIDER` | No | `auto` (default), `openrouter` or `gemini` |
| `LLM_MODEL` | No | Gemini model override, e.g. `gemini/gemini-2.5-flash` (default) |
| `MASSIVE_API_KEY` | No | Empty = built-in market simulator |
| `LLM_MOCK` | No | `true` = deterministic mock chat replies (no network) |

\* Chat needs either `OPENROUTER_API_KEY` or `GEMINI_API_KEY`. With neither, chat replies with an
apology unless `LLM_MOCK=true`.

LLM provider selection:

- `LLM_PROVIDER=auto` (default) uses OpenRouter if `OPENROUTER_API_KEY` is set, otherwise Gemini.
  If OpenRouter returns an auth or credit error (401/402) and `GEMINI_API_KEY` is set, the request
  is retried once with Gemini.
- `LLM_PROVIDER=openrouter` or `gemini` forces that provider, with no fallback.
- `LLM_MODEL` only affects Gemini and takes a LiteLLM model string. The OpenRouter model is fixed.
- `LLM_MOCK=true` overrides all of the above and makes no network calls.

Advanced (optional): `MASSIVE_POLL_INTERVAL` (seconds between Massive API polls),
`SIM_SPEED` (simulated-time multiplier, default 50 so prices visibly move) / `SIM_TICK_INTERVAL` /
`SIM_SEED` (simulator tuning), `SNAPSHOT_INTERVAL`
(portfolio snapshot cadence, default 30s).

## 2. Run with Docker (recommended)

Prerequisite: Docker (Docker Desktop on macOS/Windows).

**macOS / Linux:**

```bash
./scripts/start_mac.sh            # builds the image on first run, starts the container, opens the browser
./scripts/start_mac.sh --build    # force a rebuild (after code changes)
./scripts/start_mac.sh --no-open  # don't open a browser
./scripts/stop_mac.sh             # stop and remove the container (data is kept)
```

**Windows (PowerShell):**

```powershell
.\scripts\start_windows.ps1            # add -Build to force a rebuild, -NoOpen to skip the browser
.\scripts\stop_windows.ps1
```

If PowerShell blocks the script, run it once with
`powershell -ExecutionPolicy Bypass -File .\scripts\start_windows.ps1`.

**Plain Docker / Compose:**

```bash
docker build -t finally .
docker run -d --name finally -v finally-data:/app/db -p 8000:8000 --env-file .env finally
# or
docker compose up --build -d
```

Then open http://localhost:8000. Logs: `docker logs -f finally`.

Data (cash, positions, trades, watchlist, chat history) lives in SQLite at `/app/db/finally.db`
inside the named volume `finally-data`, so it survives restarts and rebuilds. To reset to a
fresh $10,000 account:

```bash
./scripts/stop_mac.sh && docker volume rm finally-data
```

Set `FINALLY_PORT=9000` before the start script to use another host port.

## 3. Local development (without Docker)

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 20+.

### Backend (FastAPI)

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

The backend reads `.env` from the project root (or export the variables in your shell). The
SQLite file is created at `db/finally.db` in the project root on first request (override with
`FINALLY_DB_PATH`). If `backend/static/` holds a frontend build (override with
`FINALLY_STATIC_DIR`), it is served at `/`; otherwise only the API is available.

### Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev        # dev server with hot reload on http://localhost:3000
npm run build      # static export into frontend/out/
```

In dev mode, Next.js proxies `/api/*` to the backend at `http://127.0.0.1:8000` (override with
`FINALLY_BACKEND_URL`), so start the backend first and open http://localhost:3000.

To serve a local production build from the backend, copy it into place:

```bash
cd frontend && npm run build && rm -rf ../backend/static && cp -r out ../backend/static
```

## 4. Check it works

| URL | What you should see |
|---|---|
| http://localhost:8000/ | The FinAlly trading terminal |
| http://localhost:8000/api/health | `{"status":"ok","source":"simulator",...}` |
| http://localhost:8000/api/portfolio | Cash balance, positions, total value |
| http://localhost:8000/api/stream/prices | Live `prices` events every ~500ms |
| http://localhost:8000/docs | Interactive API docs |

```bash
curl http://localhost:8000/api/health
curl -N http://localhost:8000/api/stream/prices
```

## 5. Tests

```bash
cd backend && uv run pytest     # backend unit tests
cd frontend && npm test         # frontend unit tests
```

End-to-end Playwright tests live in `test/` and run against the Docker image with
`LLM_MOCK=true` (see `test/` for the compose file and instructions).

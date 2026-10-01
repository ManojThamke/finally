# How to Run

> **Current state:** only the market data backend is built. The full app (portfolio,
> watchlist, chat, frontend, Docker image) is not yet available. For now you can run a
> dev server that streams simulated live prices for the 10 default tickers.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) — or plain `pip` + `venv`

## Run the market data dev server

### Option A — with uv (recommended)

```bash
cd backend
uv sync
uv run uvicorn dev_server:app --port 8000
```

### Option B — without uv

**Windows (PowerShell):**

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install fastapi uvicorn numpy httpx
.venv\Scripts\python -m uvicorn dev_server:app --port 8000
```

**macOS / Linux:**

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/python -m pip install fastapi uvicorn numpy httpx
.venv/bin/python -m uvicorn dev_server:app --port 8000
```

Stop the server with `Ctrl+C`.

## Check it works

| URL | What you should see |
|---|---|
| http://localhost:8000/api/health | `{"status":"ok","source":"simulator","tickers":10,...}` |
| http://localhost:8000/api/stream/prices | A live stream of `prices` events, updating ~every 500ms |
| http://localhost:8000/docs | Interactive API docs |

From a terminal:

```bash
curl http://localhost:8000/api/health
curl -N http://localhost:8000/api/stream/prices
```

## Real market data (optional)

By default prices come from the built-in simulator. To use real data from the Massive
(Polygon.io) API, set `MASSIVE_API_KEY` before starting the server:

```bash
MASSIVE_API_KEY=your-key uv run uvicorn dev_server:app --port 8000      # macOS / Linux
```

```powershell
$env:MASSIVE_API_KEY = "your-key"; uv run uvicorn dev_server:app --port 8000   # PowerShell
```

## Run the tests

```bash
cd backend
uv run pytest
```

## Full app (coming later)

Once the rest of the platform is built, the whole app will run in a single Docker container:

```bash
docker build -t finally .
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
# then open http://localhost:8000
```

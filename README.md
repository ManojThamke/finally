# FinAlly — Finance Ally

An AI-powered trading workstation: live-streaming market data, a simulated $10,000 portfolio, and an LLM chat assistant that can analyze positions and execute trades for you. Think Bloomberg terminal with an AI copilot.

Built entirely by coding agents as the capstone project for an agentic AI coding course. The full specification is in [`planning/PLAN.md`](planning/PLAN.md).

## Status

Work in progress.

| Component | State |
|---|---|
| Market data (simulator, Massive client, price cache, SSE stream) | Built and tested |
| Portfolio, watchlist, and chat APIs; SQLite database | Planned |
| Next.js frontend | Planned |
| Dockerfile and start/stop scripts | Planned |
| Playwright E2E tests | Planned |

## Architecture

One Docker container serving everything on port 8000:

- **Frontend** — Next.js (TypeScript) static export, served by FastAPI
- **Backend** — FastAPI, managed with `uv`
- **Database** — SQLite at `db/finally.db`, created and seeded on first run
- **Real-time data** — Server-Sent Events at `/api/stream/prices`
- **AI** — LiteLLM → OpenRouter (Cerebras inference) with structured outputs
- **Market data** — built-in GBM simulator by default, or real data via the Massive API

## Project Layout

```
backend/     FastAPI uv project (market data lives in app/market/)
frontend/    Next.js project
planning/    Project documentation shared by all agents
test/        Playwright E2E tests
db/          Runtime mount point for the SQLite file
```

## Configuration

Create a `.env` file in the project root:

```bash
OPENROUTER_API_KEY=your-key   # Required for AI chat
MASSIVE_API_KEY=              # Optional: real market data (simulator used if empty)
LLM_MOCK=false                # Optional: "true" for deterministic mock LLM responses
```

## Development

Backend tests and linting:

```bash
cd backend
uv sync --extra dev
uv run pytest
uv run ruff check .
```

Watch the market simulator run in the terminal:

```bash
cd backend
uv run market_data_demo.py
```

## License

See [LICENSE](LICENSE).

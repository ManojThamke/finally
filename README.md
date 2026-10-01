# FinAlly — AI Trading Workstation

A visually stunning AI-powered trading workstation that streams live market data, simulates portfolio trading, and integrates an LLM chat assistant that can analyze positions and execute trades via natural language.

Built entirely by coding agents as a capstone project for an agentic AI coding course.

## Features

- **Live price streaming** via SSE with green/red flash animations
- **Simulated portfolio** — $10k virtual cash, market orders, instant fills
- **Portfolio visualizations** — heatmap (treemap), P&L chart, positions table
- **AI chat assistant** — analyzes holdings, suggests and auto-executes trades
- **Watchlist management** — track tickers manually or via AI
- **Dark terminal aesthetic** — Bloomberg-inspired, data-dense layout

## Architecture

Single Docker container serving everything on port 8000:

- **Frontend**: Next.js (static export) with TypeScript and Tailwind CSS
- **Backend**: FastAPI (Python/uv) with SSE streaming
- **Database**: SQLite with lazy initialization
- **AI**: LiteLLM → OpenRouter (Cerebras inference) with structured outputs
- **Market data**: Built-in GBM simulator (default) or Massive API (optional)

## Quick Start

```bash
cp .env.example .env          # then add your OPENROUTER_API_KEY
./scripts/start_mac.sh        # macOS / Linux  (Windows: .\scripts\start_windows.ps1)
# open http://localhost:8000
./scripts/stop_mac.sh         # stop (portfolio data is kept in the finally-data volume)
```

Or with plain Docker:

```bash
docker build -t finally .
docker run -d --name finally -v finally-data:/app/db -p 8000:8000 --env-file .env finally
```

No API key? Set `LLM_MOCK=true` in `.env` to get deterministic mock chat replies.
See [HOW_TO_RUN.md](HOW_TO_RUN.md) for local development without Docker and for running tests.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes* | OpenRouter API key for AI chat (primary provider) |
| `GEMINI_API_KEY` | Yes* | Google Gemini key, alternative/fallback LLM provider |
| `LLM_PROVIDER` | No | `auto` (default), `openrouter` or `gemini` |
| `LLM_MODEL` | No | Gemini model override (default `gemini/gemini-2.5-flash`) |
| `MASSIVE_API_KEY` | No | Massive (Polygon.io) key for real market data; omit to use simulator |
| `LLM_MOCK` | No | Set `true` for deterministic mock LLM responses (testing) |

\* AI chat needs at least one of `OPENROUTER_API_KEY` or `GEMINI_API_KEY` (or `LLM_MOCK=true`). See [HOW_TO_RUN.md](HOW_TO_RUN.md) for provider selection.

## Project Structure

```
finally/
├── frontend/    # Next.js static export
├── backend/     # FastAPI uv project
├── planning/    # Project documentation and agent contracts
├── test/        # Playwright E2E tests
├── db/          # SQLite volume mount (runtime)
└── scripts/     # Docker start/stop helpers (macOS/Linux + Windows)
```

## License

See [LICENSE](LICENSE).

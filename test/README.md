# FinAlly E2E tests

Playwright tests for the full app: the HTTP API contract (`e2e/api/`) and the browser UI (`e2e/ui/`).
They target the `data-testid`s and endpoints defined in `planning/TEAM_CONTRACTS.md`, and expect
the backend to run with `LLM_MOCK=true`.

Projects (run in this order, serially, against one shared database):

| Project | Files | What it covers |
|---|---|---|
| `fresh` | `e2e/ui/fresh-start.spec.ts` | Default watchlist, $10,000 cash, prices streaming, connected status |
| `api` | `e2e/api/*.spec.ts` | Status codes (400/404/409/422), response shapes, SSE event format, mock chat, static fallback |
| `ui` | `e2e/ui/*.spec.ts` | Watchlist add/remove, buy/sell, heatmap + P&L chart, AI chat, SSE reconnection |

Tests clean up after themselves (sell positions they open, remove tickers they add) and use relative
assertions, so they can run against a database that already has data. The strict "exactly $10,000 /
exactly 10 tickers" checks only run when `FRESH_DB=1`.

## Option 1: Docker Compose (recommended, matches CI)

Builds the app image from the repo-root `Dockerfile`, starts it with `LLM_MOCK=true` and a throwaway
tmpfs database, waits for `/api/health`, then runs the suite in the official Playwright container.

From the repo root:

```bash
docker compose -f test/docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from playwright
docker compose -f test/docker-compose.test.yml down -v
```

The HTML report is written to `test/playwright-report/` (open with `npx playwright show-report` from `test/`).

## Option 2: Locally against a running server

1. Start the app with the mock LLM and a scratch database, e.g. from `backend/`:

   ```bash
   LLM_MOCK=true FINALLY_DB_PATH=/tmp/finally-e2e.db uv run uvicorn app.main:app --port 8000
   ```

   (Build the frontend first — `cd frontend && npm run build` — and copy/point `FINALLY_STATIC_DIR`
   at `frontend/out` so the UI is served. Or just run the Docker image with `-e LLM_MOCK=true`.)

2. Run the tests from `test/`:

   ```bash
   npm install
   npx playwright install chromium
   npx playwright test                 # everything
   npx playwright test --project=api --no-deps  # API contract only (needs Chromium for the SSE check)
   FRESH_DB=1 npx playwright test      # also assert the exact seed state (new DB only)
   ```

   Point at another server with `BASE_URL=http://host:port`.

Useful flags: `--headed`, `--debug`, `-g "watchlist"`, `npx playwright show-report`.

## Notes

- `@playwright/test` is pinned to `1.63.0`; the compose file uses the matching
  `mcr.microsoft.com/playwright:v1.63.0-noble` image. Bump both together.
- The SSE resilience test aborts `/api/stream/prices` and toggles the browser offline, then checks the
  `connection-status` indicator leaves `connected` and returns to it once the network is restored.
- Chat tests rely on the deterministic mock rules: `"buy 1 AAPL"` → `"Mock: buying 1 AAPL."` plus an
  executed trade; any other message → `"Mock response: I am FinAlly, your AI trading assistant."`.
- The app service is named `finally-app`, not `app`: Chromium HSTS-preloads the `.app` TLD and
  would force `https://app:8000`, which fails with `ERR_SSL_PROTOCOL_ERROR`.
- On this WSL2 machine Docker Desktop's integration is off; run `docker.exe compose ...` (or the same
  command from a Windows shell) instead of `docker compose`.

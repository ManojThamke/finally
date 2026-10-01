import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.BASE_URL || "http://localhost:8000";

export default defineConfig({
  testDir: "./e2e",
  // All specs share one backend + SQLite DB, so run serially for determinism.
  fullyParallel: false,
  workers: 1,
  retries: 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
  ],
  outputDir: "test-results",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    viewport: { width: 1600, height: 1000 },
  },
  projects: [
    {
      // Runs first so it can observe the untouched seed state (when FRESH_DB=1).
      name: "fresh",
      testMatch: /fresh-start\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1600, height: 1000 } },
    },
    {
      name: "api",
      testMatch: /api\/.*\.spec\.ts/,
      dependencies: ["fresh"],
    },
    {
      name: "ui",
      testMatch: /ui\/.*\.spec\.ts/,
      testIgnore: /fresh-start\.spec\.ts/,
      dependencies: ["fresh"],
      use: { ...devices["Desktop Chrome"], viewport: { width: 1600, height: 1000 } },
    },
  ],
});

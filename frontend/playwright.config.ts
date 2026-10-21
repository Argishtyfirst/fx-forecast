import { defineConfig, devices } from "@playwright/test";

// Browsers live in frontend/.pw-browsers unless PLAYWRIGHT_BROWSERS_PATH is set (see the npm scripts).
const PORT = 5173; // the dev server; every /api call is intercepted in the tests (e2e/fixtures.ts)
const MOCK_PORT = 5174; // a second dev server in VITE_USE_MOCKS=1 mode, for e2e/mock-mode.spec.ts

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    timezoneId: "UTC",
    locale: "en-GB",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      testIgnore: /mock-mode\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], baseURL: `http://localhost:${PORT}` },
    },
    {
      name: "mock-mode",
      testMatch: /mock-mode\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], baseURL: `http://localhost:${MOCK_PORT}` },
    },
  ],
  webServer: [
    {
      command: `npx vite --port ${PORT} --strictPort`,
      url: `http://localhost:${PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: { VITE_USE_MOCKS: "0" },
    },
    {
      command: `npx vite --port ${MOCK_PORT} --strictPort`,
      url: `http://localhost:${MOCK_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: { VITE_USE_MOCKS: "1" },
    },
  ],
});

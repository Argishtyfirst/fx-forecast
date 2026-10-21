import { test as base, expect, type Page } from "@playwright/test";
import { mockApi } from "../src/mocks";

/** "Now" for the app: shortly after the fixtures' health check on 21 Oct 2026. */
export const NOW = new Date("2026-10-21T16:00:00Z");

/** Serve every /api request from the fixture JSON (same router as the mock dev mode). */
export async function routeApi(page: Page, overrides: Record<string, { status: number; body: unknown }> = {}) {
  // Match the API path only: a glob like **/api/** would also catch Vite modules under /src/api/.
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const url = new URL(route.request().url());
    const key = url.pathname + url.search;
    const hit = Object.entries(overrides).find(([prefix]) => key.startsWith(prefix));
    const { status, body } = hit ? hit[1] : mockApi(key);
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  });
}

export const test = base.extend<{ mockedPage: Page }>({
  mockedPage: async ({ page }, use) => {
    await page.clock.setFixedTime(NOW);
    await routeApi(page);
    await use(page);
  },
});

export { expect };

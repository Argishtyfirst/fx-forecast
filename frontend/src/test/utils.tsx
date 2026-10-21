import { vi } from "vitest";
import { clearApiCache } from "../api/client";
import { mockApi } from "../mocks";

/** "Now" for tests: shortly after the fixtures' health check on 21 Oct 2026 (UTC). */
export const NOW = new Date("2026-10-21T16:00:00Z");

type Override = { status: number; body: unknown };

/** Route fetch("/api/...") to the fixture router, with optional per-prefix overrides. */
export function mockFetch(overrides: Record<string, Override> = {}) {
  clearApiCache();
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      calls.push(url);
      const hit = Object.entries(overrides).find(([prefix]) => url.startsWith(prefix));
      const { status, body } = hit ? hit[1] : mockApi(url);
      return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

export function useFixedClock() {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
}

import type {
  BacktestResponse,
  EventsResponse,
  ForecastRunResponse,
  HealthResponse,
  LatestForecastResponse,
  MeetingStudyResponse,
  PairsResponse,
  QuotesResponse,
  RatesResponse,
} from "./types";

/** True when the app runs on fixture data (VITE_USE_MOCKS=1). The UI labels this clearly. */
export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === "1";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly url: string;

  constructor(status: number, detail: string, url: string) {
    super(status ? `${status}: ${detail}` : detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.url = url;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }
}

type Query = Record<string, string | number | null | undefined>;

export function buildUrl(path: string, query: Query = {}): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== null && v !== undefined && v !== "") params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

async function detailOf(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (body.detail) return JSON.stringify(body.detail);
  } catch {
    // Not JSON; fall through.
  }
  return res.statusText || "Request failed";
}

async function mockFetch<T>(url: string): Promise<T> {
  const { mockApi } = await import("../mocks");
  const { status, body } = mockApi(url);
  // A short delay keeps the loading states honest in mock mode.
  await new Promise((r) => setTimeout(r, 120));
  if (status >= 400) {
    const detail = (body as { detail?: string }).detail ?? "Request failed";
    throw new ApiError(status, detail, url);
  }
  return structuredClone(body) as T;
}

const CACHE_TTL_MS = 60_000;
const cache = new Map<string, { at: number; promise: Promise<unknown> }>();

/** Clears the in-memory response cache (used by Retry and by tests). */
export function clearApiCache(): void {
  cache.clear();
}

/**
 * Fetches JSON through a short-lived cache shared by all views. Requests are not aborted on
 * unmount (other views may share the promise); hooks ignore results they no longer need.
 */
export async function getJson<T>(url: string): Promise<T> {
  const hit = cache.get(url);
  if (hit && Date.now() - hit.at < CACHE_TTL_MS) return hit.promise as Promise<T>;

  const promise = (async () => {
    if (USE_MOCKS) return mockFetch<T>(url);
    let res: Response;
    try {
      res = await fetch(url, { headers: { Accept: "application/json" } });
    } catch {
      throw new ApiError(0, "The API is not reachable. Is the backend running on port 8000?", url);
    }
    if (!res.ok) throw new ApiError(res.status, await detailOf(res), url);
    try {
      return (await res.json()) as T;
    } catch {
      throw new ApiError(res.status, "The API returned a response that is not JSON.", url);
    }
  })();

  cache.set(url, { at: Date.now(), promise });
  // Failed requests are not cached, so a retry fetches again.
  promise.catch(() => cache.delete(url));
  return promise;
}

/** Like getJson, but a 404 resolves to null: "no data yet" is an empty state, not an error. */
async function getOrNull<T>(url: string): Promise<T | null> {
  try {
    return await getJson<T>(url);
  } catch (err) {
    if (err instanceof ApiError && err.isNotFound) return null;
    throw err;
  }
}

export const api = {
  pairs: () => getJson<PairsResponse>("/api/pairs"),

  rates: (pair: string, from?: string, to?: string) =>
    getJson<RatesResponse>(buildUrl(`/api/rates/${pair}`, { from, to })),

  latestForecast: (pair: string) =>
    getOrNull<LatestForecastResponse>(`/api/forecasts/${pair}/latest`),

  forecastRun: (pair: string, runDate?: string) =>
    getOrNull<ForecastRunResponse>(buildUrl(`/api/forecasts/${pair}`, { run_date: runDate })),

  backtests: (pair: string, horizon?: number) =>
    getOrNull<BacktestResponse>(buildUrl(`/api/backtests/${pair}`, { horizon })),

  /** Provider rates for converting `amount` of the base; null (404) means none for this pair. */
  quotes: (pair: string, amount: number) =>
    getOrNull<QuotesResponse>(buildUrl(`/api/quotes/${pair}`, { amount })),

  meetings: (pair: string, lookbackDays = 365) =>
    getOrNull<MeetingStudyResponse>(buildUrl(`/api/meetings/${pair}`, { lookback_days: lookbackDays })),

  events: (bank?: string, from?: string) =>
    getJson<EventsResponse>(buildUrl("/api/events", { bank, from })),

  health: () => getJson<HealthResponse>("/api/health"),
};

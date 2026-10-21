/**
 * Fixture data for tests, Playwright route interception and the opt-in mock dev mode
 * (VITE_USE_MOCKS=1). Regenerate with `node scripts/generate-mocks.mjs`.
 * The values are invented. They are internally consistent, but they are not market data.
 */
import type {
  BacktestResponse,
  EventsResponse,
  ForecastRunResponse,
  HealthResponse,
  LatestForecastResponse,
  MeetingStudyResponse,
  PairsResponse,
  RatesResponse,
} from "../api/types";
import backtestsEURUSD from "./backtests.EURUSD.json" with { type: "json" };
import backtestsEURAMD from "./backtests.EURAMD.json" with { type: "json" };
import backtestsUSDAMD from "./backtests.USDAMD.json" with { type: "json" };
import events from "./events.json" with { type: "json" };
import latestEURAMD from "./forecast-latest.EURAMD.json" with { type: "json" };
import latestEURUSD from "./forecast-latest.EURUSD.json" with { type: "json" };
import latestUSDAMD from "./forecast-latest.USDAMD.json" with { type: "json" };
import runEURAMD from "./forecast-run.EURAMD.json" with { type: "json" };
import runEURUSD from "./forecast-run.EURUSD.json" with { type: "json" };
import runUSDAMD from "./forecast-run.USDAMD.json" with { type: "json" };
import health from "./health.json" with { type: "json" };
import meetingsEURAMD from "./meetings.EURAMD.json" with { type: "json" };
import meetingsEURUSD from "./meetings.EURUSD.json" with { type: "json" };
import meetingsUSDAMD from "./meetings.USDAMD.json" with { type: "json" };
import pairs from "./pairs.json" with { type: "json" };
import ratesEURAMD from "./rates.EURAMD.json" with { type: "json" };
import ratesEURUSD from "./rates.EURUSD.json" with { type: "json" };
import ratesUSDAMD from "./rates.USDAMD.json" with { type: "json" };

export const fixtures = {
  pairs: pairs as PairsResponse,
  health: health as HealthResponse,
  events: events as unknown as EventsResponse,
  rates: { EURUSD: ratesEURUSD, USDAMD: ratesUSDAMD, EURAMD: ratesEURAMD } as Record<
    string,
    RatesResponse
  >,
  latest: { EURUSD: latestEURUSD, USDAMD: latestUSDAMD, EURAMD: latestEURAMD } as unknown as Record<
    string,
    LatestForecastResponse
  >,
  run: { EURUSD: runEURUSD, USDAMD: runUSDAMD, EURAMD: runEURAMD } as Record<
    string,
    ForecastRunResponse
  >,
  meetings: { EURUSD: meetingsEURUSD, USDAMD: meetingsUSDAMD, EURAMD: meetingsEURAMD } as Record<
    string,
    MeetingStudyResponse
  >,
  backtests: {
    EURUSD: backtestsEURUSD,
    USDAMD: backtestsUSDAMD,
    EURAMD: backtestsEURAMD,
  } as Record<string, BacktestResponse>,
};

export interface MockResult {
  status: number;
  body: unknown;
}

const notFound = (detail: string): MockResult => ({ status: 404, body: { detail } });

/** Resolve an /api/... URL (path plus query) against the fixtures, like the real API would. */
export function mockApi(url: string): MockResult {
  const u = new URL(url, "http://mock.local");
  const parts = u.pathname.replace(/^\/api\/?/, "").split("/").filter(Boolean);
  const q = u.searchParams;
  const [resource, pair, sub] = parts;

  switch (resource) {
    case "pairs":
      return { status: 200, body: fixtures.pairs };
    case "health":
      return { status: 200, body: fixtures.health };
    case "rates": {
      const data = fixtures.rates[pair ?? ""];
      if (!data) return notFound(`Unknown pair ${pair}`);
      const from = q.get("from");
      const to = q.get("to");
      const rates = data.rates.filter(
        (r) => (!from || r.date >= from) && (!to || r.date <= to),
      );
      return { status: 200, body: { ...data, rates } };
    }
    case "forecasts": {
      if (sub === "latest") {
        const data = fixtures.latest[pair ?? ""];
        return data ? { status: 200, body: data } : notFound("No forecast yet");
      }
      const data = fixtures.run[pair ?? ""];
      if (!data) return notFound("No forecast yet");
      const runDate = q.get("run_date");
      if (runDate && runDate !== data.run_date) {
        // Older runs are not in the fixtures; serve the latest rows under the requested date.
        return { status: 200, body: { ...data, run_date: runDate } };
      }
      return { status: 200, body: data };
    }
    case "backtests": {
      const data = fixtures.backtests[pair ?? ""];
      if (!data) return notFound("No backtest yet");
      const horizon = q.get("horizon");
      const h = horizon ? Number(horizon) : null;
      const pick = <T extends { horizon_days: number }>(rows: T[] | undefined) =>
        (rows ?? []).filter((r) => h === null || r.horizon_days === h);
      return {
        status: 200,
        body: {
          ...data,
          metrics: pick(data.metrics),
          event_metrics: pick(data.event_metrics),
          ai_track: pick(data.ai_track),
        },
      };
    }
    case "meetings": {
      const data = fixtures.meetings[pair ?? ""];
      return data ? { status: 200, body: data } : notFound("No meeting study yet");
    }
    case "events": {
      const bank = q.get("bank");
      const from = q.get("from");
      return {
        status: 200,
        body: {
          decisions: fixtures.events.decisions.filter(
            (d) => (!bank || d.bank === bank) && (!from || d.date >= from),
          ),
          upcoming: fixtures.events.upcoming.filter((m) => !bank || m.bank === bank),
        },
      };
    }
    default:
      return notFound(`Unknown endpoint ${u.pathname}`);
  }
}

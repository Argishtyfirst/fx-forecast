// Generates the fixture JSON in src/mocks/. Deterministic (seeded), so reruns are stable.
// Usage: node scripts/generate-mocks.mjs
// The numbers are invented but internally consistent: bands come from a Student-t GARCH sigma,
// the forward rate from covered interest parity, and meetings from the 2026 calendars.

import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "mocks");
mkdirSync(OUT, { recursive: true });

const SPOT_DATE = "2026-10-21";
const CHECKED_AT = "2026-10-21T15:42:10Z";

// --- helpers --------------------------------------------------------------------------

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function gaussian(rand) {
  const u = Math.max(rand(), 1e-12);
  const v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}
const iso = (d) => d.toISOString().slice(0, 10);
const addDays = (s, n) => {
  const d = new Date(`${s}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return iso(d);
};
const weekday = (s) => new Date(`${s}T00:00:00Z`).getUTCDay();
const round = (x, dp) => Number(x.toFixed(dp));

const HOLIDAYS = {
  // TARGET2 closing days in the window.
  EURUSD: new Set(["2026-04-03", "2026-04-06", "2026-05-01", "2026-12-25", "2026-12-26"]),
  // Armenian public holidays in the window (weekday ones matter).
  USDAMD: new Set(["2026-04-24", "2026-05-01", "2026-05-28", "2026-09-21", "2026-12-31"]),
};
// EUR/AMD is the CBA daily average rate too, so it follows the Armenian calendar.
HOLIDAYS.EURAMD = HOLIDAYS.USDAMD;
const isTradingDay = (pair, s) => weekday(s) !== 0 && weekday(s) !== 6 && !HOLIDAYS[pair].has(s);
function tradingDaysBack(pair, end, n) {
  const out = [];
  let cur = end;
  while (out.length < n) {
    if (isTradingDay(pair, cur)) out.push(cur);
    cur = addDays(cur, -1);
  }
  return out.reverse();
}
function addTradingDays(pair, start, n) {
  let cur = start;
  let left = n;
  while (left > 0) {
    cur = addDays(cur, 1);
    if (isTradingDay(pair, cur)) left -= 1;
  }
  return cur;
}

// Student-t quantiles scaled to unit variance: z * sqrt((nu - 2) / nu).
const T_QUANTILES = {
  6: { 0.75: 0.7176, 0.9: 1.4398, 0.975: 2.4469 },
  5: { 0.75: 0.7267, 0.9: 1.4759, 0.975: 2.5706 },
};
function zUnit(nu, p) {
  const t = T_QUANTILES[nu][p];
  return t * Math.sqrt((nu - 2) / nu);
}

// --- rate histories -------------------------------------------------------------------------

function history(pair, opts) {
  // Search seeds for a calm, realistic last-90-day path: range under maxRange, not ending on an extreme.
  for (let seed = opts.seed; seed < opts.seed + 5000; seed += 1) {
    const path = historyForSeed(pair, { ...opts, seed });
    const last90 = path.slice(-90).map((p) => p.rate);
    const lo = Math.min(...last90);
    const hi = Math.max(...last90);
    const end = last90[last90.length - 1];
    if ((hi - lo) / end < opts.maxRange && end < hi && end > lo + (hi - lo) * 0.35) return path;
  }
  throw new Error(`no calm path for ${pair}`);
}

function historyForSeed(pair, { seed, n, start, end, dailyVol, dp }) {
  const dates = tradingDaysBack(pair, SPOT_DATE, n);
  const rand = mulberry32(seed);
  const shocks = dates.map((_, i) => (i === 0 ? 0 : gaussian(rand) * dailyVol));
  const cum = [];
  shocks.reduce((acc, e, i) => ((cum[i] = acc + e), acc + e), 0);
  // Tilt the path so it runs from `start` to `end` exactly.
  const target = Math.log(end / start);
  const last = cum[cum.length - 1];
  return dates.map((date, i) => {
    const tilt = ((target - last) * i) / (dates.length - 1);
    return { date, rate: round(start * Math.exp(cum[i] + tilt), dp) };
  });
}

const EUR_SPOT = 1.1207;
const AMD_SPOT = 361.42;
const ratesEUR = history("EURUSD", {
  seed: 20261021,
  n: 140,
  start: 1.0968,
  end: EUR_SPOT,
  dailyVol: 0.0041,
  dp: 4,
  maxRange: 0.04,
});
const ratesAMD = history("USDAMD", {
  seed: 7311,
  n: 140,
  start: 366.1,
  end: AMD_SPOT,
  dailyVol: 0.0021,
  dp: 2,
  maxRange: 0.022,
});

writeFileSync(
  join(OUT, "rates.EURUSD.json"),
  JSON.stringify({ pair: "EURUSD", source: "frankfurter_ecb", rates: ratesEUR }, null, 2) + "\n",
);
writeFileSync(
  join(OUT, "rates.USDAMD.json"),
  JSON.stringify({ pair: "USDAMD", source: "frankfurter_cba", rates: ratesAMD }, null, 2) + "\n",
);

// EUR/AMD: the cross of the two series on CBA fixing days (last known EUR/USD on TARGET2 holidays).
const eurByDate = new Map(ratesEUR.map((r) => [r.date, r.rate]));
const ratesEURAMD = [];
{
  let lastEur = ratesEUR[0].rate;
  const eurDates = ratesEUR.map((r) => r.date);
  for (const r of ratesAMD) {
    if (eurByDate.has(r.date)) lastEur = eurByDate.get(r.date);
    else {
      const prev = eurDates.filter((d) => d < r.date).pop();
      if (prev) lastEur = eurByDate.get(prev);
    }
    ratesEURAMD.push({ date: r.date, rate: round(lastEur * r.rate, 2) });
  }
}
const EURAMD_SPOT = ratesEURAMD[ratesEURAMD.length - 1].rate;
writeFileSync(
  join(OUT, "rates.EURAMD.json"),
  JSON.stringify({ pair: "EURAMD", source: "frankfurter_cba", rates: ratesEURAMD }, null, 2) + "\n",
);

// --- sources ------------------------------------------------------------------------------------

const SOURCES = [
  // Labels as the API sends them (backend/src/fxf/api/health.py SOURCE_LABELS).
  ["frankfurter_ecb", "ECB reference rate (Frankfurter)", "2026-10-21T15:16:04Z"],
  ["frankfurter_cba", "CBA daily rate (Frankfurter)", "2026-10-21T15:16:09Z"],
  ["fred", "FRED", "2026-10-21T15:17:30Z"],
  ["ecb_data_portal", "ECB Data Portal", "2026-10-21T15:17:41Z"],
  ["cba_rates", "CBA policy rates", "2026-10-21T15:18:02Z"],
  ["fed_rss", "Fed press releases", "2026-10-21T15:00:12Z"],
  ["ecb_rss", "ECB press releases", "2026-10-21T15:00:15Z"],
  ["cba_news", "CBA decisions (cba.am, ARKA, Interfax)", null],
  ["atlanta_fed", "Atlanta Fed Market Probability Tracker", "2026-10-16T15:20:44Z"],
];
const sourceStatus = SOURCES.map(([source, label, lastSuccess]) => {
  if (source === "cba_news") {
    return {
      source,
      label,
      last_success: null,
      last_run: "2026-10-21T15:00:20Z",
      last_status: "failed",
      stale: true,
      error: "HTTP 403 from arka.am after 3 retries",
    };
  }
  if (source === "atlanta_fed") {
    return {
      source,
      label,
      last_success: lastSuccess,
      last_run: "2026-10-21T15:18:30Z",
      last_status: "failed",
      stale: true,
      error: "Schema check failed: unknown response shape (missing column 'Probability')",
    };
  }
  return {
    source,
    label,
    last_success: lastSuccess,
    last_run: lastSuccess,
    last_status: "success",
    stale: false,
    error: null,
  };
});
const bySource = Object.fromEntries(sourceStatus.map((s) => [s.source, s]));

writeFileSync(
  join(OUT, "health.json"),
  JSON.stringify(
    {
      status: "degraded",
      checked_at: CHECKED_AT,
      sources: sourceStatus,
      jobs: [
        {
          job: "forecast",
          last_success: "2026-10-21T15:38:51Z",
          last_run: "2026-10-21T15:38:51Z",
          last_status: "success",
          last_duration_s: 41.2,
          last_rows_written: 27,
          error: null,
        },
        {
          job: "backtest",
          last_success: "2026-10-18T06:12:09Z",
          last_run: "2026-10-18T06:12:09Z",
          last_status: "success",
          last_duration_s: 912.4,
          last_rows_written: 48,
          error: null,
        },
        {
          job: "score_statements",
          last_success: "2026-10-06T13:20:02Z",
          last_run: "2026-10-06T13:20:02Z",
          last_status: "success",
          last_duration_s: 6.8,
          last_rows_written: 1,
          error: null,
        },
      ],
    },
    null,
    2,
  ) + "\n",
);

writeFileSync(
  join(OUT, "pairs.json"),
  JSON.stringify(
    {
      pairs: [
        {
          id: "EURUSD",
          base: "EUR",
          quote: "USD",
          source: "frankfurter_ecb",
          source_label: "ECB reference rate",
          banks: ["FED", "ECB"],
        },
        {
          id: "USDAMD",
          base: "USD",
          quote: "AMD",
          source: "frankfurter_cba",
          source_label: "CBA daily average rate",
          banks: ["FED", "CBA"],
        },
        {
          id: "EURAMD",
          base: "EUR",
          quote: "AMD",
          source: "frankfurter_cba",
          source_label: "CBA daily average rate",
          banks: ["FED", "ECB", "CBA"],
        },
      ],
      horizons: [
        { days: 1, label: "1D" },
        { days: 5, label: "1W" },
        { days: 21, label: "1M" },
      ],
    },
    null,
    2,
  ) + "\n",
);

// --- forecasts ----------------------------------------------------------------------------------

const FED_MID = 3.375;
const ECB_DFR = 2.0;
const CBA_REFI = 6.5;
const MEETINGS = [
  { bank: "FED", date: "2026-10-28" },
  { bank: "ECB", date: "2026-10-29" },
  { bank: "CBA", date: "2026-12-08" },
  { bank: "FED", date: "2026-12-09" },
  { bank: "ECB", date: "2026-12-17" },
];
// Extra daily-variance units a meeting adds (realized meeting-day / normal-day ratio - 1).
const EVENT_RATIO = { FED: 0.85, ECB: 0.6, CBA: 1.4 };

function forward(spot, iBase, iQuote, days) {
  const tau = days / 252;
  return (spot * (1 + (iQuote / 100) * tau)) / (1 + (iBase / 100) * tau);
}

function buildForecast(pair, cfg) {
  const spot = cfg.spot;
  const dp = cfg.dp;
  const dailyVar = (cfg.volAnnual / Math.sqrt(252)) ** 2;
  const horizons = [1, 5, 21].map((days) => {
    const label = { 1: "1D", 5: "1W", 21: "1M" }[days];
    const target = addTradingDays(pair, SPOT_DATE, days);
    const meetings = MEETINGS.filter(
      (m) => cfg.banks.includes(m.bank) && m.date > SPOT_DATE && m.date <= target,
    );
    const garchVar = dailyVar * days * (days === 21 ? 1.03 : 1);
    const extra = meetings.reduce((acc, m) => acc + EVENT_RATIO[m.bank] * dailyVar, 0);
    const sigma = Math.sqrt(garchVar + extra);
    const model = cfg.served[days];
    const fwd = forward(spot, cfg.iBase, cfg.iQuote, days);
    const mu =
      model === "random_walk" ? 0 : model === "forward" ? Math.log(fwd / spot) : cfg.lgbmMu[days];
    const q = (p) => spot * Math.exp(mu + zUnit(cfg.nu, p) * sigma);
    const qd = (p) => spot * Math.exp(mu - zUnit(cfg.nu, p) * sigma);
    const r = (x) => round(x, dp + 1);
    return {
      days,
      label,
      target_date: target,
      model,
      model_version: { random_walk: "rw-1", forward: "cip-1", lightgbm: "lgbm-2026.10.18" }[model],
      center: r(spot * Math.exp(mu)),
      bands: {
        50: [r(qd(0.75)), r(q(0.75))],
        80: [r(qd(0.9)), r(q(0.9))],
        95: [r(qd(0.975)), r(q(0.975))],
      },
      meetings,
      drivers: {
        rate_diff_bps: cfg.rateDiff,
        rate_diff_change_21d_bps: cfg.rateDiffChange,
        policy_rates: cfg.policyRates,
        forward_rate: r(fwd),
        garch_vol_annual: cfg.volAnnual,
        horizon_sigma: round(sigma, 6),
        event_extra_variance: extra > 0 ? Number(extra.toPrecision(4)) : 0,
        last_surprise_bps: cfg.lastSurprise,
        hawkish_score: cfg.hawkish,
        days_to_next_meeting: cfg.daysToNext,
        served_reason: cfg.reasons[days],
      },
    };
  });
  return {
    pair,
    as_of: SPOT_DATE,
    spot,
    spot_date: SPOT_DATE,
    disclaimer: "Statistical estimate. Not financial advice.",
    horizons,
    stale_sources: cfg.staleSources.map((s) => bySource[s]),
  };
}

const RW_REASON =
  "No candidate beats the random walk over the last 250 trading days, so the random walk center is served with GARCH bands.";

const eurusd = buildForecast("EURUSD", {
  spot: EUR_SPOT,
  dp: 4,
  nu: 6,
  volAnnual: 0.0681,
  banks: ["FED", "ECB"],
  iBase: ECB_DFR,
  iQuote: FED_MID,
  // The realistic state: no candidate has met the promotion rule, so the random walk is served.
  served: { 1: "random_walk", 5: "random_walk", 21: "random_walk" },
  lgbmMu: {},
  rateDiff: round((FED_MID - ECB_DFR) * 100, 1),
  rateDiffChange: 0,
  policyRates: { FED: FED_MID, ECB: ECB_DFR },
  lastSurprise: { FED: -4.0, ECB: 0.0 },
  hawkish: { FED: -0.35, ECB: 0.1 },
  daysToNext: { FED: 7, ECB: 8 },
  reasons: {
    1: RW_REASON,
    5: RW_REASON,
    21: "lightgbm has a lower MAE (ratio 0.962) but its Diebold-Mariano p = 0.14 misses the 0.10 bar, so the random walk center is served with GARCH bands.",
  },
  // As the API computes it: stale sources among the pair's rate, policy-rate and news sources.
  staleSources: [],
});
const usdamd = buildForecast("USDAMD", {
  spot: AMD_SPOT,
  dp: 2,
  nu: 5,
  volAnnual: 0.0412,
  banks: ["FED", "CBA"],
  iBase: FED_MID,
  iQuote: CBA_REFI,
  served: { 1: "random_walk", 5: "random_walk", 21: "random_walk" },
  lgbmMu: {},
  rateDiff: round((CBA_REFI - FED_MID) * 100, 1),
  rateDiffChange: -25,
  policyRates: { FED: FED_MID, CBA: CBA_REFI },
  lastSurprise: { FED: -4.0, CBA: -25.0 },
  hawkish: { FED: -0.35, CBA: -0.45 },
  daysToNext: { FED: 7, CBA: 48 },
  reasons: {
    1: RW_REASON,
    5: RW_REASON,
    21: "forward has a lower MAE (ratio 0.971) but its Diebold-Mariano p = 0.16 misses the 0.10 bar, so the random walk center is served with GARCH bands.",
  },
  staleSources: ["cba_news"],
});
const euramd = buildForecast("EURAMD", {
  spot: EURAMD_SPOT,
  dp: 2,
  nu: 5,
  volAnnual: 0.0745,
  banks: ["FED", "ECB", "CBA"],
  iBase: ECB_DFR,
  iQuote: CBA_REFI,
  served: { 1: "random_walk", 5: "random_walk", 21: "random_walk" },
  lgbmMu: {},
  rateDiff: round((CBA_REFI - ECB_DFR) * 100, 1),
  rateDiffChange: -25,
  policyRates: { FED: FED_MID, ECB: ECB_DFR, CBA: CBA_REFI },
  lastSurprise: { FED: -4.0, ECB: 0.0, CBA: -25.0 },
  hawkish: { FED: -0.35, ECB: 0.1, CBA: -0.45 },
  daysToNext: { FED: 7, ECB: 8, CBA: 48 },
  reasons: { 1: RW_REASON, 5: RW_REASON, 21: RW_REASON },
  staleSources: ["cba_news"],
});

// All model outputs for the run (served and not served), for the Drivers candidates table.
function runRows(latest, pair, cfg) {
  const rows = [];
  for (const h of latest.horizons) {
    const candidates = { 1: ["random_walk", "lightgbm"], 5: ["random_walk", "forward", "lightgbm"], 21: ["random_walk", "forward", "lightgbm"] }[h.days];
    const sigma = h.drivers.horizon_sigma;
    for (const model of candidates) {
      const fwd = h.drivers.forward_rate;
      const mu =
        model === "random_walk"
          ? 0
          : model === "forward"
            ? Math.log(fwd / latest.spot)
            : (cfg.lgbmMu[h.days] ?? 0);
      const z = (p) => zUnit(cfg.nu, p);
      const at = (s) => round(latest.spot * Math.exp(mu + s * sigma), cfg.dp + 1);
      rows.push({
        model,
        model_version: { random_walk: "rw-1", forward: "cip-1", lightgbm: "lgbm-2026.10.18" }[model],
        horizon_days: h.days,
        target_date: h.target_date,
        spot: latest.spot,
        center: round(latest.spot * Math.exp(mu), cfg.dp + 1),
        q025: at(-z(0.975)),
        q10: at(-z(0.9)),
        q25: at(-z(0.75)),
        q75: at(z(0.75)),
        q90: at(z(0.9)),
        q975: at(z(0.975)),
        served: model === h.model,
        meetings: h.meetings,
        git_sha: "3f9c2e1",
      });
    }
  }
  const runDates = tradingDaysBack(pair, SPOT_DATE, 20).reverse();
  return { pair, run_date: SPOT_DATE, available_run_dates: runDates, rows };
}
writeFileSync(
  join(OUT, "forecast-run.EURUSD.json"),
  JSON.stringify(runRows(eurusd, "EURUSD", { nu: 6, dp: 4, lgbmMu: { 1: 0.0003, 5: -0.0008, 21: -0.0021 } }), null, 2) + "\n",
);
writeFileSync(
  join(OUT, "forecast-run.USDAMD.json"),
  JSON.stringify(runRows(usdamd, "USDAMD", { nu: 5, dp: 2, lgbmMu: { 1: -0.0001, 5: -0.0006, 21: -0.0019 } }), null, 2) + "\n",
);
writeFileSync(
  join(OUT, "forecast-run.EURAMD.json"),
  JSON.stringify(runRows(euramd, "EURAMD", { nu: 5, dp: 2, lgbmMu: { 1: 0.0002, 5: -0.0004, 21: -0.0024 } }), null, 2) + "\n",
);

// --- backtests ------------------------------------------------------------------------------------

function metric(h, model, window, m, servedMap) {
  const full = window === "full";
  return {
    horizon_days: h,
    model,
    window,
    n_obs: full ? m.nFull : 250,
    start_date: full ? m.fullStart : "2025-10-17",
    end_date: "2026-10-16",
    mae: m.mae,
    mae_ratio_rw: m.ratio,
    hit_rate: m.hit,
    cov50: m.cov[0],
    cov80: m.cov[1],
    cov95: m.cov[2],
    pinball: m.pinball,
    pinball_ref: m.pinballRef,
    dm_pvalue: m.dm,
    promoted: !full && model !== "random_walk" && m.ratio < 0.98 && (m.dm ?? 1) < 0.1,
    served: servedMap[h] === model,
  };
}
function backtest(pair, spec, servedMap, fullStart, nFullBase) {
  const metrics = [];
  for (const [h, models] of Object.entries(spec)) {
    for (const [model, windows] of Object.entries(models)) {
      for (const [window, m] of Object.entries(windows)) {
        metrics.push(
          metric(Number(h), model, window, { ...m, fullStart, nFull: nFullBase - Number(h) }, servedMap),
        );
      }
    }
  }
  return {
    pair,
    run_date: "2026-10-18",
    targets: {
      mae_ratio: 1.0,
      hit_rate: 0.5,
      coverage_tolerance: 0.05,
      dm_pvalue: 0.1,
      promotion_mae_ratio: 0.98,
    },
    metrics,
  };
}
const w = (m250, mFull) => ({ "250d": m250, full: mFull });
const btEUR = backtest(
  "EURUSD",
  {
    1: {
      random_walk: w(
        { mae: 0.00334, ratio: 1.0, hit: null, cov: [0.512, 0.796, 0.944], pinball: 0.00121, pinballRef: 0.00121, dm: null },
        { mae: 0.00351, ratio: 1.0, hit: null, cov: [0.503, 0.801, 0.948], pinball: 0.00127, pinballRef: 0.00127, dm: null },
      ),
      lightgbm: w(
        { mae: 0.00336, ratio: 1.006, hit: 0.508, cov: [0.508, 0.792, 0.94], pinball: 0.00122, pinballRef: 0.00121, dm: 0.71 },
        { mae: 0.00352, ratio: 1.003, hit: 0.511, cov: [0.501, 0.798, 0.946], pinball: 0.00127, pinballRef: 0.00127, dm: 0.64 },
      ),
    },
    5: {
      random_walk: w(
        { mae: 0.00742, ratio: 1.0, hit: null, cov: [0.496, 0.776, 0.932], pinball: 0.00268, pinballRef: 0.00268, dm: null },
        { mae: 0.00781, ratio: 1.0, hit: null, cov: [0.494, 0.789, 0.941], pinball: 0.00283, pinballRef: 0.00283, dm: null },
      ),
      forward: w(
        { mae: 0.0074, ratio: 0.997, hit: 0.512, cov: [0.5, 0.776, 0.932], pinball: 0.00267, pinballRef: 0.00268, dm: 0.62 },
        { mae: 0.00779, ratio: 0.998, hit: 0.506, cov: [0.495, 0.79, 0.941], pinball: 0.00283, pinballRef: 0.00283, dm: 0.58 },
      ),
      lightgbm: w(
        { mae: 0.00734, ratio: 0.989, hit: 0.536, cov: [0.504, 0.78, 0.936], pinball: 0.00265, pinballRef: 0.00268, dm: 0.21 },
        { mae: 0.00776, ratio: 0.994, hit: 0.521, cov: [0.497, 0.792, 0.942], pinball: 0.00282, pinballRef: 0.00283, dm: 0.33 },
      ),
    },
    21: {
      random_walk: w(
        { mae: 0.0158, ratio: 1.0, hit: null, cov: [0.472, 0.744, 0.912], pinball: 0.00571, pinballRef: 0.00571, dm: null },
        { mae: 0.0171, ratio: 1.0, hit: null, cov: [0.481, 0.771, 0.927], pinball: 0.00618, pinballRef: 0.00618, dm: null },
      ),
      forward: w(
        { mae: 0.0157, ratio: 0.994, hit: 0.524, cov: [0.476, 0.748, 0.916], pinball: 0.00568, pinballRef: 0.00571, dm: 0.48 },
        { mae: 0.0170, ratio: 0.996, hit: 0.517, cov: [0.483, 0.773, 0.928], pinball: 0.00616, pinballRef: 0.00618, dm: 0.41 },
      ),
      lightgbm: w(
        { mae: 0.0152, ratio: 0.962, hit: 0.564, cov: [0.492, 0.784, 0.928], pinball: 0.00552, pinballRef: 0.00571, dm: 0.14 },
        { mae: 0.0168, ratio: 0.982, hit: 0.538, cov: [0.489, 0.779, 0.931], pinball: 0.00609, pinballRef: 0.00618, dm: 0.18 },
      ),
    },
  },
  { 1: "random_walk", 5: "random_walk", 21: "random_walk" },
  "2015-01-02",
  2969,
);
const btAMD = backtest(
  "USDAMD",
  {
    1: {
      random_walk: w(
        { mae: 0.86, ratio: 1.0, hit: null, cov: [0.552, 0.832, 0.952], pinball: 0.312, pinballRef: 0.312, dm: null },
        { mae: 0.94, ratio: 1.0, hit: null, cov: [0.538, 0.818, 0.944], pinball: 0.341, pinballRef: 0.341, dm: null },
      ),
      lightgbm: w(
        { mae: 0.87, ratio: 1.012, hit: 0.496, cov: [0.548, 0.828, 0.948], pinball: 0.315, pinballRef: 0.312, dm: 0.44 },
        { mae: 0.94, ratio: 1.004, hit: 0.503, cov: [0.536, 0.817, 0.944], pinball: 0.342, pinballRef: 0.341, dm: 0.61 },
      ),
    },
    5: {
      random_walk: w(
        { mae: 1.94, ratio: 1.0, hit: null, cov: [0.524, 0.812, 0.928], pinball: 0.702, pinballRef: 0.702, dm: null },
        { mae: 2.21, ratio: 1.0, hit: null, cov: [0.51, 0.796, 0.921], pinball: 0.801, pinballRef: 0.801, dm: null },
      ),
      forward: w(
        { mae: 1.93, ratio: 0.993, hit: 0.548, cov: [0.528, 0.812, 0.928], pinball: 0.699, pinballRef: 0.702, dm: 0.31 },
        { mae: 2.2, ratio: 0.995, hit: 0.532, cov: [0.512, 0.797, 0.921], pinball: 0.799, pinballRef: 0.801, dm: 0.38 },
      ),
      lightgbm: w(
        { mae: 1.92, ratio: 0.991, hit: 0.54, cov: [0.532, 0.816, 0.932], pinball: 0.697, pinballRef: 0.702, dm: 0.27 },
        { mae: 2.2, ratio: 0.997, hit: 0.524, cov: [0.514, 0.799, 0.922], pinball: 0.8, pinballRef: 0.801, dm: 0.52 },
      ),
    },
    21: {
      random_walk: w(
        { mae: 4.11, ratio: 1.0, hit: null, cov: [0.468, 0.768, 0.884], pinball: 1.49, pinballRef: 1.49, dm: null },
        { mae: 4.86, ratio: 1.0, hit: null, cov: [0.452, 0.741, 0.872], pinball: 1.77, pinballRef: 1.77, dm: null },
      ),
      forward: w(
        { mae: 3.99, ratio: 0.971, hit: 0.584, cov: [0.476, 0.772, 0.888], pinball: 1.45, pinballRef: 1.49, dm: 0.16 },
        { mae: 4.79, ratio: 0.986, hit: 0.553, cov: [0.457, 0.744, 0.874], pinball: 1.75, pinballRef: 1.77, dm: 0.21 },
      ),
      lightgbm: w(
        { mae: 4.05, ratio: 0.985, hit: 0.556, cov: [0.472, 0.764, 0.884], pinball: 1.47, pinballRef: 1.49, dm: 0.19 },
        { mae: 4.83, ratio: 0.994, hit: 0.531, cov: [0.455, 0.742, 0.873], pinball: 1.76, pinballRef: 1.77, dm: 0.36 },
      ),
    },
  },
  { 1: "random_walk", 5: "random_walk", 21: "random_walk" },
  "2015-01-05",
  2912,
);
// EUR/AMD: the USD/AMD record scaled to the EUR/AMD level, with slightly wider misses.
function scaled(spec, k) {
  const out = {};
  for (const [h, models] of Object.entries(spec)) {
    out[h] = {};
    for (const [model, windows] of Object.entries(models)) {
      out[h][model] = {};
      for (const [win, m] of Object.entries(windows)) {
        out[h][model][win] = {
          ...m,
          mae: round(m.mae * k, 3),
          pinball: round(m.pinball * k, 3),
          pinballRef: m.pinballRef === null ? null : round(m.pinballRef * k, 3),
          cov: m.cov.map((c) => round(c - 0.006, 3)),
        };
      }
    }
  }
  return out;
}
const AMD_SPEC = Object.fromEntries(
  Object.entries(Object.groupBy(btAMD.metrics, (m) => m.horizon_days)).map(([h, rows]) => [
    h,
    Object.fromEntries(
      Object.entries(Object.groupBy(rows, (m) => m.model)).map(([model, mrows]) => [
        model,
        Object.fromEntries(
          mrows.map((m) => [
            m.window,
            {
              mae: m.mae,
              ratio: m.mae_ratio_rw,
              hit: m.hit_rate,
              cov: [m.cov50, m.cov80, m.cov95],
              pinball: m.pinball,
              pinballRef: m.pinball_ref,
              dm: m.dm_pvalue,
            },
          ]),
        ),
      ]),
    ),
  ]),
);
const btEURAMD = backtest(
  "EURAMD",
  scaled(AMD_SPEC, EURAMD_SPOT / AMD_SPOT * 1.12),
  { 1: "random_walk", 5: "random_walk", 21: "random_walk" },
  "2015-01-05",
  2912,
);
writeFileSync(join(OUT, "backtests.EURUSD.json"), JSON.stringify(btEUR, null, 2) + "\n");
writeFileSync(join(OUT, "backtests.USDAMD.json"), JSON.stringify(btAMD, null, 2) + "\n");
writeFileSync(join(OUT, "backtests.EURAMD.json"), JSON.stringify(btEURAMD, null, 2) + "\n");

// --- FR-17 conversion signal ----------------------------------------------------------------------
// Mirrors backend/src/fxf/api/signal.py. With the random walk served everywhere, the honest
// answer is "no clear edge": the median sits on the spot, so P(better rate) is exactly 0.50.
// The useful facts are then the risk of waiting and the interest difference (carry).
const SIGNAL_LABEL = { 1: "1D", 5: "1W", 21: "1M" };
const PAIR_RATES = {
  EURUSD: { sell: "EUR", receive: "USD", base: ECB_DFR, quote: FED_MID },
  USDAMD: { sell: "USD", receive: "AMD", base: FED_MID, quote: CBA_REFI },
  EURAMD: { sell: "EUR", receive: "AMD", base: ECB_DFR, quote: CBA_REFI },
};
const fmtRange = (lo, hi, dp) => `${lo.toFixed(dp)} to ${hi.toFixed(dp)}`;

// Experimental AI view (prompt ai-p2): an independent read, unproven (nothing scored yet).
// It leans more often than the random walk; the lean uses the same 5-point threshold.
const AI_VIEWS = {
  EURUSD: {
    1: [0.49, -0.01, "low", "One trading day is mostly noise, and no Fed or ECB decision lands before the target date. Close to even odds."],
    5: [0.45, -0.09, "low", "The Fed decides on 28 Oct, the 1W target date. A cut is largely priced in, so the bigger risk is a less dovish message that supports the dollar, which argues against waiting."],
    21: [0.55, 0.1, "low", "The ECB holds at 2% while the Fed eases, which narrows the rate gap in the euro's favour over a month. The euro already sits near the top of its 90-day range, which limits the upside."],
  },
  USDAMD: {
    1: [0.49, -0.01, "low", "One day is mostly noise for a managed rate; the CBA fixing has moved less than 0.3% on most recent days."],
    5: [0.44, -0.1, "low", "The Fed meets on 28 Oct with a further cut expected, which tends to weigh on the dollar against the dram in the days around the decision."],
    21: [0.57, 0.12, "medium", "The CBA's easing bias and the narrower CBA-Fed rate gap point to a slightly weaker dram over a month, though the CBA has leaned against sharp moves before."],
  },
  EURAMD: {
    1: [0.44, -0.08, "low", "The dram firmed over the last week and nothing is scheduled before tomorrow's fixing, so the AI expects a little more of the same, which argues for converting now."],
    5: [0.52, 0.03, "low", "The Fed and ECB meetings on 28 and 29 Oct add risk both ways. The AI sees no clear lean over one week."],
    21: [0.58, 0.21, "medium", "Over a month the CBA's easing bias and the wide CBA-ECB rate gap point to mild dram weakness, so a slightly better EUR/AMD rate is more likely than not. The dram has been resilient, so the edge is small."],
  },
};
// Inverse standard normal (Acklam's rational approximation), to keep each AI view's expected
// change consistent with its probability and the horizon's sigma.
function probit(p) {
  const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
  const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
  const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
  const pl = 0.02425;
  if (p < pl) {
    const q = Math.sqrt(-2 * Math.log(p));
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  if (p > 1 - pl) return -probit(1 - p);
  const q = p - 0.5;
  const r = q * q;
  return ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q) / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
}
const leanOf = (p) => (Math.abs(p - 0.5) < 0.05 - 1e-9 ? "no_edge" : p > 0.5 ? "wait" : "sell_now");

function attachSignals(latest, bt) {
  const meta = PAIR_RATES[latest.pair];
  const dp = latest.pair === "EURUSD" ? 4 : 2;
  for (const h of latest.horizons) {
    const ev = bt.metrics.find((m) => m.horizon_days === h.days && m.model === h.model && m.window === "250d");
    const label = SIGNAL_LABEL[h.days];
    const [lo, hi] = h.bands["80"];
    const carryYear = round(meta.quote - meta.base, 4);
    const carryH = round((carryYear * h.days) / 252, 4);
    const carryAmt = round((latest.spot * carryH) / 100, dp + 2);
    const pays =
      carryYear >= 0
        ? `Holding ${meta.receive} pays about ${carryYear.toFixed(2)}%/yr more than ${meta.sell}`
        : `Holding ${meta.sell} pays about ${(-carryYear).toFixed(2)}%/yr more than ${meta.receive}`;
    h.signal = {
      action: "no_edge",
      verdict_source: "statistical",
      sell: meta.sell,
      receive: meta.receive,
      prob_better_if_wait: 0.5,
      expected_change_pct: round((h.center / latest.spot - 1) * 100, 4),
      downside_p10_rate: lo,
      upside_p90_rate: hi,
      risk_half_width_pct: round(((hi - lo) / 2 / latest.spot) * 100, 4),
      carry_pct_per_year: carryYear,
      carry_over_horizon_pct: carryH,
      carry_amount: carryAmt,
      confidence: "none",
      model: h.model,
      model_beats_random_walk: false,
      hit_rate: ev?.hit_rate ?? null,
      dm_pvalue: ev?.dm_pvalue ?? null,
      mae_ratio_rw: ev?.mae_ratio_rw ?? null,
      n_obs: ev?.n_obs ?? null,
      summary:
        `Waiting ${label} doesn't improve your expected rate; it adds risk: 80% of the time you'd get ` +
        `${fmtRange(lo, hi, dp)} ${meta.receive} per ${meta.sell}. ${pays} at policy rates ` +
        `(about ${Math.abs(carryAmt).toFixed(dp)} ${meta.receive} per ${meta.sell} over ${label}).`,
    };
    const [p, , confidence, reasoning] = AI_VIEWS[latest.pair][h.days];
    const chg = round(probit(p) * h.drivers.horizon_sigma * 100, 3);
    // The AI's expected rate, and the statistical 80% range re-centred on it.
    const aiCenter = round(latest.spot * (1 + chg / 100), dp + 1);
    const shift = aiCenter / h.center;
    h.ai_view = {
      provider: "gemini",
      model: "gemini-3.5-flash-lite",
      prompt_version: "ai-p2",
      generated_at: "2026-10-21T15:39:20Z",
      prob_better_if_wait: p,
      expected_change_pct: chg,
      center: aiCenter,
      band80: [round(lo * shift, dp + 1), round(hi * shift, dp + 1)],
      lean: leanOf(p),
      confidence,
      reasoning,
      track_record: {
        n_scored: 0,
        required: 250,
        hit_rate: null,
        mae_ratio_rw: null,
        dm_pvalue: null,
        brier: null,
        promoted: false,
      },
    };
  }
  return latest;
}
writeFileSync(join(OUT, "forecast-latest.EURUSD.json"), JSON.stringify(attachSignals(eurusd, btEUR), null, 2) + "\n");
writeFileSync(join(OUT, "forecast-latest.USDAMD.json"), JSON.stringify(attachSignals(usdamd, btAMD), null, 2) + "\n");
writeFileSync(join(OUT, "forecast-latest.EURAMD.json"), JSON.stringify(attachSignals(euramd, btEURAMD), null, 2) + "\n");

// --- events ------------------------------------------------------------------------------------------

const decisions = [
  {
    id: 418,
    bank: "CBA",
    date: "2026-10-06",
    rate_type: "refinancing",
    rate_before: 6.75,
    rate_after: 6.5,
    expected: 6.75,
    expected_source: "previous_rate",
    surprise_bps: -25.0,
    rates: {
      refinancing: { before: 6.75, after: 6.5 },
      lombard: { before: 8.25, after: 8.0 },
      deposit: { before: 5.25, after: 5.0 },
    },
    statement_url: "https://www.cba.am/en/press-center/press-releases",
    statement_text:
      "The Board of the Central Bank of Armenia decided to reduce the refinancing rate by 0.25 percentage points to 6.5 percent. Twelve-month inflation stood at 3.1 percent in September, below the 4 percent target. External demand has softened and credit growth is slowing. The Board considers that the current stance leaves room for further gradual easing if inflation stays below target. The Lombard repo rate is set at 8.0 percent and the deposit facility rate at 5.0 percent.",
    statement_diff: {
      added: [
        "The Board of the Central Bank of Armenia decided to reduce the refinancing rate by 0.25 percentage points to 6.5 percent.",
        "The Board considers that the current stance leaves room for further gradual easing if inflation stays below target.",
        "External demand has softened and credit growth is slowing.",
      ],
      removed: [
        "The Board of the Central Bank of Armenia decided to keep the refinancing rate unchanged at 6.75 percent.",
        "The Board will keep monetary conditions tight until inflation expectations are firmly anchored.",
      ],
      previous_event_id: 391,
    },
    hawkish_score: -0.45,
    hawkish_reason: "Cuts 25 bps and opens the door to further easing as inflation stays below target.",
    scorer_version: "claude-haiku-5-5@p1",
  },
  {
    id: 407,
    bank: "FED",
    date: "2026-09-16",
    rate_type: "target_mid",
    rate_before: 3.625,
    rate_after: 3.375,
    expected: 3.415,
    expected_source: "atlanta_fed",
    surprise_bps: -4.0,
    rates: {
      target_upper: { before: 3.75, after: 3.5 },
      target_lower: { before: 3.5, after: 3.25 },
    },
    statement_url: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm",
    statement_text:
      "Recent indicators suggest that growth of economic activity has moderated. Job gains have slowed, and the unemployment rate has edged up. Inflation has eased but remains somewhat elevated. In support of its goals, the Committee decided to lower the target range for the federal funds rate by 1/4 percentage point to 3-1/4 to 3-1/2 percent. In considering additional adjustments, the Committee will carefully assess incoming data, the evolving outlook, and the balance of risks.",
    statement_diff: {
      added: [
        "Job gains have slowed, and the unemployment rate has edged up.",
        "In support of its goals, the Committee decided to lower the target range for the federal funds rate by 1/4 percentage point to 3-1/4 to 3-1/2 percent.",
      ],
      removed: [
        "Job gains have remained solid, and the unemployment rate has stayed low.",
        "In support of its goals, the Committee decided to maintain the target range for the federal funds rate at 3-1/2 to 3-3/4 percent.",
      ],
      previous_event_id: 388,
    },
    hawkish_score: -0.35,
    hawkish_reason: "Cuts 25 bps and points to a softer labor market; keeps a data-dependent stance.",
    scorer_version: "claude-haiku-5-5@p1",
  },
  {
    id: 403,
    bank: "ECB",
    date: "2026-09-10",
    rate_type: "deposit",
    rate_before: 2.0,
    rate_after: 2.0,
    expected: 2.0,
    expected_source: "previous_rate",
    surprise_bps: 0.0,
    rates: {
      deposit: { before: 2.0, after: 2.0 },
      main_refinancing: { before: 2.15, after: 2.15 },
      marginal_lending: { before: 2.4, after: 2.4 },
    },
    statement_url: "https://www.ecb.europa.eu/press/pr/date/2026/html/index.en.html",
    statement_text:
      "The Governing Council today decided to keep the three key ECB interest rates unchanged. Inflation is currently at around the 2% medium-term target. Wage growth remains robust, which poses some upside risk to services inflation. The Governing Council is determined to ensure that inflation stabilises sustainably at its 2% target.",
    statement_diff: {
      added: ["Wage growth remains robust, which poses some upside risk to services inflation."],
      removed: ["The incoming information is broadly in line with the previous assessment."],
      previous_event_id: 384,
    },
    hawkish_score: 0.1,
    hawkish_reason: "Holds rates; flags upside risk from wages but no bias to tighten.",
    scorer_version: "claude-haiku-5-5@p1",
  },
  {
    id: 391,
    bank: "CBA",
    date: "2026-07-28",
    rate_type: "refinancing",
    rate_before: 6.75,
    rate_after: 6.75,
    expected: 6.75,
    expected_source: "previous_rate",
    surprise_bps: 0.0,
    rates: {
      refinancing: { before: 6.75, after: 6.75 },
      lombard: { before: 8.25, after: 8.25 },
      deposit: { before: 5.25, after: 5.25 },
    },
    statement_url: "https://www.cba.am/en/press-center/press-releases",
    statement_text: null,
    statement_diff: null,
    hawkish_score: null,
    hawkish_reason: null,
    scorer_version: null,
  },
  {
    id: 388,
    bank: "FED",
    date: "2026-07-29",
    rate_type: "target_mid",
    rate_before: 3.625,
    rate_after: 3.625,
    expected: 3.61,
    expected_source: "atlanta_fed",
    surprise_bps: 1.5,
    rates: {
      target_upper: { before: 3.75, after: 3.75 },
      target_lower: { before: 3.5, after: 3.5 },
    },
    statement_url: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm",
    statement_text:
      "Recent indicators suggest that economic activity has continued to expand at a solid pace. Job gains have remained solid, and the unemployment rate has stayed low. Inflation remains somewhat elevated. In support of its goals, the Committee decided to maintain the target range for the federal funds rate at 3-1/2 to 3-3/4 percent.",
    statement_diff: {
      added: ["Recent indicators suggest that economic activity has continued to expand at a solid pace."],
      removed: ["Uncertainty about the economic outlook has increased."],
      previous_event_id: 371,
    },
    hawkish_score: 0.2,
    hawkish_reason: "Holds; describes solid growth and removes the line on rising uncertainty.",
    scorer_version: "claude-haiku-5-5@p1",
  },
  {
    id: 384,
    bank: "ECB",
    date: "2026-07-23",
    rate_type: "deposit",
    rate_before: 2.0,
    rate_after: 2.0,
    expected: 2.0,
    expected_source: "previous_rate",
    surprise_bps: 0.0,
    rates: {
      deposit: { before: 2.0, after: 2.0 },
      main_refinancing: { before: 2.15, after: 2.15 },
      marginal_lending: { before: 2.4, after: 2.4 },
    },
    statement_url: "https://www.ecb.europa.eu/press/pr/date/2026/html/index.en.html",
    statement_text:
      "The Governing Council today decided to keep the three key ECB interest rates unchanged. The incoming information is broadly in line with the previous assessment. Inflation is currently at around the 2% medium-term target.",
    statement_diff: {
      added: ["Inflation is currently at around the 2% medium-term target."],
      removed: ["Inflation is expected to return to target in the course of next year."],
      previous_event_id: 369,
    },
    hawkish_score: 0.05,
    hawkish_reason: "Holds; inflation at target, language unchanged in substance.",
    scorer_version: "lexicon@v1",
  },
];
const upcoming = [
  { bank: "FED", date: "2026-10-28", scheduled: true },
  { bank: "ECB", date: "2026-10-29", scheduled: true },
  { bank: "CBA", date: "2026-12-08", scheduled: true },
  { bank: "FED", date: "2026-12-09", scheduled: true },
  { bank: "ECB", date: "2026-12-17", scheduled: true },
  { bank: "CBA", date: "2027-01-26", scheduled: true },
  { bank: "FED", date: "2027-01-27", scheduled: true },
  { bank: "ECB", date: "2027-02-04", scheduled: true },
].map((m) => ({
  ...m,
  days_until: Math.round((Date.parse(`${m.date}T00:00:00Z`) - Date.parse(`${SPOT_DATE}T00:00:00Z`)) / 86400000),
}));
writeFileSync(join(OUT, "events.json"), JSON.stringify({ decisions, upcoming }, null, 2) + "\n");

console.log("mocks written to", OUT);
console.log(
  "EURUSD",
  eurusd.horizons.map((h) => `${h.label} ${h.target_date} ${h.model} ${h.center} 80:${h.bands["80"].join("-")} m:${h.meetings.map((m) => m.bank).join(",")}`),
);
console.log(
  "EURAMD",
  euramd.horizons.map((h) => `${h.label} ${h.target_date} ${h.model} ${h.center} 80:${h.bands["80"].join("-")} m:${h.meetings.map((m) => m.bank).join(",")}`),
);
console.log(
  "USDAMD",
  usdamd.horizons.map((h) => `${h.label} ${h.target_date} ${h.model} ${h.center} 80:${h.bands["80"].join("-")} m:${h.meetings.map((m) => m.bank).join(",")}`),
);

// --- meeting reaction study (GET /api/meetings/{pair}) -------------------------------------------
// Mirrors backend/src/fxf/events/study.py. Targets match the live study: EUR/USD around the FOMC
// moved 0.51% on average (about 2.7x a normal day) and followed the surprise or tone 5 of 8 times;
// EUR/AMD around the FOMC is about 2.95x with no expected direction (USD is in neither leg).
{
  const MEETINGS_12M = {
    FED: ["2025-10-29", "2025-12-10", "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16"],
    ECB: ["2025-10-30", "2025-12-18", "2026-02-05", "2026-03-19", "2026-04-30", "2026-06-11", "2026-07-23", "2026-09-10"],
    CBA: ["2025-10-28", "2025-12-09", "2026-02-03", "2026-03-17", "2026-04-28", "2026-06-09", "2026-07-28", "2026-10-06"],
  };
  const CURRENCY_BANK = { EUR: "ECB", USD: "FED", AMD: "CBA" };
  // pair -> bank -> [mean |reaction| %, normal |move| %, followed count, neutral (unsigned) count]
  const TARGETS = {
    EURUSD: { FED: [0.51, 0.189, 5, 0], ECB: [0.32, 0.2, 4, 1] },
    USDAMD: { FED: [0.41, 0.178, 5, 0], CBA: [0.33, 0.183, 6, 0] },
    EURAMD: { FED: [0.6, 0.203, 0, 0], ECB: [0.38, 0.2, 4, 2], CBA: [0.29, 0.193, 5, 1] },
  };
  const PAIR_LEGS = { EURUSD: ["EUR", "USD"], USDAMD: ["USD", "AMD"], EURAMD: ["EUR", "AMD"] };
  const known = Object.fromEntries(decisions.map((d) => [`${d.bank}:${d.date}`, d]));
  const pearson = (xs, ys) => {
    const n = xs.length;
    if (n < 5) return null;
    const mx = xs.reduce((a, b) => a + b, 0) / n;
    const my = ys.reduce((a, b) => a + b, 0) / n;
    let sxy = 0, sxx = 0, syy = 0;
    for (let i = 0; i < n; i++) {
      sxy += (xs[i] - mx) * (ys[i] - my);
      sxx += (xs[i] - mx) ** 2;
      syy += (ys[i] - my) ** 2;
    }
    return sxx && syy ? round(sxy / Math.sqrt(sxx * syy), 3) : null;
  };
  for (const [pair, banks] of Object.entries(TARGETS)) {
    const [base, quote] = PAIR_LEGS[pair];
    const rand = mulberry32(pair.length * 977 + pair.charCodeAt(0) * 31);
    const meetings = [];
    const summaries = [];
    for (const [bank, [meanAbs, normal, followedN, neutralN]] of Object.entries(banks)) {
      const expected = CURRENCY_BANK[base] === bank ? 1 : CURRENCY_BANK[quote] === bank ? -1 : 0;
      const dates = MEETINGS_12M[bank];
      const raw = dates.map(() => 0.4 + rand() * 1.2);
      const scale = (meanAbs * dates.length) / raw.reduce((a, b) => a + b, 0);
      const rows = dates.map((date, i) => {
        const ev = known[`${bank}:${date}`];
        const surprise = ev ? ev.surprise_bps : round((rand() - 0.5) * 8, 1);
        const tone = ev && ev.hawkish_score !== null ? ev.hawkish_score : round((rand() - 0.5) * 1.2, 2);
        const neutral = expected !== 0 && i < neutralN;
        const signal = neutral ? 0 : Math.abs(surprise) >= 1 ? Math.sign(surprise) : Math.abs(tone) >= 0.15 ? Math.sign(tone) : 0;
        const signed = expected !== 0 && signal !== 0;
        const signedIndex = signed ? dates.slice(0, i).filter((_, j) => j >= neutralN).length : -1;
        const follows = signed ? signedIndex < followedN : null;
        const dir = signed ? (follows ? expected * signal : -expected * signal) : rand() < 0.5 ? -1 : 1;
        const reaction = round(dir * raw[i] * scale, 3);
        return {
          bank,
          date,
          surprise_bps: surprise,
          hawkish_score: tone,
          rate_change_bps: ev && ev.rate_before !== null ? round((ev.rate_after - ev.rate_before) * 100, 1) : 0,
          run_up_pct: round((rand() - 0.5) * 0.9, 3),
          reaction_pct: reaction,
          follow_pct: date === "2026-10-06" ? null : round((rand() - 0.5) * 1.1, 3),
          expected_sign: expected,
          signal: expected === 0 ? signal : signal,
          followed: signed ? follows : null,
        };
      });
      meetings.push(...rows);
      const signedRows = rows.filter((r) => r.followed !== null);
      const mean = (xs) => (xs.length ? round(xs.reduce((a, b) => a + b, 0) / xs.length, 3) : null);
      const meanAbsReal = mean(rows.map((r) => Math.abs(r.reaction_pct)));
      summaries.push({
        bank,
        n: rows.length,
        mean_abs_reaction_pct: meanAbsReal,
        normal_abs_move_pct: normal,
        reaction_ratio: round(meanAbsReal / normal, 2),
        mean_run_up_pct: mean(rows.map((r) => r.run_up_pct)),
        mean_follow_pct: mean(rows.filter((r) => r.follow_pct !== null).map((r) => r.follow_pct)),
        n_signed: signedRows.length,
        consistency: signedRows.length ? round(signedRows.filter((r) => r.followed).length / signedRows.length, 3) : null,
        correlation: signedRows.length
          ? pearson(signedRows.map((r) => r.expected_sign * r.signal), signedRows.map((r) => r.reaction_pct))
          : null,
      });
    }
    meetings.sort((a, b) => (a.date < b.date ? 1 : -1));
    writeFileSync(
      join(OUT, `meetings.${pair}.json`),
      JSON.stringify({ pair, as_of: SPOT_DATE, lookback_days: 365, window_days: 5, banks: summaries, meetings }, null, 2) + "\n",
    );
    console.log("meetings", pair, summaries.map((b) => `${b.bank} n${b.n} |r|${b.mean_abs_reaction_pct} x${b.reaction_ratio} ${b.n_signed ? Math.round(b.consistency * b.n_signed) + "/" + b.n_signed : "unsigned"}`).join(" | "));
  }
}

// --- backtest: around meetings, AI live record, AI weekly analysis --------------------------------
{
  const PAIR_BANKS = { EURUSD: ["FED", "ECB"], USDAMD: ["FED", "CBA"], EURAMD: ["FED", "ECB", "CBA"] };
  // 80% coverage on meeting horizons vs none, per pair and bank (meeting windows run a little wide or narrow).
  const COV80 = {
    EURUSD: { FED: 0.752, ECB: 0.774, none: 0.812 },
    USDAMD: { FED: 0.781, CBA: 0.736, none: 0.826 },
    EURAMD: { FED: 0.768, ECB: 0.79, CBA: 0.722, none: 0.818 },
  };
  const ANALYSIS = {
    EURUSD: {
      headline: "Fed weeks are where the bands are tested; ECB weeks behave much like normal weeks.",
      points: [
        "EUR/USD moved about 2.7 times a normal day around Fed decisions and followed the surprise or tone in 5 of 8 meetings.",
        "With a Fed meeting inside the week, the 80% band held 75% of the time, at the low edge of the 75 to 85% target.",
        "Around ECB meetings the reaction was smaller, about 1.6 times a normal day, and coverage stayed within target.",
      ],
      watch_next: "The Fed on 28 Oct falls on the 1W target date; a less dovish message than priced would test the lower band.",
    },
    USDAMD: {
      headline: "CBA decisions move USD/AMD more than its bands expect; Fed weeks are handled well.",
      points: [
        "USD/AMD moved about 1.8 times a normal day around CBA decisions, and the 80% band held only 74% of the time in those weeks.",
        "Around Fed meetings the reaction was larger, about 2.3 times a normal day, but the event widening kept coverage near 78%.",
        "The dram's managed float makes most days quiet, so a few meeting days account for much of the error.",
      ],
      watch_next: "The CBA meets on 8 Dec; its easing bias after the October cut is the main risk to the 1M band.",
    },
    EURAMD: {
      headline: "Fed meetings move EUR/AMD the most, even though the dollar is in neither leg.",
      points: [
        "EUR/AMD moved about 3 times a normal day around Fed decisions, with no consistent direction.",
        "With a CBA meeting inside the horizon, the 80% band held 72% of the time, below the 75 to 85% target.",
        "ECB weeks were close to normal: about 1.9 times a normal day, and coverage stayed within target.",
      ],
      watch_next: "Fed and ECB decide on 28 and 29 Oct, inside the 1W and 1M horizons; watch whether the widened bands hold.",
    },
  };
  for (const [pair, bt] of [["EURUSD", btEUR], ["USDAMD", btAMD], ["EURAMD", btEURAMD]]) {
    const banks = PAIR_BANKS[pair];
    const rand = mulberry32(pair.charCodeAt(3) * 101);
    const event_metrics = [];
    for (const m of bt.metrics.filter((r) => r.window === "250d")) {
      const h = m.horizon_days;
      // Origins whose horizon contains a meeting of the bank: about 8 meetings x h origins each.
      const nBank = Object.fromEntries(banks.map((b) => [b, Math.min(250, Math.round(8 * h * (0.95 + rand() * 0.1)))]));
      const nAny = Math.min(240, Math.round(banks.length * 8 * h * 0.85));
      const nNone = Math.max(10, 250 - nAny);
      for (const bank of [...banks, "none"]) {
        const base = COV80[pair][bank];
        const shift = h === 1 ? 0.01 : h === 21 ? -0.006 : 0;
        const cov80 = round(Math.min(0.97, base + shift + (rand() - 0.5) * 0.01), 3);
        event_metrics.push({
          horizon_days: h,
          model: m.model,
          bank,
          n_obs: bank === "none" ? nNone : nBank[bank],
          mae_ratio_rw: m.model === "random_walk" ? 1.0 : round(m.mae_ratio_rw + (bank === "none" ? -0.01 : 0.02) + (rand() - 0.5) * 0.01, 3),
          hit_rate: m.hit_rate === null ? null : round(m.hit_rate + (rand() - 0.5) * 0.04, 3),
          cov50: round(cov80 - 0.3 + (rand() - 0.5) * 0.02, 3),
          cov80,
          cov95: round(Math.min(0.99, cov80 + 0.14 + (rand() - 0.5) * 0.01), 3),
        });
      }
    }
    bt.event_metrics = event_metrics;
    bt.ai_track = [1, 5, 21].map((h) => ({
      horizon_days: h,
      model_version: "gemini-3.5-flash-lite@ai-p2",
      track_record: { n_scored: 0, required: 250, hit_rate: null, mae_ratio_rw: null, dm_pvalue: null, brier: null, promoted: false },
    }));
    bt.ai_analysis = {
      run_date: "2026-10-18",
      provider: "gemini",
      model: "gemini-3.5-flash-lite",
      prompt_version: "analysis-p1",
      generated_at: "2026-10-18T06:21:37Z",
      ...ANALYSIS[pair],
    };
    writeFileSync(join(OUT, `backtests.${pair}.json`), JSON.stringify(bt, null, 2) + "\n");
  }
}

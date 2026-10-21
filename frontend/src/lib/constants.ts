/** Mirrors backend/src/fxf/constants.py. Use these names; do not hardcode strings in views. */

import type { BandKey, BankId, PairId } from "../api/types";

export const DISCLAIMER = "Statistical estimate. Not financial advice.";

export interface PairMeta {
  id: PairId;
  base: string;
  quote: string;
  label: string; // "EUR/USD"
  rateSource: string;
  sourceLabel: string;
  banks: BankId[];
  /** Decimals for rates: ECB publishes 4, CBA publishes 2. */
  decimals: number;
  /** Sign convention of the policy-rate differential (spec: Features for the model). */
  diffLabel: string;
}

export const PAIRS: Record<PairId, PairMeta> = {
  EURUSD: {
    id: "EURUSD",
    base: "EUR",
    quote: "USD",
    label: "EUR/USD",
    rateSource: "frankfurter_ecb",
    sourceLabel: "ECB reference rate",
    banks: ["FED", "ECB"],
    decimals: 4,
    diffLabel: "Fed minus ECB",
  },
  USDAMD: {
    id: "USDAMD",
    base: "USD",
    quote: "AMD",
    label: "USD/AMD",
    rateSource: "frankfurter_cba",
    sourceLabel: "CBA daily average rate",
    banks: ["FED", "CBA"],
    decimals: 2,
    diffLabel: "CBA minus Fed",
  },
  EURAMD: {
    id: "EURAMD",
    base: "EUR",
    quote: "AMD",
    label: "EUR/AMD",
    rateSource: "frankfurter_cba",
    sourceLabel: "CBA daily average rate",
    banks: ["FED", "ECB", "CBA"],
    decimals: 2,
    diffLabel: "CBA minus ECB",
  },
};
export const PAIR_IDS: PairId[] = ["EURUSD", "USDAMD", "EURAMD"];

export function isPairId(v: string | undefined): v is PairId {
  return v !== undefined && (PAIR_IDS as string[]).includes(v);
}

export const HORIZONS = [
  { days: 1, label: "1D", long: "1 trading day" },
  { days: 5, label: "1W", long: "5 trading days" },
  { days: 21, label: "1M", long: "21 trading days" },
] as const;
export const HORIZON_LABELS: Record<number, string> = { 1: "1D", 5: "1W", 21: "1M" };

export const BANKS: BankId[] = ["FED", "ECB", "CBA"];
export const BANK_LABELS: Record<string, string> = {
  FED: "Fed",
  ECB: "ECB",
  CBA: "CBA",
};
export const BANK_LONG: Record<string, string> = {
  FED: "Federal Reserve (FOMC)",
  ECB: "European Central Bank",
  CBA: "Central Bank of Armenia",
};
export const RATE_TYPE_LABELS: Record<string, string> = {
  target_mid: "Target midpoint",
  target_upper: "Target upper",
  target_lower: "Target lower",
  deposit: "Deposit facility",
  main_refinancing: "Main refinancing",
  marginal_lending: "Marginal lending",
  refinancing: "Refinancing",
  lombard: "Lombard repo",
  lombard_repo: "Lombard repo",
};

export const MODEL_LABELS: Record<string, string> = {
  random_walk: "Random walk",
  forward: "Forward rate",
  lightgbm: "LightGBM",
};
export const MODEL_ORDER = ["random_walk", "forward", "lightgbm"];

/** Band keys from widest to narrowest: the drawing order of the fan. */
export const BAND_KEYS: BandKey[] = ["95", "80", "50"];
export const BAND_NOMINAL: Record<BandKey, number> = { "50": 0.5, "80": 0.8, "95": 0.95 };

// --- Sources (job_runs.job and /api/health keys) ----------------------------------------

/** Fallback labels; the API sends its own (backend/src/fxf/api/health.py SOURCE_LABELS). */
export const SOURCE_LABELS: Record<string, string> = {
  frankfurter_ecb: "ECB reference rate (Frankfurter)",
  frankfurter_cba: "CBA daily rate (Frankfurter)",
  fred: "FRED",
  ecb_data_portal: "ECB Data Portal",
  cba_rates: "CBA policy rates",
  fed_rss: "Fed press releases",
  ecb_rss: "ECB press releases",
  cba_news: "CBA decisions (cba.am, ARKA, Interfax)",
  atlanta_fed: "Atlanta Fed Market Probability Tracker",
};

/** Short names for the compact "last update" strip; the warning uses the API's full label. */
export const SOURCE_SHORT: Record<string, string> = {
  frankfurter_ecb: "ECB rate",
  frankfurter_cba: "CBA rate",
  fred: "FRED",
  ecb_data_portal: "ECB Data Portal",
  cba_rates: "CBA policy rates",
  fed_rss: "Fed releases",
  ecb_rss: "ECB releases",
  cba_news: "CBA news",
  atlanta_fed: "Atlanta Fed",
};

/**
 * Sources whose data feeds the forecast for each pair. This is the API's pair_sources
 * (rate source, plus each bank's policy-rate and news source) plus the Atlanta Fed tracker,
 * which sets the expected Fed rate behind the Fed surprise driver.
 */
export const PAIR_SOURCES: Record<PairId, string[]> = {
  EURUSD: ["frankfurter_ecb", "fred", "ecb_data_portal", "fed_rss", "ecb_rss", "atlanta_fed"],
  USDAMD: ["frankfurter_cba", "fred", "cba_rates", "fed_rss", "cba_news", "atlanta_fed"],
  EURAMD: [
    "frankfurter_cba",
    "fred",
    "ecb_data_portal",
    "cba_rates",
    "fed_rss",
    "ecb_rss",
    "cba_news",
    "atlanta_fed",
  ],
};

/** Sources behind the central bank events view. */
export const EVENT_SOURCES = ["fed_rss", "ecb_rss", "cba_rates", "cba_news", "atlanta_fed"];

export type ViewId = "pair" | "drivers" | "events" | "backtest";
export const VIEWS: { id: ViewId; label: string }[] = [
  { id: "pair", label: "Pair" },
  { id: "drivers", label: "Drivers" },
  { id: "events", label: "Events" },
  { id: "backtest", label: "Backtest" },
];

export function relevantSources(view: ViewId, pair: PairId): string[] {
  return view === "events" ? EVENT_SOURCES : PAIR_SOURCES[pair];
}

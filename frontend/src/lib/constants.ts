/** Mirrors backend/src/fxf/constants.py. Use these names; do not hardcode strings in views. */

import type { BandKey, BankId, PairId } from "../api/types";
import { t, tMaybe, type Key } from "../i18n";

/** English source text; the UI shows t("disclaimer") in the active language. */
export const DISCLAIMER = "Statistical estimate. Not financial advice.";

export interface PairMeta {
  id: PairId;
  base: string;
  quote: string;
  label: string; // "EUR/USD"
  rateSource: string;
  /** The reference rate behind the pair, in the active language. */
  readonly sourceLabel: string;
  banks: BankId[];
  /** Decimals for rates: ECB publishes 4, CBA publishes 2; RUB pairs need more. */
  decimals: number;
  /** Sign convention of the policy-rate differential, in the active language. */
  readonly diffLabel: string;
}

function pair(
  id: PairId,
  base: string,
  quote: string,
  rateSource: string,
  banks: BankId[],
  decimals: number,
  sourceKey: Key,
  diffKey: Key,
): PairMeta {
  return {
    id,
    base,
    quote,
    label: `${base}/${quote}`,
    rateSource,
    banks,
    decimals,
    get sourceLabel() {
      return t(sourceKey);
    },
    get diffLabel() {
      return t(diffKey);
    },
  };
}

// Assumed banks for the new pairs: the CBA for dram pairs, the Fed for dollar pairs.
export const PAIRS: Record<PairId, PairMeta> = {
  EURAMD: pair("EURAMD", "EUR", "AMD", "frankfurter_cba", ["FED", "ECB", "CBA"], 2, "source.cbaRate", "diff.EURAMD"),
  USDAMD: pair("USDAMD", "USD", "AMD", "frankfurter_cba", ["FED", "CBA"], 2, "source.cbaRate", "diff.USDAMD"),
  RUBAMD: pair("RUBAMD", "RUB", "AMD", "frankfurter_cba", ["CBA"], 4, "source.cbaRate", "diff.RUBAMD"),
  GBPAMD: pair("GBPAMD", "GBP", "AMD", "frankfurter_cba", ["CBA"], 2, "source.cbaRate", "diff.GBPAMD"),
  EURUSD: pair("EURUSD", "EUR", "USD", "frankfurter_ecb", ["FED", "ECB"], 4, "source.ecbRate", "diff.EURUSD"),
  GBPUSD: pair("GBPUSD", "GBP", "USD", "frankfurter_ecb", ["FED"], 4, "source.ecbRate", "diff.GBPUSD"),
  RUBUSD: pair("RUBUSD", "RUB", "USD", "frankfurter_cba", ["FED"], 6, "source.crossRate", "diff.RUBUSD"),
};
export const PAIR_IDS: PairId[] = ["EURAMD", "USDAMD", "RUBAMD", "GBPAMD", "EURUSD", "GBPUSD", "RUBUSD"];

export function isPairId(v: string | undefined): v is PairId {
  return v !== undefined && (PAIR_IDS as string[]).includes(v);
}

/** Currencies the picker offers, and which quote currencies each one can be converted to. */
export const BASES = ["EUR", "USD", "RUB", "GBP"] as const;
export const QUOTES_FOR: Record<string, string[]> = {
  EUR: ["AMD", "USD"],
  USD: ["AMD"],
  RUB: ["AMD", "USD"],
  GBP: ["AMD", "USD"],
};
export function pairOf(base: string, quote: string): PairId | null {
  const id = `${base}${quote}`;
  return isPairId(id) ? id : null;
}
export const CURRENCY_SYMBOL: Record<string, string> = { EUR: "€", USD: "$", GBP: "£", RUB: "₽", AMD: "֏" };

/** A record whose values are translated on read: `labels.FED` -> t("bank.FED"). */
function translated(prefix: string): Record<string, string> {
  return new Proxy({} as Record<string, string>, {
    get: (_, k) => (typeof k === "string" ? (tMaybe(`${prefix}.${k}`) ?? undefined) : undefined),
  });
}

export const HORIZONS = [
  {
    days: 1,
    label: "1D",
    get long() {
      return t("horizon.long.1D");
    },
  },
  {
    days: 5,
    label: "1W",
    get long() {
      return t("horizon.long.1W");
    },
  },
  {
    days: 21,
    label: "1M",
    get long() {
      return t("horizon.long.1M");
    },
  },
] as const;
export const HORIZON_LABELS: Record<number, string> = { 1: "1D", 5: "1W", 21: "1M" };

export const BANKS: BankId[] = ["FED", "ECB", "CBA"];
export const BANK_LABELS = translated("bank");
export const BANK_LONG = translated("bankLong");
export const RATE_TYPE_LABELS = translated("rateType");
export const MODEL_LABELS = translated("model");
export const MODEL_ORDER = ["random_walk", "forward", "lightgbm"];

/** Band keys from widest to narrowest: the drawing order of the fan. */
export const BAND_KEYS: BandKey[] = ["95", "80", "50"];
export const BAND_NOMINAL: Record<BandKey, number> = { "50": 0.5, "80": 0.8, "95": 0.95 };

// --- Sources (job_runs.job and /api/health keys) ----------------------------------------

/** Source names in the active language (the API sends English labels). */
export const SOURCE_LABELS = translated("sourceName");
/** Short names for the compact "last update" strip. */
export const SOURCE_SHORT = translated("sourceShort");

/**
 * Sources whose data feeds the forecast for each pair. This is the API's pair_sources
 * (rate source, plus each bank's policy-rate and news source) plus the Atlanta Fed tracker,
 * which sets the expected Fed rate behind the Fed surprise driver.
 */
export const PAIR_SOURCES: Record<PairId, string[]> = {
  EURUSD: ["frankfurter_ecb", "fred", "ecb_data_portal", "fed_rss", "ecb_rss", "atlanta_fed"],
  USDAMD: ["frankfurter_cba", "fred", "cba_rates", "fed_rss", "cba_news", "atlanta_fed"],
  EURAMD: ["frankfurter_cba", "fred", "ecb_data_portal", "cba_rates", "fed_rss", "ecb_rss", "cba_news", "atlanta_fed"],
  RUBAMD: ["frankfurter_cba", "cba_rates", "cba_news"],
  GBPAMD: ["frankfurter_cba", "cba_rates", "cba_news"],
  GBPUSD: ["frankfurter_ecb", "fred", "fed_rss", "atlanta_fed"],
  RUBUSD: ["frankfurter_cba", "fred", "fed_rss", "atlanta_fed"],
};

/** Sources behind the central bank events view. */
export const EVENT_SOURCES = ["fed_rss", "ecb_rss", "cba_rates", "cba_news", "atlanta_fed"];

export type ViewId = "pair" | "drivers" | "events" | "backtest";
export const VIEWS: { id: ViewId; readonly label: string }[] = (["pair", "drivers", "events", "backtest"] as const).map(
  (id) => ({
    id,
    get label() {
      return t(`view.${id}`);
    },
  }),
);

export function relevantSources(view: ViewId, pair: PairId): string[] {
  return view === "events" ? EVENT_SOURCES : PAIR_SOURCES[pair];
}

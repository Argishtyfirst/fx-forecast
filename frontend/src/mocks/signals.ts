/**
 * FR-17 signal variants for tests and visual QA. The default fixtures are all "no_edge"
 * (the realistic state); these cover every action and every confidence level.
 */
import type { AiView, ConversionSignal, LatestForecastResponse } from "../api/types";
import { fixtures } from "./index";

const base = fixtures.latest.EURAMD;
const byLabel = (label: string) => base.horizons.find((h) => h.label === label)!;

function signal(label: string, patch: Partial<ConversionSignal>): ConversionSignal {
  const h = byLabel(label);
  return { ...(h.signal as ConversionSignal), ...patch };
}

function aiView(label: string, patch: Partial<AiView>, track: Partial<AiView["track_record"]> = {}): AiView {
  const v = byLabel(label).ai_view as AiView;
  return { ...v, ...patch, track_record: { ...v.track_record, ...track } };
}

export const SIGNALS = {
  /** The usual answer: no model beats the random walk. */
  noEdgeNone: signal("1M", {}),
  /** A promoted model, but the edge is under 5 points: still no lean. */
  noEdgeLow: signal("1M", {
    action: "no_edge",
    prob_better_if_wait: 0.53,
    expected_change_pct: 0.06,
    confidence: "low",
    model: "lightgbm",
    model_beats_random_walk: true,
    hit_rate: 0.53,
    dm_pvalue: 0.07,
    mae_ratio_rw: 0.968,
    n_obs: 250,
    summary: "No clear edge: the forecast puts the chance of a better rate after 1M at 53%.",
  }),
  waitLow: signal("1W", {
    action: "wait",
    prob_better_if_wait: 0.56,
    expected_change_pct: 0.11,
    confidence: "low",
    model: "forward",
    model_beats_random_walk: true,
    hit_rate: 0.52,
    dm_pvalue: 0.09,
    mae_ratio_rw: 0.975,
    n_obs: 250,
    summary:
      "Wait: 56% chance of a better EUR/AMD rate after 1W (forward-rate model, right on direction 52% of the last 250 days).",
  }),
  waitMedium: signal("1M", {
    action: "wait",
    prob_better_if_wait: 0.58,
    expected_change_pct: 0.42,
    confidence: "medium",
    model: "forward",
    model_beats_random_walk: true,
    hit_rate: 0.55,
    dm_pvalue: 0.06,
    mae_ratio_rw: 0.961,
    n_obs: 250,
    summary:
      "Wait: 58% chance of a better EUR/AMD rate after 1M (forward-rate model, right on direction 55% of the last 250 days).",
  }),
  sellNowHigh: signal("1M", {
    action: "sell_now",
    prob_better_if_wait: 0.31,
    expected_change_pct: -0.94,
    confidence: "high",
    model: "lightgbm",
    model_beats_random_walk: true,
    hit_rate: 0.61,
    dm_pvalue: 0.02,
    mae_ratio_rw: 0.944,
    n_obs: 250,
    summary:
      "Sell now: 69% chance the EUR/AMD rate is worse after 1M (LightGBM model, right on direction 61% of the last 250 days).",
  }),
  /** Holding the base currency pays more: the interest line names EUR. */
  negativeCarry: signal("1M", {
    carry_pct_per_year: -4.5,
    carry_over_horizon_pct: -0.375,
    carry_amount: -1.5189,
  }),
  /** Policy rates unavailable at the cutoff: no interest line. */
  nullCarry: signal("1M", { carry_pct_per_year: null, carry_over_horizon_pct: null, carry_amount: null }),
  /** The AI view met the promotion rule, so it decides the verdict. */
  aiDecides: signal("1M", {
    action: "wait",
    verdict_source: "ai",
    prob_better_if_wait: 0.57,
    expected_change_pct: 0.21,
    confidence: "medium",
    model: "gemini-3.5-flash-lite",
    model_beats_random_walk: true,
    hit_rate: 0.57,
    dm_pvalue: 0.06,
    mae_ratio_rw: 0.962,
    n_obs: 263,
    summary:
      "Wait: 57% chance of a better EUR/AMD rate after 1M (AI view, right on direction 57% of 263 scored forecasts).",
  }),
} satisfies Record<string, ConversionSignal>;

export const AI_VIEWS = {
  /** The realistic default: nothing scored yet. */
  unproven: aiView("1M", {}),
  /** Some live forecasts scored, not yet enough to apply the promotion rule. */
  scored: aiView("1M", {}, { n_scored: 37, hit_rate: 0.541, mae_ratio_rw: 0.993, dm_pvalue: 0.41, brier: 0.243 }),
  /** Met the promotion rule on its live record: it decides the verdict. */
  promoted: aiView(
    "1M",
    { prob_better_if_wait: 0.57, expected_change_pct: 0.21, confidence: "medium" },
    { n_scored: 263, hit_rate: 0.57, mae_ratio_rw: 0.962, dm_pvalue: 0.06, brier: 0.231, promoted: true },
  ),
} satisfies Record<string, AiView>;

type Label = "1D" | "1W" | "1M";

/** The EUR/AMD latest forecast with per-horizon signal and AI view replacements (null removes). */
export function latestWith(
  patch: Partial<Record<Label, { signal?: ConversionSignal | null; ai_view?: AiView | null }>>,
): LatestForecastResponse {
  const copy = structuredClone(base);
  for (const h of copy.horizons) {
    const p = patch[h.label as Label];
    if (!p) continue;
    if (p.signal !== undefined) h.signal = p.signal;
    if (p.ai_view !== undefined) h.ai_view = p.ai_view;
  }
  return copy;
}

/** The EUR/AMD latest forecast with the given signal per horizon label (null removes it). */
export function latestWithSignals(signals: Partial<Record<Label, ConversionSignal | null>>): LatestForecastResponse {
  return latestWith(
    Object.fromEntries(Object.entries(signals).map(([k, v]) => [k, { signal: v }])) as Parameters<
      typeof latestWith
    >[0],
  );
}

/**
 * Mirrors backend/src/fxf/api/schemas.py one to one. Keep field names and nullability identical.
 * Dates (dt.date) are ISO "YYYY-MM-DD" strings; datetimes are ISO 8601 UTC strings.
 */

export type IsoDate = string;
export type IsoDateTime = string;

export type PairId = "EURUSD" | "USDAMD" | "EURAMD";
export type BankId = "FED" | "ECB" | "CBA";
export type HorizonLabel = "1D" | "1W" | "1M";
export type BandKey = "50" | "80" | "95";
export type ModelId = "random_walk" | "forward" | "lightgbm";
export type BacktestWindow = "250d" | "full";
export type RunStatus = "success" | "failed" | "running";

// --- /api/pairs -------------------------------------------------------------------

export interface HorizonOut {
  days: number;
  label: string; // "1D" | "1W" | "1M"
}

export interface PairOut {
  id: string; // "EURUSD"
  base: string;
  quote: string;
  source: string; // source key, e.g. "frankfurter_ecb"
  source_label: string; // "ECB reference rate"
  banks: string[];
}

export interface PairsResponse {
  pairs: PairOut[];
  horizons: HorizonOut[];
}

// --- /api/rates/{pair} -------------------------------------------------------------

export interface RatePoint {
  date: IsoDate;
  rate: number;
}

export interface RatesResponse {
  pair: string;
  source: string;
  rates: RatePoint[];
}

// --- shared --------------------------------------------------------------------------

export interface MeetingRef {
  bank: string;
  date: IsoDate;
}

export interface SourceStatus {
  source: string;
  label: string;
  last_success: IsoDateTime | null;
  last_run: IsoDateTime | null;
  last_status: string | null; // success | failed | running | null (never ran)
  stale: boolean;
  error?: string | null;
}

// --- /api/forecasts/{pair}/latest ---------------------------------------------------

export interface Drivers {
  rate_diff_bps?: number | null;
  rate_diff_change_21d_bps?: number | null;
  policy_rates?: Record<string, number | null>;
  forward_rate?: number | null;
  garch_vol_annual?: number | null;
  horizon_sigma?: number | null;
  event_extra_variance?: number | null;
  last_surprise_bps?: Record<string, number | null>;
  hawkish_score?: Record<string, number | null>;
  days_to_next_meeting?: Record<string, number | null>;
  served_reason?: string | null;
}

/**
 * FR-17: "Should I sell my <base> now?" for someone converting `sell` (base) into `receive`
 * (quote). A statistical summary of the served forecast and its backtest evidence.
 */
export type SignalAction = "sell_now" | "wait" | "no_edge";
export type SignalConfidence = "none" | "low" | "medium" | "high";

export type VerdictSource = "statistical" | "ai";

/** A meeting inside the horizon, with what last year's data says about it. Not AI text. */
export interface MeetingRiskOut {
  bank: string;
  date: IsoDate;
  reaction_vs_normal: number | null; // mean |reaction| / mean |normal day| over the last year
  meetings_last_year: number;
  band80_meeting_weeks: number | null; // share of outcomes inside the 80% range, that bank's weeks
  band80_other_weeks: number | null; // same, weeks without a meeting
  n_meeting_weeks: number | null;
  level: "higher" | "normal" | "lower"; // expected swing around this meeting
  summary: string;
}

export interface ConversionSignal {
  action: SignalAction;
  /** Who decided the verdict: the backtested models, or the AI view once promoted. */
  verdict_source: VerdictSource;
  sell: string; // base currency, e.g. "EUR"
  receive: string; // quote currency, e.g. "AMD"
  /** P(rate at the target date > spot) under the forecast behind the verdict, 0..1. */
  prob_better_if_wait: number;
  expected_change_pct: number; // (center / spot - 1) * 100
  downside_p10_rate: number; // 1-in-10 chance the rate at the target is at or below this
  upside_p90_rate: number; // 1-in-10 chance it is at or above this
  risk_half_width_pct: number; // half the 80% range, in percent of spot: the risk of waiting
  /**
   * Holding the quote currency instead of the base, at policy rates (quote bank minus base
   * bank). Positive means converting now and holding the quote currency earns more.
   */
  carry_pct_per_year: number | null;
  carry_over_horizon_pct: number | null;
  carry_amount: number | null; // in quote currency per 1 unit of base over the horizon
  confidence: SignalConfidence;
  model: string;
  model_beats_random_walk: boolean; // met the promotion rule on the last 250 days
  hit_rate: number | null; // directional hit rate of the model behind the verdict
  dm_pvalue: number | null;
  mae_ratio_rw: number | null;
  n_obs: number | null;
  summary: string;
}

export type AiConfidence = "low" | "medium" | "high";

/** Live-only scoring of the AI view: forecasts made before the outcome was known. */
export interface AiTrackRecord {
  n_scored: number; // forecasts whose target date has passed
  required: number; // scored forecasts needed before the promotion rule can apply
  hit_rate: number | null;
  mae_ratio_rw: number | null; // against the random walk on the same dates
  dm_pvalue: number | null;
  brier: number | null; // of prob_better_if_wait; 0.25 is a coin flip
  promoted: boolean; // meets the promotion rule, so it decides the verdict
}

/** Experimental: an LLM's read of the same context the dashboard shows. */
export interface AiView {
  provider: string; // "gemini"
  model: string; // e.g. "gemini-3.5-flash-lite"
  prompt_version: string;
  generated_at: IsoDateTime;
  prob_better_if_wait: number;
  expected_change_pct: number;
  /** The AI's expected rate at the target date. */
  center: number;
  /** The 80% range re-centred on the AI's expectation: [low, high]. */
  band80: [number, number];
  /** Its own call for someone selling the base, by the same 5-point threshold as the verdict. */
  lean: SignalAction;
  /** "clear": at least a 5-point lean; "slight": 2 to 5 points; "none": under 2 (no_edge). */
  strength?: AiStrength;
  confidence: AiConfidence;
  reasoning: string;
  track_record: AiTrackRecord;
  /** The day of the AI call; on a weekend it is Friday's call, carried over. */
  run_date?: IsoDate;
  /** One call a day: earlier answers of run_date that new inputs replaced (0 almost always). */
  revisions?: number;
  /** The AI's call on the previous run day, for "yesterday vs today". */
  previous?: AiPrevious | null;
}

export interface AiPrevious {
  run_date: IsoDate;
  prob_better_if_wait: number;
  lean: SignalAction;
  strength: AiStrength;
  confidence: AiConfidence;
}

// --- /api/quotes/{pair}?amount= (provider rates, AMD pairs only) --------------------------------

export type QuoteChannel = "cash" | "non_cash" | "card" | "online" | "transfer";

export interface ProviderQuote {
  provider: string; // "ameriabank", "wise", "paysend"
  name: string; // "Ameriabank"
  kind: "bank" | "app" | "transfer";
  channel: QuoteChannel; // "online": the bank's app rate
  rate: number; // quote currency per 1 base when you sell the base (e.g. AMD per EUR)
  fee: number; // estimated fee for this amount, in the quote currency (0 if none known)
  net: number; // quote currency received for `amount` after the fee
  vs_reference_pct: number | null; // net vs amount x the CBA rate, in percent
  fetched_at: IsoDateTime;
  quoted_at?: IsoDateTime | null;
  stale: boolean; // older than about 26h
  url: string | null;
  note: string | null;
  /** Estimated arrival for transfers: an ISO date (Wise) or free text (Paysend). */
  delivery?: string | null;
}

/** A provider that publishes no rate we may read, shown as a quiet line. */
export interface UnavailableProvider {
  provider: string;
  name: string;
  reason: string;
  url: string | null;
}

export interface QuotesResponse {
  pair: string;
  amount: number;
  reference: { source: string; rate: number; date: IsoDate } | null; // CBA official rate
  as_of: IsoDateTime | null; // newest fetched_at
  quotes: ProviderQuote[]; // best first; stale quotes last
  unavailable?: UnavailableProvider[];
  indicative: boolean;
  disclaimer: string;
}

export interface HorizonForecast {
  days: number;
  label: string;
  target_date: IsoDate;
  model: string; // served model
  model_version: string;
  center: number;
  /** "50" | "80" | "95" -> [low, high] */
  bands: Record<string, [number, number]>;
  meetings: MeetingRef[];
  drivers: Drivers;
  signal?: ConversionSignal | null;
  ai_view?: AiView | null;
  meeting_risks?: MeetingRiskOut[];
}

export interface LatestForecastResponse {
  pair: string;
  as_of: IsoDate; // run_date
  spot: number;
  spot_date: IsoDate;
  disclaimer: string;
  horizons: HorizonForecast[];
  stale_sources: SourceStatus[];
}

// --- /api/forecasts/{pair}?run_date= ----------------------------------------------------

export interface ForecastRow {
  model: string;
  model_version: string;
  horizon_days: number;
  target_date: IsoDate;
  spot: number;
  center: number;
  q025: number;
  q10: number;
  q25: number;
  q75: number;
  q90: number;
  q975: number;
  served: boolean;
  meetings: MeetingRef[];
  git_sha: string;
}

export interface ForecastRunResponse {
  pair: string;
  run_date: IsoDate;
  available_run_dates: IsoDate[]; // most recent first, up to 60
  rows: ForecastRow[];
}

// --- /api/backtests/{pair}?horizon= ------------------------------------------------------

export interface BacktestTargets {
  mae_ratio: number; // 1.0
  hit_rate: number; // 0.5
  coverage_tolerance: number; // 0.05
  dm_pvalue: number; // 0.10
  promotion_mae_ratio: number; // 0.98
}

export interface BacktestMetricOut {
  horizon_days: number;
  model: string;
  window: string; // "250d" | "full"
  n_obs: number;
  start_date: IsoDate | null;
  end_date: IsoDate | null;
  mae: number;
  mae_ratio_rw: number;
  hit_rate: number | null;
  cov50: number;
  cov80: number;
  cov95: number;
  pinball: number;
  pinball_ref: number | null;
  dm_pvalue: number | null;
  promoted: boolean; // meets the promotion rule (window 250d only)
  served: boolean; // served in the latest forecast run
}

/**
 * Metrics over the last 250 origins, split by whether a meeting of `bank` fell inside the horizon
 * ("none": no meeting of any of the pair's banks).
 */
export interface EventWindowMetricOut {
  horizon_days: number;
  model: string;
  bank: string; // "FED" | "ECB" | "CBA" | "none"
  n_obs: number;
  mae_ratio_rw: number;
  hit_rate: number | null;
  cov50: number;
  cov80: number;
  cov95: number;
}

export interface AiTrackRow {
  horizon_days: number;
  model_version: string | null; // the AI view's latest "<model>@<prompt>", null if it never ran
  track_record: AiTrackRecord;
}

/** Experimental: the AI's weekly written reading of the meeting study and the around-meetings backtest. */
export interface AiAnalysisOut {
  run_date: IsoDate;
  provider: string;
  model: string;
  prompt_version: string;
  generated_at: IsoDateTime;
  headline: string; // the takeaway sentence
  points: string[];
  watch_next: string;
  for_you?: string; // what it means for someone converting the base currency
}

export interface BacktestResponse {
  pair: string;
  run_date: IsoDate | null;
  targets: BacktestTargets;
  metrics: BacktestMetricOut[]; // windows "250d" and "full"
  event_metrics?: EventWindowMetricOut[];
  ai_track?: AiTrackRow[];
  ai_analysis?: AiAnalysisOut | null;
}

// --- /api/events ---------------------------------------------------------------------------

export interface StatementDiff {
  added: string[];
  removed: string[];
  previous_event_id?: number | null;
}

export interface DecisionOut {
  id: number;
  bank: string;
  date: IsoDate;
  rate_type: string;
  rate_before: number | null;
  rate_after: number | null;
  expected: number | null;
  expected_source: string | null;
  surprise_bps: number | null;
  /** Every rate of the decision, e.g. {"refinancing": {"before": 7.0, "after": 6.75}, ...}. Percent. */
  rates: Record<string, Record<string, number | null>> | null;
  statement_url: string | null;
  statement_text: string | null;
  statement_diff: StatementDiff | null;
  hawkish_score: number | null;
  hawkish_reason: string | null;
  scorer_version: string | null;
}

export interface UpcomingMeeting {
  bank: string;
  date: IsoDate;
  scheduled: boolean;
  days_until: number;
}

export interface EventsResponse {
  decisions: DecisionOut[]; // most recent first
  upcoming: UpcomingMeeting[]; // soonest first
}

// --- /api/meetings/{pair}?lookback_days= -------------------------------------------------------

/** One day of a meeting's path: % change against the last fix before the decision. */
export interface PathPoint {
  offset: number; // trading days from the last fix before the decision (1 = first fix after)
  date: IsoDate;
  pct: number;
}

export interface TypicalPathPoint {
  offset: number;
  mean_abs_pct: number; // how far, on average, the pair was from its pre-decision level
  meetings: number;
}

/** How the pair moved around one meeting. Moves in percent. */
export interface MeetingReactionOut {
  bank: string;
  date: IsoDate;
  surprise_bps: number | null;
  hawkish_score: number | null;
  rate_change_bps: number | null;
  run_up_pct: number | null; // 5 fixes into the meeting
  reaction_pct: number; // last fix before the decision to the first fix after
  follow_pct: number | null; // 5 fixes after the reaction
  expected_sign: number; // +1 a hawkish signal should lift the pair, -1 lower it, 0 no view
  signal: number; // +1 hawkish (surprise, else tone), -1 dovish, 0 neutral
  followed: boolean | null; // the reaction went the way the signal implies
  path?: PathPoint[]; // day by day, -10..+10
}

export interface BankReactionSummaryOut {
  bank: string;
  n: number;
  mean_abs_reaction_pct: number | null;
  normal_abs_move_pct: number | null; // median |daily move| on other days
  reaction_ratio: number | null; // mean |reaction| / normal move
  mean_run_up_pct: number | null;
  mean_follow_pct: number | null;
  n_signed: number;
  consistency: number | null; // share of signed meetings the reaction followed
  correlation: number | null;
  typical_path?: TypicalPathPoint[];
}

export interface MeetingStudyResponse {
  pair: string;
  as_of: IsoDate;
  lookback_days: number;
  window_days: number; // fixes counted for the run-up and the follow-through
  banks: BankReactionSummaryOut[];
  meetings: MeetingReactionOut[]; // most recent first
  path_days?: number; // each path runs from -path_days to +path_days
}

// --- /api/health ----------------------------------------------------------------------------

export interface JobStatus {
  job: string;
  last_success: IsoDateTime | null;
  last_run: IsoDateTime | null;
  last_status: string | null;
  last_duration_s: number | null;
  last_rows_written: number | null;
  error?: string | null;
}

export interface HealthResponse {
  status: string; // "ok" | "degraded"
  checked_at: IsoDateTime;
  sources: SourceStatus[];
  jobs: JobStatus[];
}

export type AiStrength = "clear" | "slight" | "none";

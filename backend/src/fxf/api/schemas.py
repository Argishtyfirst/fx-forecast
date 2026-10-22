"""Response models for the read-only REST API. The frontend mirrors these in TypeScript
(frontend/src/api/types.ts). Dates are ISO strings; datetimes are ISO 8601 UTC.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

# --- /api/pairs ----------------------------------------------------------------


class HorizonOut(BaseModel):
    days: int
    label: str  # "1D" | "1W" | "1M"


class PairOut(BaseModel):
    id: str  # "EURUSD"
    base: str
    quote: str
    source: str  # source key, e.g. "frankfurter_ecb"
    source_label: str  # "ECB reference rate"
    banks: list[str]


class PairsResponse(BaseModel):
    pairs: list[PairOut]
    horizons: list[HorizonOut]


# --- /api/rates/{pair} -----------------------------------------------------------


class RatePoint(BaseModel):
    date: dt.date
    rate: float


class RatesResponse(BaseModel):
    pair: str
    source: str
    rates: list[RatePoint]


# --- shared ------------------------------------------------------------------------


class MeetingRef(BaseModel):
    bank: str
    date: dt.date


class SourceStatus(BaseModel):
    source: str
    label: str
    last_success: dt.datetime | None
    last_run: dt.datetime | None
    last_status: str | None  # success | failed | running | None (never ran)
    stale: bool
    error: str | None = None


# --- /api/forecasts/{pair}/latest ------------------------------------------------------


class Drivers(BaseModel):
    rate_diff_bps: float | None = None
    rate_diff_change_21d_bps: float | None = None
    policy_rates: dict[str, float | None] = Field(default_factory=dict)
    forward_rate: float | None = None
    garch_vol_annual: float | None = None
    horizon_sigma: float | None = None
    event_extra_variance: float | None = None
    last_surprise_bps: dict[str, float | None] = Field(default_factory=dict)
    hawkish_score: dict[str, float | None] = Field(default_factory=dict)
    days_to_next_meeting: dict[str, int | None] = Field(default_factory=dict)
    served_reason: str | None = None


class MeetingRiskOut(BaseModel):
    """A meeting inside the horizon, with what last year's data says about it (fxf.events.study
    and the around-meetings backtest). Deterministic numbers, not AI text."""

    bank: str
    date: dt.date
    reaction_vs_normal: float | None  # mean |reaction| / mean |normal day| over the last year
    meetings_last_year: int
    band80_meeting_weeks: float | None  # share of outcomes inside the 80% range, that bank's weeks
    band80_other_weeks: float | None  # same, weeks without a meeting
    n_meeting_weeks: int | None
    level: Literal["higher", "normal", "lower"]  # expected swing around this meeting
    summary: str


class ConversionSignal(BaseModel):
    """FR-17: "Should I sell my <base> now?" for someone converting base into quote
    (e.g. selling EUR for AMD). A statistical summary of the served forecast and its
    backtest evidence, not financial advice (fxf.api.signal)."""

    action: Literal["sell_now", "wait", "no_edge"]
    # Who decided the verdict: the backtested models, or the AI view once its live track
    # record meets the promotion rule.
    verdict_source: Literal["statistical", "ai"]
    sell: str  # base currency, e.g. "EUR"
    receive: str  # quote currency, e.g. "AMD"
    # P(rate at the target date > spot) under the forecast behind the verdict.
    prob_better_if_wait: float
    expected_change_pct: float  # (center / spot - 1) * 100
    downside_p10_rate: float  # 1-in-10 chance the rate at the target is at or below this
    upside_p90_rate: float  # 1-in-10 chance it is at or above this
    risk_half_width_pct: float  # half the 80% range, in percent of spot: the risk of waiting
    # Holding the quote currency instead of the base, at policy rates (quote bank minus base
    # bank). Positive means converting now and holding the quote currency earns more.
    carry_pct_per_year: float | None
    carry_over_horizon_pct: float | None
    carry_amount: float | None  # in quote currency per 1 unit of base over the horizon
    confidence: Literal["none", "low", "medium", "high"]
    model: str
    model_beats_random_walk: bool  # met the promotion rule on the last 250 days
    hit_rate: float | None  # directional hit rate of the model behind the verdict
    dm_pvalue: float | None
    mae_ratio_rw: float | None
    n_obs: int | None
    summary: str


class AiTrackRecord(BaseModel):
    """Live-only scoring of the AI view: forecasts made before the outcome was known."""

    n_scored: int  # forecasts whose target date has passed
    required: int  # scored forecasts needed before the promotion rule can apply
    hit_rate: float | None
    mae_ratio_rw: float | None  # against the random walk on the same dates
    dm_pvalue: float | None
    brier: float | None  # of prob_better_if_wait; 0.25 is a coin flip
    promoted: bool  # meets the promotion rule, so it decides the verdict


class AiPrevious(BaseModel):
    """The AI's call on the previous run day, for "yesterday vs today"."""

    run_date: dt.date
    prob_better_if_wait: float
    lean: Literal["sell_now", "wait", "no_edge"]
    strength: Literal["clear", "slight", "none"]
    confidence: Literal["low", "medium", "high"]


class AiView(BaseModel):
    """Experimental: an LLM's read of the same context the dashboard shows (fxf.ai)."""

    run_date: dt.date  # the day of the call; on a weekend, Friday's (fxf.api.forecasts)
    provider: str  # "gemini"
    model: str  # e.g. "gemini-3.5-flash-lite"
    prompt_version: str
    generated_at: dt.datetime
    prob_better_if_wait: float
    expected_change_pct: float
    center: float  # the AI's expected rate at the target date
    band80: tuple[float, float]  # the statistical 80% range re-centred on the AI's expectation
    # Its own call for someone selling the base currency. strength "clear" is a lean of at least
    # 5 points (fxf.api.signal.MIN_EDGE), "slight" 2 to 5 points, "none" under 2 (no_edge).
    lean: Literal["sell_now", "wait", "no_edge"]
    strength: Literal["clear", "slight", "none"]
    confidence: Literal["low", "medium", "high"]
    reasoning: str
    reasoning_i18n: dict[str, str] | None = None  # {"en", "hy", "ru"}, from ai-p5 on
    track_record: AiTrackRecord
    # One call a day: a rerun with the same inputs keeps this answer. revisions counts the
    # earlier answers of run_date that new inputs replaced (0 almost always).
    revisions: int = 0
    previous: AiPrevious | None = None


class HorizonForecast(BaseModel):
    days: int
    label: str
    target_date: dt.date
    model: str  # served model
    model_version: str
    center: float
    # "50" | "80" | "95" -> [low, high]
    bands: dict[str, tuple[float, float]]
    meetings: list[MeetingRef]
    drivers: Drivers
    signal: ConversionSignal | None = None
    ai_view: AiView | None = None
    meeting_risks: list[MeetingRiskOut] = Field(default_factory=list)


class LatestForecastResponse(BaseModel):
    pair: str
    as_of: dt.date  # run_date
    spot: float
    spot_date: dt.date
    disclaimer: str
    horizons: list[HorizonForecast]
    stale_sources: list[SourceStatus]


# --- /api/forecasts/{pair}?run_date= -----------------------------------------------------


class ForecastRow(BaseModel):
    model: str
    model_version: str
    horizon_days: int
    target_date: dt.date
    spot: float
    center: float
    q025: float
    q10: float
    q25: float
    q75: float
    q90: float
    q975: float
    served: bool
    meetings: list[MeetingRef]
    git_sha: str


class ForecastRunResponse(BaseModel):
    pair: str
    run_date: dt.date
    available_run_dates: list[dt.date]  # most recent first, up to 60
    rows: list[ForecastRow]


# --- /api/backtests/{pair}?horizon= ------------------------------------------------------


class BacktestTargets(BaseModel):
    mae_ratio: float = 1.0
    hit_rate: float = 0.5
    coverage_tolerance: float = 0.05
    dm_pvalue: float = 0.10
    promotion_mae_ratio: float = 0.98


class BacktestMetricOut(BaseModel):
    horizon_days: int
    model: str
    window: str  # "250d" | "full"
    n_obs: int
    start_date: dt.date | None
    end_date: dt.date | None
    mae: float
    mae_ratio_rw: float
    hit_rate: float | None
    cov50: float
    cov80: float
    cov95: float
    pinball: float
    pinball_ref: float | None
    dm_pvalue: float | None
    promoted: bool  # meets the promotion rule (window 250d only)
    served: bool  # served in the latest forecast run


class EventWindowMetricOut(BaseModel):
    """Backtest metrics over the last 250 origins, split by whether a meeting of `bank` fell
    inside the horizon ("none": no meeting of any of the pair's banks). backtest_metrics
    rows with window "evt_<BANK>" / "evt_none"."""

    horizon_days: int
    model: str
    bank: str  # "FED" | "ECB" | "CBA" | "none"
    n_obs: int
    mae_ratio_rw: float
    hit_rate: float | None
    cov50: float
    cov80: float
    cov95: float


class AiTrackRow(BaseModel):
    horizon_days: int
    model_version: str | None  # the AI view's latest "<model>@<prompt>", None if it never ran
    track_record: AiTrackRecord


class AiAnalysisText(BaseModel):
    headline: str = ""
    for_you: str = ""
    points: list[str] = Field(default_factory=list)
    watch_next: str = ""


class AiAnalysisOut(BaseModel):
    """Experimental: the AI's weekly reading of the meeting study and the around-meetings
    backtest (fxf.ai.analysis). Written text, not a forecast."""

    run_date: dt.date
    provider: str
    model: str
    prompt_version: str
    generated_at: dt.datetime
    headline: str  # the takeaway, one sentence
    for_you: str = ""  # what it means for someone converting the base currency
    points: list[str]
    watch_next: str
    i18n: dict[str, AiAnalysisText] | None = None  # "hy", "ru", from an-p3 on


class BacktestResponse(BaseModel):
    pair: str
    run_date: dt.date | None
    targets: BacktestTargets
    metrics: list[BacktestMetricOut]  # windows "250d" and "full"
    event_metrics: list[EventWindowMetricOut] = Field(default_factory=list)
    ai_track: list[AiTrackRow] = Field(default_factory=list)
    ai_analysis: AiAnalysisOut | None = None


# --- /api/events ---------------------------------------------------------------------------


class StatementDiff(BaseModel):
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    previous_event_id: int | None = None


class DecisionOut(BaseModel):
    id: int
    bank: str
    date: dt.date
    rate_type: str
    rate_before: float | None
    rate_after: float | None
    expected: float | None
    expected_source: str | None
    surprise_bps: float | None
    rates: dict[str, dict[str, float | None]] | None
    statement_url: str | None
    statement_text: str | None
    statement_diff: StatementDiff | None
    hawkish_score: float | None
    hawkish_reason: str | None
    scorer_version: str | None


class UpcomingMeeting(BaseModel):
    bank: str
    date: dt.date
    scheduled: bool
    days_until: int


class EventsResponse(BaseModel):
    decisions: list[DecisionOut]  # most recent first
    upcoming: list[UpcomingMeeting]  # soonest first


# --- /api/meetings/{pair} (meeting reaction study) -------------------------------------------


class PathPoint(BaseModel):
    offset: int  # trading days from the last fix before the decision (1 = first fix after)
    date: dt.date
    pct: float  # % change against the last fix before the decision


class TypicalPathPoint(BaseModel):
    offset: int
    mean_abs_pct: float  # how far, on average, the pair was from its pre-decision level
    meetings: int


class MeetingReactionOut(BaseModel):
    """How the pair moved around one meeting (fxf.events.study). Moves in percent."""

    bank: str
    date: dt.date
    surprise_bps: float | None
    hawkish_score: float | None
    rate_change_bps: float | None
    run_up_pct: float | None  # 5 fixes into the meeting
    reaction_pct: float  # last fix before the decision to the first fix after
    follow_pct: float | None  # 5 fixes after the reaction
    expected_sign: int  # +1 a hawkish signal should lift the pair, -1 lower it, 0 no view
    signal: int  # +1 hawkish (surprise, else tone), -1 dovish, 0 neutral
    followed: bool | None  # the reaction went the way the signal implies
    path: list[PathPoint] = Field(default_factory=list)  # day by day, -10..+10


class BankReactionSummaryOut(BaseModel):
    bank: str
    n: int
    mean_abs_reaction_pct: float | None
    normal_abs_move_pct: float | None  # mean |daily move| on other days
    reaction_ratio: float | None  # mean |reaction| / normal move
    mean_run_up_pct: float | None
    mean_follow_pct: float | None
    n_signed: int
    consistency: float | None  # share of signed meetings the reaction followed
    correlation: float | None
    typical_path: list[TypicalPathPoint] = Field(default_factory=list)


class MeetingStudyResponse(BaseModel):
    pair: str
    as_of: dt.date
    lookback_days: int
    window_days: int  # fixes counted for the run-up and the follow-through
    path_days: int = 10  # each path runs from -path_days to +path_days
    banks: list[BankReactionSummaryOut]
    meetings: list[MeetingReactionOut]  # most recent first


# --- /api/health ----------------------------------------------------------------------------


class JobStatus(BaseModel):
    job: str
    last_success: dt.datetime | None
    last_run: dt.datetime | None
    last_status: str | None
    last_duration_s: float | None
    last_rows_written: int | None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    checked_at: dt.datetime
    sources: list[SourceStatus]
    jobs: list[JobStatus]


class ProviderQuoteOut(BaseModel):
    """One place to convert, priced for the requested amount (fxf.quotes.service)."""

    provider: str
    name: str
    kind: Literal["bank", "app", "transfer"]
    channel: Literal["cash", "non_cash", "card", "online", "transfer"]
    rate: float  # quote currency per 1 base when you sell the base
    fee: float  # estimated fee for this amount, in the quote currency
    net: float  # quote currency received for the amount, after the fee
    vs_reference_pct: float | None  # net vs amount x the CBA rate, in percent
    fetched_at: dt.datetime
    quoted_at: dt.datetime | None
    stale: bool
    url: str | None
    note: str | None
    delivery: str | None = None  # estimated arrival, for transfers


class QuoteReference(BaseModel):
    source: str
    rate: float
    date: dt.date


class UnavailableProvider(BaseModel):
    provider: str
    name: str
    reason: str
    url: str | None


class QuotesResponse(BaseModel):
    pair: str
    amount: float
    reference: QuoteReference | None
    as_of: dt.datetime | None
    quotes: list[ProviderQuoteOut]  # best first; stale quotes last
    unavailable: list[UnavailableProvider]
    indicative: bool
    disclaimer: str

"""Shared identifiers. Every module uses these names; do not hardcode strings elsewhere."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# --- Pairs -----------------------------------------------------------------


@dataclass(frozen=True)
class PairSpec:
    id: str  # API id, e.g. "EURUSD"
    base: str
    quote: str
    provider: str  # Frankfurter provider key
    source: str  # value stored in rates.source and job/source keys
    # Policy-rate macro series used for covered interest parity.
    base_rate_series: str
    quote_rate_series: str
    banks: tuple[str, ...]  # banks whose meetings affect the pair


EURUSD: Final = PairSpec(
    id="EURUSD",
    base="EUR",
    quote="USD",
    provider="ECB",
    source="frankfurter_ecb",
    base_rate_series="ECB_DFR",
    quote_rate_series="FED_MID",
    banks=("FED", "ECB"),
)
USDAMD: Final = PairSpec(
    id="USDAMD",
    base="USD",
    quote="AMD",
    provider="CBA",
    source="frankfurter_cba",
    base_rate_series="FED_MID",
    quote_rate_series="CBA_REFI",
    banks=("FED", "CBA"),
)
EURAMD: Final = PairSpec(
    id="EURAMD",
    base="EUR",
    quote="AMD",
    provider="CBA",
    source="frankfurter_cba",
    base_rate_series="ECB_DFR",
    quote_rate_series="CBA_REFI",
    banks=("FED", "ECB", "CBA"),
)
RUBAMD: Final = PairSpec(
    id="RUBAMD",
    base="RUB",
    quote="AMD",
    provider="CBA",
    source="frankfurter_cba",
    base_rate_series="CBR_KEY",
    quote_rate_series="CBA_REFI",
    banks=("FED", "CBA"),
)
GBPAMD: Final = PairSpec(
    id="GBPAMD",
    base="GBP",
    quote="AMD",
    provider="CBA",
    source="frankfurter_cba",
    base_rate_series="BOE_BANK",
    quote_rate_series="CBA_REFI",
    banks=("FED", "CBA"),
)
GBPUSD: Final = PairSpec(
    id="GBPUSD",
    base="GBP",
    quote="USD",
    provider="ECB",  # the ECB's EUR/USD and EUR/GBP fixes, crossed by Frankfurter
    source="frankfurter_ecb",
    base_rate_series="BOE_BANK",
    quote_rate_series="FED_MID",
    banks=("FED", "ECB"),
)
# The CBA publishes RUB/AMD and USD/AMD; Frankfurter's RUB/USD cross is rounded to 5
# decimals (0.01221, a 0.08% step), so RUB/USD is derived as RUBAMD / USDAMD instead
# (fxf.ingest.frankfurter.derive_crosses).
RUBUSD: Final = PairSpec(
    id="RUBUSD",
    base="RUB",
    quote="USD",
    provider="CBA",
    source="frankfurter_cba",
    base_rate_series="CBR_KEY",
    quote_rate_series="FED_MID",
    banks=("FED", "CBA"),
)
PAIRS: Final[dict[str, PairSpec]] = {
    p.id: p for p in (EURAMD, USDAMD, RUBAMD, GBPAMD, EURUSD, GBPUSD, RUBUSD)
}

# Policy rate series and central bank of each currency. BOE and CBR have policy rates
# (fxf.ingest.policy) but no meeting calendar or statements yet, so they are not in BANKS.
CURRENCY_RATE_SERIES: Final[dict[str, str]] = {
    "EUR": "ECB_DFR",
    "USD": "FED_MID",
    "AMD": "CBA_REFI",
    "GBP": "BOE_BANK",
    "RUB": "CBR_KEY",
}
CURRENCY_BANK: Final[dict[str, str]] = {
    "EUR": "ECB",
    "USD": "FED",
    "AMD": "CBA",
    "GBP": "BOE",
    "RUB": "CBR",
}
SERIES_BANK: Final[dict[str, str]] = {CURRENCY_RATE_SERIES[c]: b for c, b in CURRENCY_BANK.items()}

# --- Horizons (trading days) ----------------------------------------------

HORIZONS: Final[tuple[int, ...]] = (1, 5, 21)
HORIZON_LABELS: Final[dict[int, str]] = {1: "1D", 5: "1W", 21: "1M"}

# --- Central banks ----------------------------------------------------------

BANKS: Final[tuple[str, ...]] = ("FED", "ECB", "CBA")

# Policy rate type recorded in cb_events.rate_type for the headline rate.
BANK_POLICY_RATE: Final[dict[str, str]] = {
    "FED": "target_mid",
    "ECB": "deposit",
    "CBA": "refinancing",
}

# --- Models -----------------------------------------------------------------

MODEL_RW: Final = "random_walk"
MODEL_FORWARD: Final = "forward"
MODEL_LGBM: Final = "lightgbm"
MODELS: Final[tuple[str, ...]] = (MODEL_RW, MODEL_FORWARD, MODEL_LGBM)
# The experimental AI view (fxf.ai). Never backtested: an LLM has seen historical rates, so
# it is scored only on forecasts made live, and it never enters CENTER_CANDIDATES.
MODEL_LLM: Final = "llm"

# Center candidates per horizon (spec: Forecasting models table).
CENTER_CANDIDATES: Final[dict[int, tuple[str, ...]]] = {
    1: (MODEL_RW, MODEL_LGBM),
    5: (MODEL_RW, MODEL_FORWARD, MODEL_LGBM),
    21: (MODEL_RW, MODEL_FORWARD, MODEL_LGBM),
}

# Quantile levels stored on each forecast row: column name -> probability.
QUANTILE_COLUMNS: Final[dict[str, float]] = {
    "q025": 0.025,
    "q10": 0.10,
    "q25": 0.25,
    "q75": 0.75,
    "q90": 0.90,
    "q975": 0.975,
}
# Band label -> (lower column, upper column).
BANDS: Final[dict[str, tuple[str, str]]] = {
    "50": ("q25", "q75"),
    "80": ("q10", "q90"),
    "95": ("q025", "q975"),
}

# Promotion rule (spec: Evaluation and backtesting).
PROMOTION_MAE_RATIO: Final = 0.98
PROMOTION_DM_PVALUE: Final = 0.10
BACKTEST_WINDOW_DAYS: Final = 250
WINDOW_RECENT: Final = "250d"
WINDOW_FULL: Final = "full"

# --- Macro series ids (macro_series.series_id) --------------------------------

FRED_SERIES: Final[tuple[str, ...]] = (
    "DFEDTARU",
    "DFEDTARL",
    "DFF",
    "FEDTARMD",
    "DGS2",
    "DCOILBRENTEU",
    "DTWEXBGS",
)
ECB_SERIES: Final[tuple[str, ...]] = ("ECB_DFR", "ESTR", "HICP")
CBA_SERIES: Final[tuple[str, ...]] = ("CBA_REFI", "CBA_LOMBARD", "CBA_DEPOSIT")
# Bank of England Bank Rate and the Bank of Russia key rate (fxf.ingest.policy).
POLICY_SERIES: Final[tuple[str, ...]] = ("BOE_BANK", "CBR_KEY")
# Market-implied Fed funds midpoint expected after the next FOMC meeting.
ATLFED_SERIES: Final = "ATLFED_EXP_NEXT"
# Derived series computed on read, never stored: (DFEDTARU + DFEDTARL) / 2.
FED_MID: Final = "FED_MID"

# --- Sources (job_runs.job and /api/health keys) -----------------------------
# One ingest job per source, so the last successful run per source is the last
# successful job run with that name.

SOURCE_FRANKFURTER_ECB: Final = "frankfurter_ecb"
SOURCE_FRANKFURTER_CBA: Final = "frankfurter_cba"
SOURCE_FRED: Final = "fred"
SOURCE_ECB: Final = "ecb_data_portal"
SOURCE_POLICY: Final = "boe_cbr_rates"
SOURCE_CBA: Final = "cba_rates"
SOURCE_FED_RSS: Final = "fed_rss"
SOURCE_ECB_RSS: Final = "ecb_rss"
SOURCE_CBA_NEWS: Final = "cba_news"
SOURCE_ATLFED: Final = "atlanta_fed"

SOURCES: Final[tuple[str, ...]] = (
    SOURCE_FRANKFURTER_ECB,
    SOURCE_FRANKFURTER_CBA,
    SOURCE_FRED,
    SOURCE_ECB,
    SOURCE_POLICY,
    SOURCE_CBA,
    SOURCE_FED_RSS,
    SOURCE_ECB_RSS,
    SOURCE_CBA_NEWS,
    SOURCE_ATLFED,
)

# Pipeline (non-source) job names.
JOB_FORECAST: Final = "forecast"
JOB_BACKTEST: Final = "backtest"
JOB_SCORE: Final = "score_statements"
JOB_AI: Final = "ai_view"
JOB_AI_ANALYSIS: Final = "ai_analysis"
JOB_QUOTES: Final = "provider_quotes"

# Hours after which a source with no newer successful run counts as stale.
# Daily sources tolerate a weekend plus a holiday.
SOURCE_STALE_HOURS: Final[dict[str, int]] = {
    SOURCE_FRANKFURTER_ECB: 96,
    SOURCE_FRANKFURTER_CBA: 96,
    SOURCE_FRED: 96,
    SOURCE_ECB: 96,
    SOURCE_POLICY: 96,
    SOURCE_CBA: 24 * 45,
    SOURCE_FED_RSS: 6,
    SOURCE_ECB_RSS: 6,
    SOURCE_CBA_NEWS: 24 * 45,
    SOURCE_ATLFED: 96,
}

DISCLAIMER: Final = "Statistical estimate. Not financial advice."

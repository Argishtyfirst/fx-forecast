"""Modelling choices shared by the forecast engine and the walk-forward backtest.

Every number here is a documented design decision (spec: Forecasting models, Evaluation
and backtesting). Changing one changes model output, so bump MODEL_VERSIONS with it.
"""

from __future__ import annotations

import datetime as dt
from typing import Final

from fxf.constants import MODEL_FORWARD, MODEL_LGBM, MODEL_RW, PairSpec

# --- Training windows (trading days of returns) --------------------------------------
# AMD pairs (quote currency AMD: USD/AMD, EUR/AMD): rolling window of the last 1000 trading
# days (~4 years). The CBA manages the float and the series has regime breaks (e.g. 2022),
# so old regimes are dropped. Every other pair (EUR/USD): expanding window ("train on all
# data up to day t"). A 500 to 2500-day or expanding GARCH window on USD/AMD gave the same
# pinball loss within 1% on the 2010-2026 backtest, so the suggested 1000 days stays.
MANAGED_QUOTES: Final[frozenset[str]] = frozenset({"AMD"})
ROLLING_WINDOW: Final = 1000


def is_managed(spec: PairSpec) -> bool:
    """A pair quoted in a managed-float currency (the AMD pairs)."""
    return spec.quote in MANAGED_QUOTES


def garch_window(spec: PairSpec) -> int | None:
    """Returns in the GARCH fit window (None: expanding). Also used for the event ratios."""
    return ROLLING_WINDOW if is_managed(spec) else None


def lgbm_window(spec: PairSpec) -> int | None:
    """LightGBM training rows (None: expanding)."""
    return ROLLING_WINDOW if is_managed(spec) else None


# Minimum number of daily returns before a GARCH fit (and so any forecast) is attempted.
GARCH_MIN_OBS: Final = 500

# --- Walk-forward refit cadence (origins, i.e. trading days) -------------------------
# GARCH parameters are refit every 21 origins; between refits the conditional variance
# is filtered daily with fixed parameters on data <= t. LightGBM is refit every 63
# origins. The live engine refits both on every run.
GARCH_REFIT_EVERY: Final = 21
LGBM_REFIT_EVERY: Final = 63

# --- Event widening ---------------------------------------------------------------
# Ratio of realised variance on meeting impact days to normal days, per bank and pair.
# Fewer impact days than this in the window gives no widening for that bank.
EVENT_MIN_MEETINGS: Final = 8
EVENT_MIN_NORMAL_DAYS: Final = 100
# Recency weighting: the ratio over the last 252 trading days, shrunk toward the long-run
# ratio with a prior worth K = 8 meetings (about one year of a bank's meetings).
EVENT_RECENT_DAYS: Final = 252
EVENT_PRIOR_MEETINGS: Final = 8.0
EVENT_RECENT_MIN_NORMAL: Final = 100

# --- 1M empirical quantile check ---------------------------------------------------
# Overlapping 21-day log returns over the last 252 trading days (1 year, the length of the
# evaluation window). If their q90-q10 width exceeds the model 80% width, sigma is scaled up
# to match (widen only). On the 2010-2026 backtest a 504-day lookback over-covered EUR/USD
# 1M (80% band: 89% over the last 250 days) and longer lookbacks more so; 252 days kept
# EUR/USD at 84% and still widened USD/AMD across its regime breaks.
EMPIRICAL_HORIZONS: Final[tuple[int, ...]] = (21,)
EMPIRICAL_LOOKBACK: Final = 252
EMPIRICAL_MIN_OBS: Final = 200

# --- Bands ---------------------------------------------------------------------------
# Floor on the daily return std, so bands never collapse onto the center when a managed
# rate does not move for weeks (and NUMERIC(18,8) keeps the quantiles strictly ordered).
SIGMA_FLOOR_DAILY: Final = 1e-5

# --- Walk-forward band calibration (fxf.forecast.calibration) ------------------------
# The last step of the band model: per pair, horizon and band level, scale the band by the
# quantile of the standardized errors of the trailing 500 origins whose outcome is known
# (s + h <= t). 500 rather than 250: overlapping 21-day errors leave ~12 independent
# observations in 250 origins, and the factor then chases regimes. On the 2010-2026 backtest
# (3 pairs x 3 horizons) the mean |cov80 - 0.80| was 0.043 uncalibrated, 0.010 with 250
# origins, 0.003 with 500 and 0.008 with 1000; 250 origins also left 3 of 9 last-250-day
# cov80 values below 0.75. Per-level factors beat a single 80% factor on the 50% and 95%
# bands (mean |cov50 - 0.50| 0.006 vs 0.025, |cov95 - 0.95| 0.007 vs 0.017).
CAL_WINDOW: Final = 500
CAL_MIN_OBS: Final = 60
CAL_CLAMP: Final[tuple[float, float]] = (0.5, 1.5)
# True: one factor per band level (50/80/95); False: the 80% factor for every level.
CAL_PER_LEVEL: Final = True

# --- LightGBM -------------------------------------------------------------------------
LGBM_MIN_TRAIN_ROWS: Final = 250
# Rows before this index lack the 63-day return feature and are not used for training.
FEATURE_WARMUP: Final = 63

# --- Backtest ---------------------------------------------------------------------------
# First origin of the "full" window, to bound runtime.
BACKTEST_FULL_START: Final = dt.date(2010, 1, 1)
# Risk table: alert when the 80% coverage of an AMD pair (is_managed) over the last 250
# days falls below 70%.
COVERAGE_ALERT_THRESHOLD: Final = 0.70

# --- Versions (forecasts.model_version, NFR-02) ---------------------------------------
BANDS_VERSION: Final = "garch-t2"
MODEL_VERSIONS: Final[dict[str, str]] = {
    MODEL_RW: f"rw1+{BANDS_VERSION}",
    MODEL_FORWARD: f"cip1+{BANDS_VERSION}",
    MODEL_LGBM: f"lgbm1+{BANDS_VERSION}",
}

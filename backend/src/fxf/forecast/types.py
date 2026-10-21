"""Contract between the forecast engine, the backtest, and the API.

All models predict the log return over the horizon; the engine converts to rates:
    center = spot * exp(mu)
    quantile(p) = spot * exp(mu + z_p * sigma_h)   (Student-t z_p, see fxf.forecast.garch)
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

# Keys written to forecasts.features_json and read by the API drivers panel (FR-15).
# Values may be None when an input is unavailable at the cutoff.
FEATURES_JSON_KEYS: dict[str, str] = {
    "spot_date": "date of the last known rate (ISO)",
    "rate_diff_bps": "quote minus base policy rate in bps: Fed-ECB for EURUSD, CBA-Fed for USDAMD, CBA-ECB for EURAMD",
    "rate_diff_change_21d_bps": "21 trading day change of rate_diff_bps",
    "policy_rates": "{bank: rate in percent} at the cutoff",
    "forward_rate": "covered interest parity forward for this horizon",
    "garch_vol_annual": "annualised GARCH(1,1) conditional volatility of daily log returns",
    "horizon_sigma": "std of the horizon log return used for the bands (after widening)",
    "garch_sigma": "std of the horizon log return from GARCH alone",
    "event_extra_variance": "variance added for meetings inside the horizon (log-return units)",
    "empirical_check": "1M only: {'applied': bool, 'empirical_width_80': float, 'garch_width_80': float}",
    "student_t_nu": "Student-t degrees of freedom of the GARCH fit",
    "last_surprise_bps": "{bank: bps or None} of the last decision before the cutoff",
    "hawkish_score": "{bank: -1..1 or None} of the last decision before the cutoff",
    "days_to_next_meeting": "{bank: calendar days or None}",
    "served_reason": "why this model is served (FR-11)",
    "model_inputs": "model-specific inputs, e.g. the LightGBM feature vector",
    "seed": "random seed used (NFR-02)",
}


@dataclass
class ModelForecast:
    run_date: dt.date
    pair: str
    horizon_days: int
    target_date: dt.date
    model: str
    model_version: str
    spot: float
    center: float
    # Column name (q025, q10, q25, q75, q90, q975) -> rate.
    quantiles: dict[str, float]
    meetings: list[dict[str, str]] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)
    served: bool = False

    def bands(self) -> dict[str, tuple[float, float]]:
        from fxf.constants import BANDS

        return {k: (self.quantiles[lo], self.quantiles[hi]) for k, (lo, hi) in BANDS.items()}


# Appended by the forecast engine (fxf.forecast.engine): keys written beyond
# FEATURES_JSON_KEYS, and the sub-keys of features_json["model_inputs"].
EXTRA_FEATURES_JSON_KEYS: dict[str, str] = {
    "student_t_nu_horizon": "degrees of freedom used for the h-day quantiles (fxf.forecast.bands)",
    "horizon_sigma_pre": "horizon std after event widening and the 1M empirical check, before"
    " the walk-forward calibration (horizon_sigma = horizon_sigma_pre * factors['80'])",
    "band_calibration": "walk-forward band calibration (fxf.forecast.calibration): {factors:"
    " {'50', '80', '95': c}, applied, n_obs, outcomes_through (date of the latest realised"
    " outcome used, <= spot_date), window, min_obs, clamp, per_level, center}",
}
MODEL_INPUTS_KEYS: dict[str, str] = {
    "as_of": "{cutoff, rates_through, aux_rates_through, macro_published_at: {series: ts},"
    " cb_events_through[, labels_through]}: latest timestamp of every input (NFR-03)",
    "garch": "GARCH(1,1)-t parameters (percent^2 units) and fit window",
    "event_widening": "{ratios: {bank: combined ratio}, ratio_detail: {bank: {ratio (combined),"
    " ratio_recent, n_recent, ratio_long, n_long, prior_meetings}}, meetings: [{bank, date,"
    " impact_step, impact_date, ratio, extra_variance}]} (fxf.forecast.widening)",
    "horizon_dates": "the h trading dates after the spot date",
    "mu": "predicted h-day log return of this model",
    "forward": "forward rows only: {i_base_pct, i_quote_pct, base_series, quote_series, tau}",
    "lightgbm": "lightgbm rows only: {features, train_rows, train_start, train_end,"
    " labels_through, fit_origin, num_boost_round, params}",
}

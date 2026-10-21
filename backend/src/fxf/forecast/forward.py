"""Forward rate center model: covered interest parity with policy rates (spec: Forward rate).

    F = S * (1 + i_quote * tau) / (1 + i_base * tau)

Rates are policy rates in percent (ECB_DFR, FED_MID, CBA_REFI) and are divided by 100.
tau convention: simple interest over h trading days with 252 trading days per year,
tau = h / 252. EUR/USD: base = ECB_DFR, quote = FED_MID. USD/AMD: base = FED_MID,
quote = CBA_REFI. EUR/AMD: base = ECB_DFR, quote = CBA_REFI (constants.PairSpec holds the
series names for every pair).

The model predicts the h-day log return mu = log(F / S); the engine converts it to a rate.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

TRADING_DAYS_PER_YEAR = 252

ArrayLike = float | npt.NDArray[np.float64]


def year_fraction(horizon_days: int) -> float:
    return horizon_days / TRADING_DAYS_PER_YEAR


def forward_rate(
    spot: ArrayLike, i_base_pct: ArrayLike, i_quote_pct: ArrayLike, horizon_days: int
) -> ArrayLike:
    tau = year_fraction(horizon_days)
    return (
        spot
        * (1.0 + np.asarray(i_quote_pct) / 100.0 * tau)
        / (1.0 + np.asarray(i_base_pct) / 100.0 * tau)
    )


def forward_log_return(
    i_base_pct: ArrayLike, i_quote_pct: ArrayLike, horizon_days: int
) -> ArrayLike:
    """mu = log(F / S). NaN where either rate is unavailable."""
    tau = year_fraction(horizon_days)
    return np.log1p(np.asarray(i_quote_pct, dtype="float64") / 100.0 * tau) - np.log1p(
        np.asarray(i_base_pct, dtype="float64") / 100.0 * tau
    )

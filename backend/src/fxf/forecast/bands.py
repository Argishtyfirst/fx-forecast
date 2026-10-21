"""Band construction: Student-t quantiles of the horizon variance around the center mu.

    quantile(p) = spot * exp(mu + t_unit(p, nu_h) * sigma_h)
    t_unit(p, nu) = t_nu.ppf(p) * sqrt((nu - 2) / nu)          (unit-variance Student-t)

nu_h is the degrees of freedom for the h-day sum. The daily GARCH fit gives nu; the sum of h
independent unit-variance t_nu returns has excess kurtosis 6 / ((nu - 4) h), which a t with
nu_h = 4 + (nu - 4) h matches. Using the daily nu at 1W and 1M would make the 50% and 80%
bands too narrow for a near-normal horizon sum. For nu <= 4 (infinite kurtosis) nu - 4 is
floored at NU_EXCESS_FLOOR. For h = 1, nu_h = nu.

The 1M empirical check compares the model 80% width with the q90 - q10 width of the
overlapping 21-day log returns over a rolling lookback (params.EMPIRICAL_LOOKBACK) and
only ever widens.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from fxf.constants import BANDS, QUANTILE_COLUMNS
from fxf.forecast import params

NU_EXCESS_FLOOR = 0.5
NU_MAX = 200.0
QUANTILE_NAMES: tuple[str, ...] = tuple(QUANTILE_COLUMNS)
QUANTILE_PROBS: np.ndarray = np.array([QUANTILE_COLUMNS[c] for c in QUANTILE_NAMES])
BAND_LEVELS: dict[str, float] = {"50": 0.50, "80": 0.80, "95": 0.95}


@lru_cache(maxsize=4096)
def t_unit_quantile(p: float, nu: float) -> float:
    """Quantile of a Student-t with nu degrees of freedom scaled to unit variance."""
    if nu >= NU_MAX:
        return float(stats.norm.ppf(p))
    return float(stats.t.ppf(p, nu) * math.sqrt((nu - 2.0) / nu))


def horizon_nu(nu: float, horizon_days: int) -> float:
    """Degrees of freedom for the h-day sum (kurtosis matching, see module docstring)."""
    if horizon_days <= 1:
        return float(nu)
    return float(min(NU_MAX, 4.0 + max(nu - 4.0, NU_EXCESS_FLOOR) * horizon_days))


@lru_cache(maxsize=4096)
def _z(nu_h: float) -> tuple[float, ...]:
    return tuple(t_unit_quantile(float(p), nu_h) for p in QUANTILE_PROBS)


def z_values(nu_h: float) -> np.ndarray:
    """Unit-variance quantile offsets in QUANTILE_NAMES order."""
    return np.array(_z(float(nu_h)))


# Band levels of the walk-forward calibration factors, and the level of each quantile column.
CAL_LEVELS: tuple[str, ...] = ("50", "80", "95")
COLUMN_LEVEL: np.ndarray = np.array(
    [CAL_LEVELS.index(next(k for k, cols in BANDS.items() if c in cols)) for c in QUANTILE_NAMES]
)
NO_CALIBRATION: np.ndarray = np.ones(len(CAL_LEVELS))
# Crossing per-level factors keep at least this share of the natural gap between band levels.
MIN_LEVEL_GAP = 0.05


def calibrated_z(z: np.ndarray, cal: np.ndarray | None) -> np.ndarray:
    """Scale symmetric unit quantile offsets (..., 6) by per-level factors (..., 3) for the
    50/80/95 bands, keeping |q75| < |q90| < |q975| so the quantiles stay strictly ascending."""
    z = np.asarray(z, dtype="float64")
    if cal is None:
        return z
    cal = np.asarray(cal, dtype="float64")
    up0 = z[..., 3:]  # natural q75, q90, q975 offsets (positive)
    up = up0 * np.take(cal, COLUMN_LEVEL[3:], axis=-1)
    for k in (1, 2):
        ratio = 1.0 + MIN_LEVEL_GAP * (up0[..., k] / up0[..., k - 1] - 1.0)
        up[..., k] = np.maximum(up[..., k], up[..., k - 1] * ratio)
    return np.concatenate([-up[..., ::-1], up], axis=-1)


def quantile_log_returns(
    mu: float, sigma: float, nu_h: float, cal: np.ndarray | None = None
) -> dict[str, float]:
    z = calibrated_z(z_values(nu_h), cal)
    return {c: float(mu + zi * sigma) for c, zi in zip(QUANTILE_NAMES, z, strict=True)}


def to_rates(
    spot: float, mu: float, sigma: float, nu_h: float, cal: np.ndarray | None = None
) -> tuple[float, dict[str, float]]:
    """(center, {q025..q975}) as rates. cal: per-level calibration factors (50, 80, 95)."""
    q = quantile_log_returns(mu, sigma, nu_h, cal)
    return float(spot * math.exp(mu)), {c: float(spot * math.exp(v)) for c, v in q.items()}


def band_width(sigma: float, nu_h: float, level: str = "80") -> float:
    """Width of the central band in log-return units."""
    p_hi = 0.5 + BAND_LEVELS[level] / 2.0
    return 2.0 * t_unit_quantile(p_hi, nu_h) * sigma


def floor_sigma(sigma: float, horizon_days: int) -> float:
    return max(float(sigma), params.SIGMA_FLOOR_DAILY * math.sqrt(horizon_days))


# --- 1M empirical quantile check ---------------------------------------------------------


def empirical_widths(
    log_rates: np.ndarray,
    horizon_days: int,
    lookback: int = params.EMPIRICAL_LOOKBACK,
    min_obs: int = params.EMPIRICAL_MIN_OBS,
) -> tuple[np.ndarray, np.ndarray]:
    """For each index i: (q90 - q10 of the h-day log returns ending in (i - lookback, i], count).

    Only returns realised by i are used. NaN where fewer than min_obs returns exist.
    """
    lr = pd.Series(np.asarray(log_rates, dtype="float64"))
    rh = lr - lr.shift(horizon_days)
    roll = rh.rolling(lookback, min_periods=min_obs)
    width = (roll.quantile(0.9) - roll.quantile(0.1)).to_numpy()
    count = rh.rolling(lookback, min_periods=1).count().to_numpy()
    return width, count


def empirical_check(
    sigma: float, nu_h: float, empirical_width_80: float | None, n_obs: int | None = None
) -> tuple[float, dict[str, Any]]:
    """Scale sigma up when the empirical 80% width exceeds the model's. Never narrows."""
    model_w = band_width(sigma, nu_h, "80")
    info: dict[str, Any] = {
        "applied": False,
        "empirical_width_80": None,
        "garch_width_80": model_w,
        "scale": 1.0,
        "lookback_days": params.EMPIRICAL_LOOKBACK,
        "n_obs": int(n_obs) if n_obs is not None else None,
    }
    if empirical_width_80 is None or not math.isfinite(empirical_width_80):
        return sigma, info
    info["empirical_width_80"] = float(empirical_width_80)
    if empirical_width_80 > model_w > 0:
        scale = empirical_width_80 / model_w
        info["applied"] = True
        info["scale"] = scale
        return sigma * scale, info
    return sigma, info


def bands_of(quantiles: dict[str, float]) -> dict[str, tuple[float, float]]:
    return {k: (quantiles[lo], quantiles[hi]) for k, (lo, hi) in BANDS.items()}

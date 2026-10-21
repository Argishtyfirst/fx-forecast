"""GARCH(1,1) with Student-t errors on daily log returns (spec: GARCH bands).

Returns are scaled x100 (percent) for the optimiser (arch, zero mean); variances leave this
module in log-return units (divided by 100^2).

    sigma2[t+1] = omega + alpha * r[t]^2 + beta * sigma2[t]          one step ahead
    sigma2[t+k] = omega + (alpha + beta) * sigma2[t+k-1],  k >= 2     since E[r^2] = sigma2

The horizon variance is the sum of the h daily variance forecasts.

Between refits the walk-forward backtest keeps the fitted parameters and filters the
conditional variance forward one day at a time on data <= t (`advance`). When the optimiser
fails, the previous fit is reused; without one, a RiskMetrics EWMA (lambda 0.94, nu 8) is used.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import asdict, dataclass

import numpy as np
from arch import arch_model

SCALE = 100.0
EWMA_LAMBDA = 0.94
EWMA_NU = 8.0


@dataclass(frozen=True)
class GarchFit:
    """Parameters in scaled (percent^2) units."""

    omega: float
    alpha: float
    beta: float
    nu: float
    method: str  # "arch" | "previous" | "ewma"
    n_obs: int

    @property
    def persistence(self) -> float:
        return self.alpha + self.beta

    def to_json(self) -> dict[str, float | str | int]:
        return {k: (round(v, 10) if isinstance(v, float) else v) for k, v in asdict(self).items()}


@dataclass(frozen=True)
class GarchState:
    """sigma2 is the conditional variance (scaled units) of returns[index]."""

    fit: GarchFit
    index: int
    sigma2: float


def _filter(fit: GarchFit, scaled: np.ndarray, sigma2_0: float) -> float:
    """Run the variance recursion over `scaled` and return sigma2 of its last element."""
    s2 = sigma2_0
    for k in range(1, len(scaled)):
        s2 = fit.omega + fit.alpha * scaled[k - 1] ** 2 + fit.beta * s2
    return s2


def _backcast(scaled: np.ndarray) -> float:
    head = scaled[: min(75, len(scaled))]
    return float(np.mean(head**2)) if len(head) else 0.0


def fit_garch(returns: np.ndarray, end_index: int, previous: GarchFit | None = None) -> GarchState:
    """Fit on `returns` (log-return units, no NaN) whose last element sits at end_index."""
    scaled = np.asarray(returns, dtype="float64") * SCALE
    n = len(scaled)
    fit: GarchFit | None = None
    sigma2: float | None = None
    if n >= 10 and float(np.var(scaled)) > 0:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                am = arch_model(scaled, mean="Zero", vol="GARCH", p=1, q=1, dist="t", rescale=False)
                res = am.fit(disp="off", show_warning=False)
            p = res.params
            cand = GarchFit(
                omega=float(p["omega"]),
                alpha=float(p["alpha[1]"]),
                beta=float(p["beta[1]"]),
                nu=float(p["nu"]),
                method="arch",
                n_obs=n,
            )
            last_vol = float(np.asarray(res.conditional_volatility)[-1])
            ok = (
                res.convergence_flag == 0
                and all(math.isfinite(v) for v in (cand.omega, cand.alpha, cand.beta, cand.nu))
                and cand.omega > 0
                and cand.nu > 2.0
                and math.isfinite(last_vol)
            )
            if ok:
                fit, sigma2 = cand, last_vol**2
        except Exception:
            fit = None
    if fit is None:
        if previous is not None:
            fit = GarchFit(
                previous.omega, previous.alpha, previous.beta, previous.nu, "previous", n
            )
        else:
            fit = GarchFit(0.0, 1.0 - EWMA_LAMBDA, EWMA_LAMBDA, EWMA_NU, "ewma", n)
        sigma2 = _filter(fit, scaled, _backcast(scaled))
    assert sigma2 is not None
    return GarchState(fit=fit, index=end_index, sigma2=float(sigma2))


def advance(state: GarchState, returns: np.ndarray, to_index: int) -> GarchState:
    """Filter forward with fixed parameters to `to_index` (uses returns up to to_index - 1)."""
    if to_index < state.index:
        raise ValueError("cannot filter backwards")
    f = state.fit
    s2 = state.sigma2
    for k in range(state.index + 1, to_index + 1):
        s2 = f.omega + f.alpha * (returns[k - 1] * SCALE) ** 2 + f.beta * s2
    return GarchState(fit=f, index=to_index, sigma2=s2)


def daily_variance_path(state: GarchState, returns: np.ndarray, steps: int) -> np.ndarray:
    """Variance forecasts (log-return units) of the next `steps` daily returns after state.index."""
    f = state.fit
    out = np.empty(steps)
    s2 = f.omega + f.alpha * (returns[state.index] * SCALE) ** 2 + f.beta * state.sigma2
    out[0] = s2
    for k in range(1, steps):
        s2 = f.omega + f.persistence * s2
        out[k] = s2
    return out / SCALE**2


def horizon_variance(daily_path: np.ndarray, horizon_days: int) -> float:
    """Sum of the h daily variance forecasts."""
    return float(np.sum(daily_path[:horizon_days]))


def annualised_vol(daily_path: np.ndarray, trading_days: int = 252) -> float:
    """Annualised one-step conditional volatility."""
    return float(math.sqrt(daily_path[0] * trading_days))

"""Backtest metrics (spec: Evaluation and backtesting). Pure numpy, no DB access.

Units: MAE and pinball are in rate units (|center - realised rate|), so they read like the
forecast itself; ratios and coverages are unit-free.

Diebold-Mariano: d_t = |e_model,t| - |e_rw,t|. The long-run variance uses autocovariances up
to lag h - 1 (rectangular kernel; Bartlett weights if that is not positive), the statistic gets
the Harvey-Leybourne-Newbold small-sample correction and is compared with t(n - 1). One-sided:
H1 is that the model's expected absolute error is lower than the random walk's.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

MIN_DM_OBS = 10


def pinball(y: np.ndarray, q: np.ndarray, p: float | np.ndarray) -> np.ndarray:
    """Pinball (quantile) loss of quantile forecast q at level p for outcome y."""
    diff = np.asarray(y, dtype="float64") - np.asarray(q, dtype="float64")
    p = np.asarray(p, dtype="float64")
    return np.maximum(p * diff, (p - 1.0) * diff)


def mean_pinball(y: np.ndarray, qmat: np.ndarray, probs: np.ndarray) -> float:
    """Average pinball loss over observations (rows of qmat) and quantile levels (columns)."""
    y = np.asarray(y, dtype="float64")[:, None]
    return float(np.mean(pinball(y, qmat, np.asarray(probs)[None, :])))


def coverage(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    y = np.asarray(y, dtype="float64")
    return float(np.mean((y >= lo) & (y <= hi)))


def mae(err: np.ndarray) -> float:
    return float(np.mean(np.abs(err)))


def hit_rate(mu: np.ndarray, realised_ret: np.ndarray) -> float | None:
    """Share of correct signs, ignoring flat outcomes and zero predictions."""
    mu = np.asarray(mu, dtype="float64")
    y = np.asarray(realised_ret, dtype="float64")
    ok = (mu != 0) & (y != 0) & np.isfinite(mu) & np.isfinite(y)
    if not ok.any():
        return None
    return float(np.mean(np.sign(mu[ok]) == np.sign(y[ok])))


def _autocov(d: np.ndarray, k: int) -> float:
    n = len(d)
    dc = d - d.mean()
    return float(np.dot(dc[k:], dc[: n - k]) / n)


def dm_test(loss_model: np.ndarray, loss_ref: np.ndarray, h: int) -> float | None:
    """One-sided DM p-value (H1: model loss < reference loss), HAC with h-1 lags, HLN-corrected."""
    d = np.asarray(loss_model, dtype="float64") - np.asarray(loss_ref, dtype="float64")
    d = d[np.isfinite(d)]
    n = len(d)
    if n < max(MIN_DM_OBS, 2 * h + 1):
        return None
    gammas = [_autocov(d, k) for k in range(h)]
    v = gammas[0] + 2.0 * sum(gammas[1:])
    if v <= 0:
        v = gammas[0] + 2.0 * sum((1.0 - k / h) * g for k, g in enumerate(gammas[1:], start=1))
    if not v > 0:
        return None
    dm = d.mean() / math.sqrt(v / n)
    hln = math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    return float(stats.t.cdf(hln * dm, df=n - 1))

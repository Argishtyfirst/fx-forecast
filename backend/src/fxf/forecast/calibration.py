"""Walk-forward band calibration: the last step of the band model.

    sigma_pre = empirical_check(sqrt(GARCH horizon variance + event extra variance))   (1M check)
    band L    = mu +- c_L * t_unit(0.5 + L/2, nu_h) * sigma_pre,   L in {50, 80, 95}

For an origin t and horizon h, take the trailing params.CAL_WINDOW origins s whose outcome was
realised by t (s + h <= t in trading days of the pair) and their standardized absolute errors
around the random-walk center:

    u_{s,L} = |log(S_{s+h} / S_s)| / (t_unit(0.5 + L/2, nu_h,s) * sigma_pre,s)

c_L is the L-quantile of u_{s,L}: the factor that would have put a share L of those outcomes
inside the band. With params.CAL_PER_LEVEL False the 80% factor is used for every level (a
single scale on sigma). Factors are clamped to params.CAL_CLAMP, and c = 1 with fewer than
params.CAL_MIN_OBS completed origins.

The random-walk center is used because every center candidate shares one band model (the same
sigma) and the served fallback is the random walk; FX centers move mu by a small fraction of
sigma, so the factor carries over. Calibration multiplies the band after event widening, so a
wider pre-calibration band stays wider for the same factors: widening never narrows a band.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fxf.forecast import bands, params


@dataclass
class Calibration:
    factors: np.ndarray  # (n, 3) for the 50/80/95 bands
    n_obs: np.ndarray  # completed origins used per target origin
    outcomes_through: np.ndarray  # index of the latest outcome used (-1 if none)


def standardized_errors(
    log_rates: np.ndarray, origins: np.ndarray, sigma_pre: np.ndarray, nu_h: np.ndarray, h: int
) -> np.ndarray:
    """u (n, 3): |h-day log return| over each band's pre-calibration half-width, per origin.

    NaN where the outcome lies beyond the data (s + h past the last rate)."""
    origins = np.asarray(origins, dtype=int)
    n = len(log_rates)
    r = np.full(len(origins), np.nan)
    ok = origins + h <= n - 1
    r[ok] = np.abs(log_rates[origins[ok] + h] - log_rates[origins[ok]])
    half = np.array(
        [
            [
                bands.t_unit_quantile(0.5 + bands.BAND_LEVELS[lv] / 2.0, float(v))
                for lv in bands.CAL_LEVELS
            ]
            for v in nu_h
        ]
    ).reshape(len(origins), len(bands.CAL_LEVELS))
    return r[:, None] / (half * np.asarray(sigma_pre, dtype="float64")[:, None])


def calibrate(
    log_rates: np.ndarray,
    hist_origins: np.ndarray,
    hist_sigma_pre: np.ndarray,
    hist_nu_h: np.ndarray,
    targets: np.ndarray,
    h: int,
    *,
    window: int = params.CAL_WINDOW,
    min_obs: int = params.CAL_MIN_OBS,
    clamp: tuple[float, float] = params.CAL_CLAMP,
    per_level: bool = params.CAL_PER_LEVEL,
) -> Calibration:
    """Factors for each target origin t from history origins s with t - h - window < s <= t - h.

    hist_origins must be increasing. Only outcomes at index s + h <= t are read, so the
    factors use nothing after t."""
    hist_origins = np.asarray(hist_origins, dtype=int)
    targets = np.asarray(targets, dtype=int)
    u = standardized_errors(log_rates, hist_origins, hist_sigma_pre, hist_nu_h, h)
    levels = np.array([bands.BAND_LEVELS[lv] for lv in bands.CAL_LEVELS])
    k80 = bands.CAL_LEVELS.index("80")
    out = np.ones((len(targets), len(levels)))
    n_used = np.zeros(len(targets), dtype=int)
    through = np.full(len(targets), -1, dtype=int)
    for j, t in enumerate(targets):
        a = int(np.searchsorted(hist_origins, t - h - window + 1, "left"))
        b = int(np.searchsorted(hist_origins, t - h, "right"))
        uu = u[a:b]
        uu = uu[np.isfinite(uu[:, 0])]
        n_used[j] = len(uu)
        if b > a:
            through[j] = int(hist_origins[b - 1]) + h
        if len(uu) < min_obs:
            continue
        c = np.array([np.quantile(uu[:, k], levels[k]) for k in range(len(levels))])
        if not per_level:
            c = np.full(len(levels), c[k80])
        out[j] = np.clip(c, clamp[0], clamp[1])
    return Calibration(factors=out, n_obs=n_used, outcomes_through=through)

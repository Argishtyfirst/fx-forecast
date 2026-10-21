"""Unit tests for the walk-forward band calibration (fxf.forecast.calibration)."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from fxf.forecast import bands
from fxf.forecast.calibration import calibrate, standardized_errors

NU = 8.0


def _series(n: int, true_sigma: float, h: int, seed: int = 0) -> np.ndarray:
    """Log rates whose h-day returns are unit-variance t(NU) * true_sigma (non-overlapping draws
    are not needed: the factor only reads the marginal distribution)."""
    rng = np.random.default_rng(seed)
    daily = (
        stats.t.rvs(NU, size=n, random_state=rng) * np.sqrt((NU - 2) / NU) * true_sigma / np.sqrt(h)
    )
    return np.concatenate([[0.0], np.cumsum(daily)])[:n]


def test_factor_is_one_for_a_calibrated_band():
    h, n = 1, 3000
    lr = _series(n, 0.01, h)
    o = np.arange(n - 1)
    cal = calibrate(
        lr,
        o,
        np.full(len(o), 0.01),
        np.full(len(o), NU),
        np.array([n - 2]),
        h,
        window=2500,
        min_obs=60,
        clamp=(0.5, 1.5),
        per_level=True,
    )
    np.testing.assert_allclose(cal.factors[0], 1.0, atol=0.07)


def test_factor_shrinks_a_band_twice_too_wide_and_widens_one_too_narrow():
    h, n = 1, 3000
    lr = _series(n, 0.01, h, seed=1)
    o = np.arange(n - 1)
    nu = np.full(len(o), NU)
    wide = calibrate(
        lr,
        o,
        np.full(len(o), 0.02),
        nu,
        np.array([n - 2]),
        h,
        window=2500,
        min_obs=60,
        clamp=(0.2, 5.0),
        per_level=True,
    )
    narrow = calibrate(
        lr,
        o,
        np.full(len(o), 0.008),
        nu,
        np.array([n - 2]),
        h,
        window=2500,
        min_obs=60,
        clamp=(0.2, 5.0),
        per_level=True,
    )
    np.testing.assert_allclose(wide.factors[0], 0.5, atol=0.05)
    np.testing.assert_allclose(narrow.factors[0], 1.25, atol=0.1)


def test_calibrated_band_covers_its_level_in_sample():
    h, n = 5, 1200
    lr = _series(n, 0.02, h, seed=2)
    o = np.arange(n - h)
    sig = np.full(len(o), 0.03)  # too wide
    nu = np.full(len(o), 30.0)
    t = int(o[-1]) + h
    cal = calibrate(
        lr,
        o,
        sig,
        nu,
        np.array([t]),
        h,
        window=10_000,
        min_obs=60,
        clamp=(0.2, 5.0),
        per_level=True,
    )
    z = bands.calibrated_z(
        np.vstack([bands.z_values(30.0)] * len(o)), np.repeat(cal.factors, len(o), axis=0)
    )
    y = lr[o + h] - lr[o]
    q = z * sig[:, None]
    assert np.mean((y >= q[:, 1]) & (y <= q[:, 4])) == pytest.approx(0.80, abs=0.01)
    assert np.mean((y >= q[:, 2]) & (y <= q[:, 3])) == pytest.approx(0.50, abs=0.01)
    assert np.mean((y >= q[:, 0]) & (y <= q[:, 5])) == pytest.approx(0.95, abs=0.01)


def test_uses_only_outcomes_realised_by_the_origin():
    h, n = 5, 800
    lr = _series(n, 0.02, h, seed=3)
    o = np.arange(n - 1)
    sig = np.full(len(o), 0.02)
    nu = np.full(len(o), NU)
    t = 600
    a = calibrate(
        lr, o, sig, nu, np.array([t]), h, window=250, min_obs=60, clamp=(0.5, 1.5), per_level=True
    )
    lr2 = lr.copy()
    lr2[t + 1 :] += np.linspace(0, 3, n - t - 1)  # rewrite everything after t
    b = calibrate(
        lr2, o, sig, nu, np.array([t]), h, window=250, min_obs=60, clamp=(0.5, 1.5), per_level=True
    )
    np.testing.assert_array_equal(a.factors, b.factors)
    assert a.outcomes_through[0] == t  # the last outcome read is S_t itself (origin t - h)
    assert a.n_obs[0] == 250


def test_too_few_outcomes_gives_factor_one_and_clamp_applies():
    h, n = 1, 300
    lr = _series(n, 0.01, h, seed=4)
    o = np.arange(n - 1)
    nu = np.full(len(o), NU)
    few = calibrate(
        lr,
        o,
        np.full(len(o), 0.01),
        nu,
        np.array([40]),
        h,
        window=250,
        min_obs=60,
        clamp=(0.5, 1.5),
        per_level=True,
    )
    np.testing.assert_array_equal(few.factors[0], 1.0)
    assert few.n_obs[0] == 40
    huge = calibrate(
        lr,
        o,
        np.full(len(o), 1.0),
        nu,
        np.array([n - 2]),
        h,
        window=250,
        min_obs=60,
        clamp=(0.5, 1.5),
        per_level=True,
    )
    np.testing.assert_array_equal(huge.factors[0], 0.5)


def test_single_factor_mode_uses_the_80_factor_everywhere():
    h, n = 1, 2000
    lr = _series(n, 0.01, h, seed=5)
    o = np.arange(n - 1)
    cal = calibrate(
        lr,
        o,
        np.full(len(o), 0.015),
        np.full(len(o), 4.5),
        np.array([n - 2]),
        h,
        window=1500,
        min_obs=60,
        clamp=(0.2, 5.0),
        per_level=False,
    )
    assert cal.factors[0, 0] == cal.factors[0, 1] == cal.factors[0, 2]


def test_standardized_errors_divide_by_each_bands_half_width():
    lr = np.log(np.array([1.0, 1.1, 1.0, 1.05]))
    u = standardized_errors(
        lr, np.array([0, 1, 3]), np.array([0.1, 0.1, 0.1]), np.array([NU, NU, NU]), 1
    )
    half80 = bands.t_unit_quantile(0.9, NU) * 0.1
    assert u[0, 1] == pytest.approx(abs(np.log(1.1)) / half80)
    assert np.isnan(u[2]).all()  # outcome beyond the data


def test_calibrated_z_keeps_quantiles_ordered_and_symmetric():
    z = bands.z_values(6.0)
    zc = bands.calibrated_z(z, np.array([1.5, 0.5, 0.5]))  # would cross without the guard
    assert np.all(np.diff(zc) > 0)
    np.testing.assert_allclose(zc, -zc[::-1])
    np.testing.assert_allclose(bands.calibrated_z(z, None), z)

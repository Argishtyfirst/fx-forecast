"""Property tests (spec: Test plan / Property): quantiles ascending, widening never narrows a
band, the center sits inside the 50% band. Every property holds for any walk-forward
calibration factors in the clamp range (params.CAL_CLAMP)."""

from __future__ import annotations

import math

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from fxf.constants import BANDS, HORIZONS
from fxf.forecast import bands, params
from fxf.forecast.widening import extra_variance, meeting_steps

spots = st.floats(min_value=0.01, max_value=5000.0)
mus = st.floats(min_value=-0.2, max_value=0.2)
sigmas = st.floats(min_value=1e-5, max_value=0.4)
nus = st.floats(min_value=2.05, max_value=150.0)
horizons = st.sampled_from(HORIZONS)
factor = st.floats(min_value=params.CAL_CLAMP[0], max_value=params.CAL_CLAMP[1])
cals = st.none() | st.tuples(factor, factor, factor).map(np.array)


def _band(
    spot: float, mu: float, sigma: float, nu: float, h: int, cal=None
) -> tuple[float, dict[str, float]]:
    return bands.to_rates(spot, mu, bands.floor_sigma(sigma, h), bands.horizon_nu(nu, h), cal)


@settings(max_examples=400, deadline=None)
@given(spots, mus, sigmas, nus, horizons, cals)
def test_quantiles_ascending(spot, mu, sigma, nu, h, cal):
    _, q = _band(spot, mu, sigma, nu, h, cal)
    vals = [q[c] for c in bands.QUANTILE_NAMES]
    assert all(a < b for a, b in zip(vals, vals[1:], strict=False))


@settings(max_examples=400, deadline=None)
@given(st.floats(min_value=0.5, max_value=5000.0), mus, sigmas, nus, horizons, cals)
def test_quantiles_ascending_after_numeric_rounding(spot, mu, sigma, nu, h, cal):
    """Still strictly ordered in NUMERIC(18,8) for real spot levels (EUR/USD ~1, AMD ~400)."""
    _, q = _band(spot, mu, sigma, nu, h, cal)
    r = [round(q[c], 8) for c in bands.QUANTILE_NAMES]
    assert all(a < b for a, b in zip(r, r[1:], strict=False))


@settings(max_examples=400, deadline=None)
@given(spots, mus, sigmas, nus, horizons, cals)
def test_center_inside_50_band(spot, mu, sigma, nu, h, cal):
    center, q = _band(spot, mu, sigma, nu, h, cal)
    assert q["q25"] < center < q["q75"]


@settings(max_examples=300, deadline=None)
@given(
    spot=spots,
    mu=mus,
    nu=nus,
    h=horizons,
    daily=st.lists(st.floats(min_value=1e-10, max_value=1e-3), min_size=21, max_size=21),
    meetings=st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=30),
            st.floats(min_value=0.0, max_value=20.0) | st.none(),
        ),
        max_size=4,
    ),
    cal=cals,
)
def test_widening_never_narrows_a_band(spot, mu, nu, h, daily, meetings, cal):
    path = np.array(daily)
    day = np.timedelta64(1, "D")
    horizon_dates = np.arange(np.datetime64("2026-01-02"), np.datetime64("2026-01-02") + h * day)
    m_dates = [np.datetime64("2026-01-01") + int(off) * day for off, _ in meetings]
    steps = meeting_steps(m_dates, horizon_dates) if meetings else []
    assert all(1 <= s <= h for s in steps)
    extra = extra_variance(path, steps, [r for _, r in meetings])
    assert extra >= 0.0
    gv = float(path[:h].sum())
    nu_h = bands.horizon_nu(nu, h)
    # the same calibration factors with and without the meetings
    _, base = bands.to_rates(spot, mu, bands.floor_sigma(math.sqrt(gv), h), nu_h, cal)
    _, wide = bands.to_rates(spot, mu, bands.floor_sigma(math.sqrt(gv + extra), h), nu_h, cal)
    for lo, hi in BANDS.values():
        assert wide[lo] <= base[lo] + 1e-12 * spot
        assert wide[hi] >= base[hi] - 1e-12 * spot


@settings(max_examples=200, deadline=None)
@given(sigma=sigmas, nu=nus, emp=st.floats(min_value=0.0, max_value=2.0) | st.none())
def test_empirical_check_never_narrows(sigma, nu, emp):
    nu_h = bands.horizon_nu(nu, 21)
    new, info = bands.empirical_check(sigma, nu_h, emp)
    assert new >= sigma
    assert info["applied"] == (new > sigma)

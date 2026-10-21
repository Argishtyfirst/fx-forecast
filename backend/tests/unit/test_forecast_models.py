"""Unit tests for the pure forecast model code (forward, GARCH, bands, widening, selection)."""

from __future__ import annotations

import datetime as dt
import math
import warnings

import numpy as np
import pytest
from arch import arch_model
from scipy import stats

from fxf.constants import MODEL_FORWARD, MODEL_LGBM, MODEL_RW
from fxf.forecast import bands, garch
from fxf.forecast.forward import forward_log_return, forward_rate, year_fraction
from fxf.forecast.selection import MetricSummary, select_from_metrics
from fxf.forecast.widening import (
    EventRatios,
    extra_variance,
    impact_indices,
    meeting_steps,
    variance_ratio,
)

# --- forward rate (CIP) ------------------------------------------------------------------


def test_forward_rate_formula_eurusd():
    # S = 1.16, ECB 2.00%, Fed mid 4.375%, 21 trading days: tau = 21/252 = 1/12
    f = forward_rate(1.16, 2.0, 4.375, 21)
    assert f == pytest.approx(1.16 * (1 + 0.04375 / 12) / (1 + 0.02 / 12), rel=1e-12)
    assert f > 1.16  # the higher-yielding quote currency trades at a forward discount
    assert year_fraction(5) == pytest.approx(5 / 252)


def test_forward_rate_usdamd_and_log_return():
    s, i_fed, i_cba = 387.5, 4.375, 6.75
    f = forward_rate(s, i_fed, i_cba, 5)
    assert f == pytest.approx(s * (1 + 0.0675 * 5 / 252) / (1 + 0.04375 * 5 / 252), rel=1e-12)
    assert math.log(f / s) == pytest.approx(forward_log_return(i_fed, i_cba, 5), rel=1e-12)


def test_forward_equal_rates_is_spot_and_missing_rate_is_nan():
    assert forward_rate(1.1, 3.0, 3.0, 21) == pytest.approx(1.1)
    assert math.isnan(float(forward_log_return(np.nan, 3.0, 5)))
    arr = forward_log_return(np.array([1.0, 2.0]), np.array([2.0, 2.0]), 21)
    assert arr[1] == 0.0 and arr[0] > 0


# --- GARCH ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sim_returns() -> np.ndarray:
    rng = np.random.default_rng(3)
    n = 1500
    out = np.empty(n)
    s2, e = 0.25e-4, 0.0
    for k in range(n):
        s2 = 0.02e-4 * 0.25 + 0.07 * e**2 + 0.9 * s2
        e = math.sqrt(s2) * rng.standard_t(6) / math.sqrt(1.5)
        out[k] = e
    return out


def test_horizon_variance_is_sum_of_daily_forecasts(sim_returns):
    st = garch.fit_garch(sim_returns, len(sim_returns) - 1)
    path = garch.daily_variance_path(st, sim_returns, 21)
    for h in (1, 5, 21):
        assert garch.horizon_variance(path, h) == pytest.approx(path[:h].sum())
    f = st.fit
    # recursion: one step from the last return, then omega + (alpha + beta) * previous
    s1 = (f.omega + f.alpha * (sim_returns[-1] * 100) ** 2 + f.beta * st.sigma2) / 1e4
    assert path[0] == pytest.approx(s1)
    assert path[1] == pytest.approx((f.omega + f.persistence * path[0] * 1e4) / 1e4)


def test_daily_path_matches_arch_forecast(sim_returns):
    st = garch.fit_garch(sim_returns, len(sim_returns) - 1)
    assert st.fit.method == "arch" and st.fit.nu > 2
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = arch_model(
            sim_returns * 100, mean="Zero", vol="GARCH", p=1, q=1, dist="t", rescale=False
        ).fit(disp="off")
    ref = res.forecast(horizon=21, reindex=False).variance.to_numpy()[0] / 1e4
    np.testing.assert_allclose(garch.daily_variance_path(st, sim_returns, 21), ref, rtol=1e-6)


def test_advance_equals_arch_filter_with_fixed_params(sim_returns):
    t = 1200
    st = garch.fit_garch(sim_returns[: t + 1], t)
    f = st.fit
    fixed = arch_model(
        sim_returns[: t + 60] * 100, mean="Zero", vol="GARCH", p=1, q=1, dist="t", rescale=False
    ).fix([f.omega, f.alpha, f.beta, f.nu])
    cv = np.asarray(fixed.conditional_volatility) ** 2
    later = garch.advance(st, sim_returns, t + 40)
    assert later.sigma2 == pytest.approx(cv[t + 40], rel=1e-8)
    with pytest.raises(ValueError):
        garch.advance(later, sim_returns, t)


def test_garch_fallback_on_flat_series():
    st = garch.fit_garch(np.zeros(600), 599)
    assert st.fit.method == "ewma"
    path = garch.daily_variance_path(st, np.zeros(600), 5)
    assert np.all(path >= 0)


# --- bands --------------------------------------------------------------------------------


def test_student_t_unit_variance_quantile():
    nu = 5.0
    assert bands.t_unit_quantile(0.9, nu) == pytest.approx(stats.t.ppf(0.9, nu) * math.sqrt(3 / 5))
    assert bands.t_unit_quantile(0.975, 1e6) == pytest.approx(1.959964, abs=1e-4)
    # a unit-variance t has variance 1
    z = stats.t.rvs(nu, size=400_000, random_state=1) * math.sqrt((nu - 2) / nu)
    assert np.var(z) == pytest.approx(1.0, abs=0.03)


def test_horizon_nu_matches_kurtosis_of_the_sum():
    assert bands.horizon_nu(6.0, 1) == 6.0
    assert bands.horizon_nu(6.0, 5) == pytest.approx(4 + 2 * 5)
    assert bands.horizon_nu(3.0, 21) == pytest.approx(4 + bands.NU_EXCESS_FLOOR * 21)
    assert bands.horizon_nu(50.0, 21) == bands.NU_MAX
    nu, h = 8.0, 5
    assert 6 / (bands.horizon_nu(nu, h) - 4) == pytest.approx(6 / (nu - 4) / h)


def test_to_rates_orders_quantiles_around_center():
    center, q = bands.to_rates(1.16, 0.001, 0.01, 7.0)
    assert center == pytest.approx(1.16 * math.exp(0.001))
    vals = [q[c] for c in bands.QUANTILE_NAMES]
    assert vals == sorted(vals)
    assert q["q25"] < center < q["q75"]
    # the 80% band in log space is 2 * t_unit(0.9) * sigma wide
    assert math.log(q["q90"] / q["q10"]) == pytest.approx(bands.band_width(0.01, 7.0, "80"))


def test_empirical_check_widens_only():
    sig, info = bands.empirical_check(0.01, 20.0, 0.05, 240)
    assert info["applied"] and sig > 0.01
    assert bands.band_width(sig, 20.0, "80") == pytest.approx(0.05)
    sig2, info2 = bands.empirical_check(0.01, 20.0, 0.001, 240)
    assert sig2 == 0.01 and not info2["applied"]
    sig3, info3 = bands.empirical_check(0.01, 20.0, None)
    assert sig3 == 0.01 and info3["empirical_width_80"] is None


def test_empirical_widths_use_only_past_returns():
    lr = np.log(np.linspace(1.0, 2.0, 400))
    w, n = bands.empirical_widths(lr, 21, lookback=252, min_obs=200)
    assert np.isnan(w[:220]).all() and np.isfinite(w[300])
    lr2 = lr.copy()
    lr2[301:] += 5.0  # a later shock must not change the width at index 300
    w2, _ = bands.empirical_widths(lr2, 21, lookback=252, min_obs=200)
    assert w2[300] == w[300]
    assert n[300] == 252


# --- event widening -------------------------------------------------------------------------


def test_widening_ratio_known_case():
    r = np.array([np.nan, 1, -1, 2, 1, -1, -2, 1, -1, 1], dtype=float)
    ev = np.zeros(10, dtype=bool)
    ev[[3, 6]] = True
    assert variance_ratio(r, ev, ~ev) == pytest.approx(4.0)
    est = EventRatios(r, {"ECB": np.array([3, 6])}, np.array([3, 6]), min_meetings=2, min_normal=5)
    assert est.ratio("ECB", 1, 9) == pytest.approx(4.0)
    st = est.stats("ECB", 1, 9)
    # the window starts at the first impact day (index 3): days 1-2 precede the calendar
    assert st["n_meetings"] == 2 and st["n_normal"] == 5
    assert est.ratio("ECB", 1, 5) is None  # only one meeting in the window
    assert est.ratio("FED", 1, 9) is None


def test_extra_variance_formula_and_never_negative():
    path = np.array([1.0, 2.0, 3.0])
    assert extra_variance(path, [2], [4.0]) == pytest.approx(3 * 2.0)
    assert extra_variance(path, [1, 3], [2.0, 1.5]) == pytest.approx(1.0 + 0.5 * 3)
    assert extra_variance(path, [2], [0.5]) == 0.0  # ratio < 1 never narrows
    assert extra_variance(path, [2], [None]) == 0.0


def test_impact_day_is_next_trading_day_and_steps():
    trading = np.array(
        ["2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26"], dtype="datetime64[D]"
    )
    meetings = np.array(["2026-10-21", "2026-10-23", "2026-10-24"], dtype="datetime64[D]")
    assert impact_indices(meetings, trading).tolist() == [1, 3, 3]
    horizon = trading[1:]  # spot 2026-10-21, h = 3
    # meeting on the spot date -> step 1; Friday meeting -> Monday (step 3);
    # a meeting on the target date maps to the last step
    assert meeting_steps(list(meetings), horizon) == [1, 3, 3]
    assert meeting_steps([np.datetime64("2026-10-26")], horizon) == [3]


# --- selection (FR-11) --------------------------------------------------------------------


def test_selection_promotes_lowest_mae_model_meeting_the_rule():
    m = [
        MetricSummary(MODEL_RW, 1.0, 1.0, None),
        MetricSummary(MODEL_FORWARD, 0.95, 0.95, 0.05),
        MetricSummary(MODEL_LGBM, 0.90, 0.90, 0.20),  # lower MAE but DM p fails
    ]
    model, reason = select_from_metrics(m, 21)
    assert model == MODEL_FORWARD and "MAE ratio 0.950" in reason


def test_selection_falls_back_to_random_walk():
    m = [MetricSummary(MODEL_FORWARD, 0.995, 0.995, 0.41), MetricSummary(MODEL_LGBM, 1.1, 1.1, 0.9)]
    assert select_from_metrics(m, 21) == (
        MODEL_RW,
        "no model beats the random walk (best: forward, MAE ratio 0.995, DM p 0.41)",
    )
    model, reason = select_from_metrics([], 5)
    assert model == MODEL_RW and "no backtest metrics" in reason
    # forward is not a 1D candidate
    assert select_from_metrics([MetricSummary(MODEL_FORWARD, 0.5, 0.5, 0.01)], 1)[0] == MODEL_RW


def test_selection_rule_boundaries_are_strict():
    at_limit = [MetricSummary(MODEL_LGBM, 0.98, 0.98, 0.01)]
    assert select_from_metrics(at_limit, 5)[0] == MODEL_RW
    p_limit = [MetricSummary(MODEL_LGBM, 0.9, 0.9, 0.10)]
    assert select_from_metrics(p_limit, 5)[0] == MODEL_RW


def test_year_fraction_convention_documented():
    from fxf.forecast import forward

    assert "h / 252" in forward.__doc__
    assert dt.date(2026, 1, 1)  # module imports cleanly

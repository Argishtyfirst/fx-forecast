"""Unit tests for the backtest metrics (pinball, coverage, hit rate, Diebold-Mariano)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from fxf.backtest import metrics as M
from fxf.backtest.runner import coverage_alerts
from fxf.constants import MODEL_FORWARD, MODEL_RW, WINDOW_RECENT


def test_pinball_known_values():
    # y above the quantile: p * (y - q); below: (1 - p) * (q - y)
    assert M.pinball(np.array([1.0]), np.array([0.0]), 0.9)[0] == pytest.approx(0.9)
    assert M.pinball(np.array([0.0]), np.array([1.0]), 0.9)[0] == pytest.approx(0.1)
    assert M.pinball(np.array([2.0]), np.array([2.0]), 0.25)[0] == 0.0
    y = np.array([1.0, 2.0])
    q = np.array([[0.0, 3.0], [2.0, 2.0]])
    probs = np.array([0.1, 0.9])
    # row 1: 0.1*1, 0.1*2 ; row 2: 0, 0
    assert M.mean_pinball(y, q, probs) == pytest.approx((0.1 + 0.2) / 4)


def test_coverage_and_mae():
    y = np.array([1.0, 2.0, 3.0, 4.0])
    assert M.coverage(y, np.full(4, 1.5), np.full(4, 3.0)) == pytest.approx(0.5)
    assert M.coverage(y, y, y) == 1.0  # bounds are inclusive
    assert M.mae(np.array([-1.0, 2.0])) == pytest.approx(1.5)


def test_hit_rate_ignores_flat_and_zero_predictions():
    mu = np.array([0.1, -0.2, 0.3, 0.0, 0.1])
    y = np.array([0.5, 0.4, -0.1, 0.2, 0.0])
    assert M.hit_rate(mu, y) == pytest.approx(1 / 3)
    assert M.hit_rate(np.zeros(3), np.ones(3)) is None


def test_dm_h1_equals_one_sided_t_test():
    rng = np.random.default_rng(5)
    a = np.abs(rng.normal(0, 1.0, 300))
    b = np.abs(rng.normal(0, 1.1, 300))
    p = M.dm_test(a, b, 1)
    ref = stats.ttest_1samp(a - b, 0.0, alternative="less").pvalue
    assert p == pytest.approx(ref, rel=1e-10)


def test_dm_hac_and_hln_known_case():
    d_model = np.array([1.0, 0.5, 2.0, 1.5, 0.2, 0.8, 1.1, 0.4, 0.9, 1.3, 0.7, 0.6])
    d_ref = np.ones(12)
    h = 3
    d = d_model - d_ref
    n = len(d)
    dc = d - d.mean()
    g = [np.dot(dc[k:], dc[: n - k]) / n for k in range(h)]
    v = g[0] + 2 * (g[1] + g[2])
    if v <= 0:
        v = g[0] + 2 * sum((1 - k / h) * g[k] for k in range(1, h))
    dm = d.mean() / math.sqrt(v / n)
    hln = math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    assert M.dm_test(d_model, d_ref, h) == pytest.approx(stats.t.cdf(hln * dm, n - 1))


def test_dm_direction_and_degenerate_cases():
    rng = np.random.default_rng(1)
    ref = np.abs(rng.normal(0, 1, 500))
    better = ref * 0.8
    worse = ref * 1.2
    assert M.dm_test(better, ref, 5) < 0.01
    assert M.dm_test(worse, ref, 5) > 0.99
    assert M.dm_test(ref, ref, 5) is None  # identical losses: no variance
    assert M.dm_test(ref[:5], ref[:5] * 0.9, 1) is None  # too few observations


def _row(
    model: str,
    h: int,
    cov80: float,
    mae: float,
    ratio: float,
    p: float | None,
    pair: str = "USDAMD",
) -> dict:
    return {
        "pair": pair,
        "horizon_days": h,
        "window": WINDOW_RECENT,
        "model": model,
        "mae": mae,
        "mae_ratio_rw": ratio,
        "dm_pvalue": p,
        "cov80": cov80,
        "n_obs": 250,
    }


def test_usdamd_coverage_alert_below_70_percent():
    rows = [
        _row(MODEL_RW, 5, 0.65, 1.0, 1.0, None),
        _row(MODEL_FORWARD, 5, 0.66, 1.0, 1.0, 0.5),
        _row(MODEL_RW, 21, 0.78, 1.0, 1.0, None),
    ]
    alerts = coverage_alerts(rows)
    assert len(alerts) == 1 and "USDAMD 5d" in alerts[0] and "65.0%" in alerts[0]
    assert coverage_alerts([_row(MODEL_RW, 1, 0.75, 1.0, 1.0, None)]) == []


def test_coverage_alert_applies_to_every_amd_pair_only():
    rows = [
        _row(MODEL_RW, 21, 0.60, 1.0, 1.0, None, pair="EURAMD"),
        _row(MODEL_RW, 21, 0.50, 1.0, 1.0, None, pair="EURUSD"),
    ]
    alerts = coverage_alerts(rows)
    assert len(alerts) == 1 and alerts[0].startswith("EURAMD 21d")

"""FR-17: the "sell now?" indicator is a calibrated summary, and only leans with evidence."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fxf.api.signal import build_signal, prob_above
from fxf.constants import EURAMD
from fxf.models import BacktestMetric, Forecast

QS = {0.025: 400.0, 0.10: 402.0, 0.25: 404.0, 0.50: 406.0, 0.75: 408.0, 0.90: 410.0, 0.975: 412.0}


def forecast(center: float, spot: float = 406.0, model: str = "lightgbm", h: int = 21) -> Forecast:
    shift = center - 406.0
    q = {k: Decimal(str(v + shift)) for k, v in QS.items()}
    return Forecast(
        run_date=dt.date(2026, 10, 21),
        pair="EURAMD",
        horizon_days=h,
        target_date=dt.date(2026, 11, 19),
        model=model,
        model_version="t",
        spot=Decimal(str(spot)),
        center=q[0.50],
        q025=q[0.025],
        q10=q[0.10],
        q25=q[0.25],
        q75=q[0.75],
        q90=q[0.90],
        q975=q[0.975],
        served=True,
        meetings_in_horizon=[],
        git_sha="t",
        features_json={},
    )


def evidence(ratio=0.95, dm=0.03, hit=0.60, model="lightgbm") -> BacktestMetric:
    return BacktestMetric(
        run_date=dt.date(2026, 10, 17),
        pair="EURAMD",
        horizon_days=21,
        model=model,
        window="250d",
        n_obs=250,
        mae=1.0,
        mae_ratio_rw=ratio,
        hit_rate=hit,
        cov50=0.5,
        cov80=0.8,
        cov95=0.95,
        pinball=1.0,
        dm_pvalue=dm,
    )


def test_prob_above_is_half_at_the_median():
    assert prob_above(406.0, QS) == pytest.approx(0.5)
    assert prob_above(402.0, QS) == pytest.approx(0.9)
    assert prob_above(399.0, QS) == pytest.approx(0.975)  # clamped below the 95% band
    assert prob_above(500.0, QS) == pytest.approx(0.025)


@given(st.floats(min_value=390, max_value=420), st.floats(min_value=390, max_value=420))
def test_prob_above_falls_as_spot_rises(a, b):
    lo, hi = sorted((a, b))
    assert prob_above(lo, QS) >= prob_above(hi, QS)


def test_fr17_random_walk_served_means_no_edge():
    s = build_signal(EURAMD, forecast(406.0, model="random_walk"), None)
    assert (s.action, s.confidence, s.model_beats_random_walk) == ("no_edge", "none", False)
    assert s.prob_better_if_wait == pytest.approx(0.5)
    assert (s.sell, s.receive) == ("EUR", "AMD")
    assert s.verdict_source == "statistical"
    assert s.summary.startswith("Waiting 1M doesn't improve your expected rate; it adds risk")
    assert "402.00 to 410.00 AMD per EUR" in s.summary
    assert s.risk_half_width_pct == pytest.approx(0.9852, abs=1e-3)


def test_fr17_interest_difference_names_the_currency_that_pays_more():
    row = forecast(406.0, model="random_walk")
    row.features_json = {"policy_rates": {"CBA": 6.75, "ECB": 2.5}}
    s = build_signal(EURAMD, row, None)
    assert s.carry_pct_per_year == pytest.approx(4.25)
    assert s.carry_over_horizon_pct == pytest.approx(4.25 * 21 / 252, abs=1e-4)
    assert s.carry_amount == pytest.approx(406.0 * 4.25 * 21 / 252 / 100, rel=1e-6)
    assert "Holding AMD pays about 4.25%/yr more than EUR" in s.summary

    row.features_json = {"policy_rates": {"CBA": 2.0, "ECB": 2.5}}
    flipped = build_signal(EURAMD, row, None)
    assert flipped.carry_pct_per_year == pytest.approx(-0.5)
    assert "Holding EUR pays about 0.50%/yr more than AMD" in flipped.summary


def test_fr17_missing_policy_rates_leave_carry_empty():
    s = build_signal(EURAMD, forecast(406.0, model="random_walk"), None)
    assert (s.carry_pct_per_year, s.carry_amount) == (None, None)
    assert "Holding" not in s.summary


def test_fr17_a_promoted_ai_view_decides_the_verdict():
    from fxf.api.signal import AiBasis

    ai = AiBasis(
        prob_better_if_wait=0.66,
        expected_change_pct=0.5,
        model="llm",
        hit_rate=0.61,
        dm_pvalue=0.04,
        mae_ratio_rw=0.93,
        n_scored=250,
    )
    s = build_signal(EURAMD, forecast(406.0, model="random_walk"), None, ai)
    assert (s.verdict_source, s.action, s.confidence) == ("ai", "wait", "high")
    assert "AI view, right on direction 61% of the last 250 forecasts" in s.summary


def test_fr17_proven_model_expecting_a_higher_rate_says_wait():
    s = build_signal(EURAMD, forecast(409.0), evidence(hit=0.60))
    assert s.action == "wait"
    assert s.prob_better_if_wait > 0.6
    assert s.confidence == "high"
    assert s.summary.startswith("Wait:")


def test_fr17_proven_model_expecting_a_lower_rate_says_sell_now():
    s = build_signal(EURAMD, forecast(403.5), evidence(hit=0.55))
    assert s.action == "sell_now"
    assert s.prob_better_if_wait < 0.4
    assert s.confidence == "medium"
    assert s.downside_p10_rate == pytest.approx(399.5)


def test_fr17_no_lean_without_the_promotion_rule_or_direction_skill():
    unpromoted = build_signal(EURAMD, forecast(409.0), evidence(ratio=0.99))
    coin_flip = build_signal(EURAMD, forecast(409.0), evidence(hit=0.50))
    no_backtest = build_signal(EURAMD, forecast(409.0), None)
    assert {unpromoted.action, coin_flip.action, no_backtest.action} == {"no_edge"}


def test_fr17_small_edge_is_no_edge():
    s = build_signal(EURAMD, forecast(406.3), evidence())
    assert (s.action, s.confidence) == ("no_edge", "low")


def test_fr17_a_stated_45_percent_is_a_full_five_point_edge():
    from fxf.api.signal import AiBasis

    ai = AiBasis(
        prob_better_if_wait=0.45,
        expected_change_pct=-0.2,
        model="llm",
        hit_rate=0.6,
        dm_pvalue=0.04,
        mae_ratio_rw=0.95,
        n_scored=250,
    )
    s = build_signal(EURAMD, forecast(406.0, model="random_walk"), None, ai)
    assert s.action == "sell_now"

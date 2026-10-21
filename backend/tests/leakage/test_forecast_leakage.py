"""Leakage tests (NFR-03): no feature timestamp is at or after the forecast cutoff, on a fixed
historical date, and nothing published after the cutoff can change a forecast."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from fxf.constants import HORIZONS, MODEL_LGBM, PAIRS
from fxf.data_access import forecast_cutoff
from fxf.forecast.core import prepare_pair_data, walk_forward
from fxf.forecast.engine import run_forecasts
from fxf.forecast.inputs import load_pair_inputs
from fxf.models import CbEvent, Forecast, MacroSeries, Rate
from tests.regression.datasets import seed_synthetic

pytestmark = pytest.mark.db

FIXED = dt.date(2024, 6, 12)  # a Wednesday: an FOMC-like day in the synthetic calendar is near


@pytest.fixture
def seeded(session: Session) -> Session:
    seed_synthetic(session, end=dt.date(2024, 12, 31))
    return session


def test_nfr03_no_feature_timestamp_at_or_after_cutoff(seeded: Session):
    fcs = run_forecasts(seeded, FIXED)
    seeded.commit()
    cutoff = forecast_cutoff(FIXED)
    assert {f.pair for f in fcs} == set(PAIRS)
    for f in fcs:
        as_of = f.features["model_inputs"]["as_of"]
        assert dt.datetime.fromisoformat(as_of["cutoff"]) <= cutoff
        for sid, ts in as_of["macro_published_at"].items():
            assert ts is not None, sid  # the synthetic set has every series
            assert dt.datetime.fromisoformat(ts) < cutoff, (f.pair, sid, ts)
        assert dt.date.fromisoformat(as_of["rates_through"]) <= FIXED
        for d in as_of["aux_rates_through"].values():
            assert dt.date.fromisoformat(d) <= FIXED
        assert dt.date.fromisoformat(as_of["cb_events_through"]) < FIXED
        if f.model == MODEL_LGBM:
            assert dt.date.fromisoformat(as_of["labels_through"]) <= FIXED
            lg = f.features["model_inputs"]["lightgbm"]
            assert dt.date.fromisoformat(lg["train_end"]) < FIXED
        assert dt.date.fromisoformat(f.features["spot_date"]) <= FIXED
        # the band calibration reads only outcomes realised by the cutoff
        bc = f.features["band_calibration"]
        assert bc["applied"]
        assert dt.date.fromisoformat(bc["outcomes_through"]) <= FIXED


def _snapshot(fcs) -> dict:
    return {
        (f.pair, f.horizon_days, f.model): (
            round(f.center, 12),
            {k: round(v, 12) for k, v in f.quantiles.items()},
        )
        for f in fcs
    }


def test_nfr03_values_published_after_cutoff_cannot_change_a_forecast(seeded: Session):
    before = _snapshot(run_forecasts(seeded, FIXED))
    seeded.commit()
    cutoff = forecast_cutoff(FIXED)
    # Corrupt everything that was not public at the cutoff: later macro publications
    # (including values for dates <= FIXED published late), later rates and later decisions.
    seeded.execute(
        update(MacroSeries)
        .where(MacroSeries.published_at > cutoff)
        .values(value=MacroSeries.value * 7 + 3)
    )
    seeded.execute(update(Rate).where(Rate.date > FIXED).values(rate=Rate.rate * 1.5))
    seeded.execute(
        update(CbEvent).where(CbEvent.date >= FIXED).values(surprise_bps=500.0, hawkish_score=1.0)
    )
    seeded.commit()
    late = seeded.execute(
        select(MacroSeries.series_id).where(
            MacroSeries.published_at > cutoff, MacroSeries.date <= FIXED
        )
    ).all()
    assert late, "the fixture must contain values for dates <= FIXED published after the cutoff"
    after = _snapshot(run_forecasts(seeded, FIXED))
    assert after == before


def test_nfr03_walk_forward_has_no_lookahead(seeded: Session):
    """Backtest origins up to t give identical outputs whether or not data after t exists.

    Refits are frequent here so that some fall within h days of t, where a model trained on
    labels not yet realised at its origin would see different data in the two runs."""
    t = dt.date(2024, 6, 28)
    start = dt.date(2024, 2, 1)
    for pair in PAIRS:
        full = prepare_pair_data(
            load_pair_inputs(seeded, pair, end=dt.date(2024, 12, 31)), widening="scheduled"
        )
        trunc = prepare_pair_data(load_pair_inputs(seeded, pair, end=t), widening="scheduled")
        lo = int(np.searchsorted(trunc.dates64, np.datetime64(start)))
        hi = trunc.n - 1
        assert full.dates64[hi] == trunc.dates64[hi]
        o_trunc = np.arange(lo, hi + 1)
        o_full = np.arange(lo, hi + 40)
        cadence = {"garch_refit_every": 4, "lgbm_refit_every": 6}
        a = walk_forward(trunc, o_trunc, seed=7, **cadence)
        b = walk_forward(full, o_full, seed=7, **cadence)
        k = len(o_trunc)
        for h in HORIZONS:
            np.testing.assert_allclose(a.horizons[h].sigma, b.horizons[h].sigma[:k], rtol=1e-12)
            np.testing.assert_array_equal(a.horizons[h].cal, b.horizons[h].cal[:k])
            assert (a.horizons[h].cal_through <= o_trunc).all()
            np.testing.assert_allclose(
                a.horizons[h].extra_var, b.horizons[h].extra_var[:k], rtol=1e-12
            )
            for model, mu in a.horizons[h].mu.items():
                np.testing.assert_allclose(
                    mu, b.horizons[h].mu[model][:k], rtol=1e-12, equal_nan=True
                )
        # the features of the last origin were built from data <= t only
        pd.testing.assert_series_equal(trunc.features.iloc[hi], full.features.iloc[hi])


def test_nfr03_forecast_rows_record_the_cutoff(seeded: Session):
    run_forecasts(seeded, FIXED)
    seeded.commit()
    rows = seeded.execute(select(Forecast).where(Forecast.run_date == FIXED)).scalars().all()
    assert rows
    for r in rows:
        assert (
            r.features_json["model_inputs"]["as_of"]["cutoff"] == forecast_cutoff(FIXED).isoformat()
        )

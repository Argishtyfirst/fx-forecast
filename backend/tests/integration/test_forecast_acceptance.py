"""Acceptance tests for FR-08 to FR-13 and NFR-02 on a seeded synthetic database."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxf.backtest import run_backtest, run_backtest_job
from fxf.constants import (
    CENTER_CANDIDATES,
    HORIZONS,
    JOB_BACKTEST,
    JOB_FORECAST,
    MODEL_FORWARD,
    MODEL_LGBM,
    MODEL_RW,
    PAIRS,
    QUANTILE_COLUMNS,
    WINDOW_FULL,
    WINDOW_RECENT,
)
from fxf.forecast import params
from fxf.forecast.engine import run_forecast_job, run_forecasts
from fxf.forecast.types import FEATURES_JSON_KEYS
from fxf.models import BacktestMetric, CbMeeting, Forecast, JobRun, MacroSeries
from tests.regression.datasets import seed_synthetic

pytestmark = pytest.mark.db

RUN = dt.date(2026, 10, 21)
QCOLS = list(QUANTILE_COLUMNS)
N_SERVED = len(PAIRS) * len(HORIZONS)  # one served row per pair and horizon (FR-08)


@pytest.fixture
def seeded(session: Session) -> Session:
    seed_synthetic(session, end=RUN)
    return session


def _rows(session: Session, run_date: dt.date = RUN) -> list[Forecast]:
    session.expire_all()
    return list(session.execute(select(Forecast).where(Forecast.run_date == run_date)).scalars())


def _metric(pair: str, h: int, model: str, mae: float, ratio: float, p: float | None) -> dict:
    return {
        "run_date": RUN - dt.timedelta(days=1),
        "pair": pair,
        "horizon_days": h,
        "model": model,
        "window": WINDOW_RECENT,
        "n_obs": 250,
        "start_date": dt.date(2025, 10, 1),
        "end_date": dt.date(2026, 9, 20),
        "mae": mae,
        "mae_ratio_rw": ratio,
        "hit_rate": None,
        "cov50": 0.5,
        "cov80": 0.8,
        "cov95": 0.95,
        "pinball": 0.01,
        "pinball_ref": 0.01,
        "dm_pvalue": p,
    }


def _seed_metrics(session: Session, rows: list[dict]) -> None:
    for r in rows:
        session.add(BacktestMetric(**r))
    session.commit()


def test_fr08_one_served_row_per_pair_and_horizon(seeded: Session):
    run_forecasts(seeded, RUN)
    seeded.commit()
    rows = _rows(seeded)
    served = [r for r in rows if r.served]
    assert len(served) == N_SERVED
    assert {(r.pair, r.horizon_days) for r in served} == {(p, h) for p in PAIRS for h in HORIZONS}
    # every candidate of every horizon is produced when all inputs exist
    assert {(r.pair, r.horizon_days, r.model) for r in rows} == {
        (p, h, m) for p in PAIRS for h in HORIZONS for m in CENTER_CANDIDATES[h]
    }


def test_fr08_rerun_is_idempotent(seeded: Session):
    first = run_forecasts(seeded, RUN)
    seeded.commit()
    second = run_forecasts(seeded, RUN)
    seeded.commit()
    rows = _rows(seeded)
    assert len(rows) == len(first) == len(second)
    assert sum(r.served for r in rows) == N_SERVED
    a = {(f.pair, f.horizon_days, f.model): (f.center, f.quantiles) for f in first}
    b = {(f.pair, f.horizon_days, f.model): (f.center, f.quantiles) for f in second}
    assert a == b


def test_fr08_job_records_run_and_writes_rows(seeded: Session, clean_db):
    assert run_forecast_job(clean_db, run_date=RUN) is True
    job = seeded.execute(select(JobRun).where(JobRun.job == JOB_FORECAST)).scalar_one()
    assert job.status == "success" and job.rows_written == len(_rows(seeded))
    assert sum(r.served for r in _rows(seeded)) == N_SERVED


def test_fr08_missing_macro_and_meetings_still_produces_rw_and_garch(session: Session):
    seed_synthetic(session, end=RUN, with_macro=False, with_meetings=False)
    fcs = run_forecasts(session, RUN)
    session.commit()
    models = {
        (f.pair, f.horizon_days): {
            x.model for x in fcs if (x.pair, x.horizon_days) == (f.pair, f.horizon_days)
        }
        for f in fcs
    }
    assert len(models) == N_SERVED
    for key, ms in models.items():
        assert MODEL_RW in ms, key
        assert MODEL_FORWARD not in ms, key  # no policy rates
    assert sum(f.served for f in fcs) == N_SERVED
    assert all(f.model == MODEL_RW for f in fcs if f.served)
    assert all(f.meetings == [] for f in fcs)


def test_fr09_quantiles_ascending(seeded: Session):
    run_forecasts(seeded, RUN)
    seeded.commit()
    for r in _rows(seeded):
        qs = [float(getattr(r, c)) for c in QCOLS]
        assert qs == sorted(qs) and len(set(qs)) == len(qs), (r.pair, r.horizon_days, r.model)
        assert float(r.q25) < float(r.center) < float(r.q75)


def test_fr10_random_walk_row_for_each_pair_and_horizon(seeded: Session):
    run_forecasts(seeded, RUN)
    seeded.commit()
    rw = [r for r in _rows(seeded) if r.model == MODEL_RW]
    assert {(r.pair, r.horizon_days) for r in rw} == {(p, h) for p in PAIRS for h in HORIZONS}
    for r in rw:
        assert float(r.center) == pytest.approx(float(r.spot), abs=1e-8)


def test_fr11_promoted_model_is_served(seeded: Session):
    _seed_metrics(
        seeded,
        [
            _metric("EURUSD", 5, MODEL_RW, 0.0100, 1.0, None),
            _metric("EURUSD", 5, MODEL_FORWARD, 0.0090, 0.90, 0.03),
            _metric("EURUSD", 5, MODEL_LGBM, 0.0095, 0.95, 0.04),
            _metric("EURUSD", 21, MODEL_LGBM, 0.0200, 0.96, 0.05),
            _metric("EURUSD", 21, MODEL_FORWARD, 0.0190, 0.99, 0.01),  # ratio fails the rule
        ],
    )
    run_forecasts(seeded, RUN)
    seeded.commit()
    served = {(r.pair, r.horizon_days): r for r in _rows(seeded) if r.served}
    assert served[("EURUSD", 5)].model == MODEL_FORWARD
    assert "lowest 250d MAE" in served[("EURUSD", 5)].features_json["served_reason"]
    assert served[("EURUSD", 21)].model == MODEL_LGBM


def test_fr11_no_winner_serves_random_walk_with_garch_bands(seeded: Session):
    _seed_metrics(
        seeded,
        [
            _metric("USDAMD", 21, MODEL_RW, 2.0, 1.0, None),
            _metric("USDAMD", 21, MODEL_FORWARD, 1.99, 0.995, 0.41),
            _metric("USDAMD", 21, MODEL_LGBM, 2.10, 1.05, 0.80),
        ],
    )
    run_forecasts(seeded, RUN)
    seeded.commit()
    rows = [r for r in _rows(seeded) if r.pair == "USDAMD" and r.horizon_days == 21]
    served = [r for r in rows if r.served]
    assert len(served) == 1 and served[0].model == MODEL_RW
    reason = served[0].features_json["served_reason"]
    assert reason == "no model beats the random walk (best: forward, MAE ratio 0.995, DM p 0.41)"
    # RW center with the GARCH bands every candidate shares
    fwd = next(r for r in rows if r.model == MODEL_FORWARD)
    f = served[0].features_json
    assert float(served[0].center) == pytest.approx(float(served[0].spot), abs=1e-8)
    assert f["horizon_sigma"] == fwd.features_json["horizon_sigma"]
    assert f["garch_sigma"] > 0


def test_fr12_meeting_in_horizon_widens_bands_and_is_listed(seeded: Session):
    run_forecasts(seeded, RUN)
    seeded.commit()
    rw = {(r.pair, r.horizon_days): r for r in _rows(seeded) if r.model == MODEL_RW}
    # 2026-10-21 run: CBA 10-27, FED 10-28, ECB 10-29 (synthetic calendar)
    assert rw[("EURUSD", 1)].meetings_in_horizon == []
    assert rw[("EURUSD", 5)].meetings_in_horizon == [{"bank": "FED", "date": "2026-10-28"}]
    assert rw[("EURUSD", 21)].meetings_in_horizon[:2] == [
        {"bank": "FED", "date": "2026-10-28"},
        {"bank": "ECB", "date": "2026-10-29"},
    ]
    assert rw[("USDAMD", 5)].meetings_in_horizon == [
        {"bank": "CBA", "date": "2026-10-27"},
        {"bank": "FED", "date": "2026-10-28"},
    ]
    # EUR/AMD follows all three banks
    assert rw[("EURAMD", 5)].meetings_in_horizon == rw[("USDAMD", 5)].meetings_in_horizon
    assert {"bank": "ECB", "date": "2026-10-29"} in rw[("EURAMD", 21)].meetings_in_horizon
    for key in [("EURUSD", 5), ("EURUSD", 21), ("USDAMD", 5), ("USDAMD", 21), ("EURAMD", 21)]:
        f = rw[key].features_json
        assert f["event_extra_variance"] > 0, key
        assert f["horizon_sigma_pre"] > f["garch_sigma"], key
    f1 = rw[("EURUSD", 1)].features_json
    assert f1["event_extra_variance"] == 0.0
    assert f1["horizon_sigma_pre"] == pytest.approx(f1["garch_sigma"])
    assert f1["horizon_sigma"] == pytest.approx(
        f1["horizon_sigma_pre"] * f1["band_calibration"]["factors"]["80"]
    )

    # The same run without the meetings: every band is narrower (or equal) at every level.
    with_meetings = {k: v for k, v in rw.items()}
    widths = {
        k: [float(r.q975) - float(r.q025), float(r.q90) - float(r.q10)]
        for k, r in with_meetings.items()
    }
    factors = {k: r.features_json["band_calibration"]["factors"] for k, r in with_meetings.items()}
    seeded.query(CbMeeting).filter(CbMeeting.date > RUN).delete()
    seeded.commit()
    run_forecasts(seeded, RUN)
    seeded.commit()
    after = {(r.pair, r.horizon_days): r for r in _rows(seeded) if r.model == MODEL_RW}
    for k in [("EURUSD", 5), ("USDAMD", 5), ("EURAMD", 5)]:
        assert after[k].meetings_in_horizon == []
        # the calibration reads outcomes realised by the run date only, so it is unchanged
        assert after[k].features_json["band_calibration"]["factors"] == factors[k]
        new = [
            float(after[k].q975) - float(after[k].q025),
            float(after[k].q90) - float(after[k].q10),
        ]
        assert all(n < o for n, o in zip(new, widths[k], strict=True)), k


def test_fr12_1d_meeting_on_spot_date_widens(session: Session):
    # 2026-10-28 is a synthetic FOMC date: its impact day is the 1D target.
    run = dt.date(2026, 10, 28)
    seed_synthetic(session, end=run)
    run_forecasts(session, run)
    session.commit()
    r = next(
        x
        for x in _rows(session, run)
        if x.pair == "EURUSD" and x.horizon_days == 1 and x.model == MODEL_RW
    )
    assert {"bank": "FED", "date": "2026-10-28"} in r.meetings_in_horizon
    assert r.features_json["event_extra_variance"] > 0


def test_fr13_weekly_backtest_stores_metrics_per_pair_horizon_model(seeded: Session):
    n = run_backtest(seeded, RUN, start=dt.date(2025, 6, 1))
    seeded.commit()
    rows = list(seeded.execute(select(BacktestMetric)).scalars())
    assert n == len(rows) > 0
    keys = {(r.pair, r.horizon_days, r.model, r.window) for r in rows}
    expected = {
        (p, h, m, w)
        for p in PAIRS
        for h in HORIZONS
        for m in CENTER_CANDIDATES[h]
        for w in (WINDOW_RECENT, WINDOW_FULL)
    }
    assert keys == expected
    for r in rows:
        assert r.n_obs > 0 and r.mae >= 0
        assert 0 <= r.cov50 <= r.cov80 <= r.cov95 <= 1
        assert r.pinball > 0 and r.pinball_ref is not None
        if r.model == MODEL_RW:
            assert (
                r.mae_ratio_rw == pytest.approx(1.0) and r.hit_rate is None and r.dm_pvalue is None
            )
        else:
            assert r.dm_pvalue is None or 0 <= r.dm_pvalue <= 1
        if r.window == WINDOW_RECENT:
            assert r.n_obs <= 250
    # rerun is idempotent
    assert run_backtest(seeded, RUN, start=dt.date(2025, 6, 1)) == n
    seeded.commit()
    assert seeded.execute(select(func.count()).select_from(BacktestMetric)).scalar_one() == n


def test_fr13_backtest_job_then_forecast_uses_its_metrics(seeded: Session, clean_db, monkeypatch):
    monkeypatch.setattr(params, "BACKTEST_FULL_START", dt.date(2025, 9, 1))
    assert run_backtest_job(clean_db, run_date=RUN) is True
    job = seeded.execute(select(JobRun).where(JobRun.job == JOB_BACKTEST)).scalar_one()
    assert job.status == "success" and job.rows_written > 0
    assert "seconds" in job.meta
    run_forecasts(seeded, RUN)
    seeded.commit()
    for r in _rows(seeded):
        if r.served:
            reason = r.features_json["served_reason"]
            assert reason.startswith(("no model beats", "lowest 250d MAE")), reason


def test_nfr02_forecast_stores_sha_version_features_and_is_reproducible(seeded: Session):
    a = run_forecasts(seeded, RUN)
    seeded.commit()
    for r in _rows(seeded):
        assert r.git_sha and r.model_version == params.MODEL_VERSIONS[r.model]
        missing = set(FEATURES_JSON_KEYS) - set(r.features_json)
        assert not missing, missing
        assert r.features_json["seed"] is not None
    lg = next(r for r in _rows(seeded) if r.model == MODEL_LGBM)
    assert len(lg.features_json["model_inputs"]["lightgbm"]["features"]) > 10
    b = run_forecasts(seeded, RUN)
    assert [(f.model, f.center) for f in a] == [(f.model, f.center) for f in b]


def test_fr08_macro_published_late_is_not_used(seeded: Session):
    """A policy-rate value published after the cutoff must not move the forward center."""
    base = {
        (f.pair, f.horizon_days): f.center
        for f in run_forecasts(seeded, RUN)
        if f.model == MODEL_FORWARD
    }
    seeded.query(MacroSeries).filter(
        MacroSeries.series_id == "ECB_DFR", MacroSeries.date == RUN
    ).update({"value": 9.99, "published_at": dt.datetime(2026, 10, 21, 16, 0, 1, tzinfo=dt.UTC)})
    seeded.commit()
    late = {
        (f.pair, f.horizon_days): f.center
        for f in run_forecasts(seeded, RUN)
        if f.model == MODEL_FORWARD
    }
    assert late == base


def test_fr15_drivers_are_generic_over_pairs(seeded: Session):
    """Rate differential = quote minus base policy rate; per-bank drivers follow the pair's banks."""
    run_forecasts(seeded, RUN)
    seeded.commit()
    rows = {r.pair: r for r in _rows(seeded) if r.served and r.horizon_days == 21}
    expected_banks = {"EURUSD": ("ECB", "FED"), "USDAMD": ("FED", "CBA"), "EURAMD": ("ECB", "CBA")}
    for pair, spec in PAIRS.items():
        f = rows[pair].features_json
        base, quote = expected_banks[pair]
        assert set(f["policy_rates"]) == {base, quote}
        assert f["rate_diff_bps"] == pytest.approx(
            (f["policy_rates"][quote] - f["policy_rates"][base]) * 100
        )
        assert set(f["last_surprise_bps"]) == set(spec.banks)
        assert set(f["days_to_next_meeting"]) == set(spec.banks)
        lg = next(
            r
            for r in _rows(seeded)
            if r.pair == pair and r.horizon_days == 21 and r.model == MODEL_LGBM
        )
        feats = lg.features_json["model_inputs"]["lightgbm"]["features"]
        assert ("rubamd_ret_1" in feats) == (spec.quote == "AMD")


def test_fr09_bands_are_calibrated_walk_forward(seeded: Session):
    """Every row carries its walk-forward calibration; it reads outcomes up to the spot date only."""
    run_forecasts(seeded, RUN)
    seeded.commit()
    for r in _rows(seeded):
        bc = r.features_json["band_calibration"]
        assert bc["applied"] and bc["n_obs"] >= params.CAL_MIN_OBS
        assert dt.date.fromisoformat(bc["outcomes_through"]) <= dt.date.fromisoformat(
            r.features_json["spot_date"]
        )
        lo, hi = params.CAL_CLAMP
        assert all(lo <= c <= hi for c in bc["factors"].values())


def test_a_forecast_rerun_keeps_the_ai_view_rows(seeded: Session):
    """The AI view ("llm") is written by its own job; rerunning the forecast must not delete it."""
    run_forecasts(seeded, RUN)
    seeded.commit()
    served = seeded.scalars(
        select(Forecast).where(Forecast.run_date == RUN, Forecast.served.is_(True))
    ).first()
    ai = Forecast(
        **{
            c: getattr(served, c)
            for c in (
                "run_date",
                "pair",
                "horizon_days",
                "target_date",
                "spot",
                "center",
                "q025",
                "q10",
                "q25",
                "q75",
                "q90",
                "q975",
                "meetings_in_horizon",
            )
        },
        model="llm",
        model_version="gemini-test@ai-p3",
        served=False,
        git_sha="t",
        features_json={"llm": {"prob_higher": 0.45}},
    )
    seeded.add(ai)
    seeded.commit()
    run_forecasts(seeded, RUN)
    seeded.commit()
    assert seeded.scalars(select(Forecast).where(Forecast.model == "llm")).all()

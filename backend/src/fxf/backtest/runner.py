"""Weekly walk-forward backtest (FR-13, spec: Evaluation and backtesting).

For every origin t (a trading date of the pair from `start`, default
params.BACKTEST_FULL_START): train on data <= t, forecast t + h, step one trading day.
Features use only values published by forecast_cutoff(t); widening uses only scheduled
meetings (unscheduled ones were not known in advance). Refit schedule for speed: GARCH
parameters every 21 origins with daily variance filtering on data <= t in between, LightGBM
every 63 origins (params.GARCH_REFIT_EVERY / LGBM_REFIT_EVERY).

Metrics per pair x horizon x center candidate x window. "250d" is the last 250 origins with
a realised outcome, "full" is every origin; start_date and end_date are the first and last
origin. pinball_ref scores GARCH-only bands (random-walk center, no event widening, no
empirical check, no calibration) on the same dates. The walk-forward starts CAL_WINDOW + 21
origins before `start` so the first scored origins already have a calibrated band. A model without a prediction on some origins (missing
inputs) is scored on the origins where it has one, against the random walk on those origins.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from fxf.alerts import send_alert
from fxf.backtest import metrics as M
from fxf.calendars import now_cet
from fxf.config import get_settings
from fxf.constants import (
    BACKTEST_WINDOW_DAYS,
    BANDS,
    CENTER_CANDIDATES,
    HORIZONS,
    JOB_BACKTEST,
    MODEL_RW,
    PAIRS,
    WINDOW_FULL,
    WINDOW_RECENT,
)
from fxf.db import session_scope
from fxf.forecast import bands, params
from fxf.forecast.core import (
    InsufficientData,
    PairData,
    WalkForward,
    prepare_pair_data,
    walk_forward,
)
from fxf.forecast.inputs import load_pair_inputs
from fxf.forecast.selection import MetricSummary, select_from_metrics
from fxf.jobs import RunContext, run_job
from fxf.logging_setup import get_logger
from fxf.models import BacktestMetric, upsert

log = get_logger(__name__)

PK_COLS = ["run_date", "pair", "horizon_days", "model", "window"]
METRIC_COLS = [
    "n_obs",
    "start_date",
    "end_date",
    "mae",
    "mae_ratio_rw",
    "hit_rate",
    "cov50",
    "cov80",
    "cov95",
    "pinball",
    "pinball_ref",
    "dm_pvalue",
]
# cov50/cov80/cov95 -> column positions of the band's quantiles in bands.QUANTILE_NAMES.
BAND_COLS = {
    f"cov{label}": (bands.QUANTILE_NAMES.index(lo), bands.QUANTILE_NAMES.index(hi))
    for label, (lo, hi) in BANDS.items()
}


@dataclass
class BacktestResult:
    run_date: dt.date
    rows: list[dict[str, Any]] = field(default_factory=list)
    seconds: dict[str, float] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)

    @property
    def rows_written(self) -> int:
        return len(self.rows)


def backtest_origins(data: PairData, start: dt.date) -> np.ndarray:
    """Origins from `start` (after the GARCH warm-up) to the last date with a 1-day outcome."""
    first = max(
        params.GARCH_MIN_OBS, int(np.searchsorted(data.dates64, np.datetime64(start), "left"))
    )
    last = data.n - 2
    return np.arange(first, last + 1) if last >= first else np.array([], dtype=int)


def _zmat(nu_h: np.ndarray) -> np.ndarray:
    return np.vstack([bands.z_values(float(v)) for v in nu_h]) if len(nu_h) else np.empty((0, 6))


def pair_metrics(
    data: PairData,
    wf: WalkForward,
    run_date: dt.date,
    horizons: tuple[int, ...] = HORIZONS,
    first_scored: int = 0,
) -> list[dict[str, Any]]:
    """Metrics over origins >= first_scored (earlier origins only warm up the calibration)."""
    rows: list[dict[str, Any]] = []
    o = wf.origins
    spot = data.rates[o]
    for h in horizons:
        ho = wf.horizons[h]
        valid = (o + h <= data.n - 1) & (o >= first_scored)
        if not valid.any():
            continue
        oi = o[valid]
        s = spot[valid]
        y = data.rates[oi + h]
        y_ret = np.log(y / s)
        z = _zmat(ho.nu_h[valid])
        zc = bands.calibrated_z(z, ho.cal[valid])
        sig = ho.sigma_pre[valid][:, None]
        q_ref = s[:, None] * np.exp(z * ho.sigma_ref[valid][:, None])
        rw_err = np.abs(s - y)
        recent = np.zeros(len(oi), dtype=bool)
        recent[-BACKTEST_WINDOW_DAYS:] = True
        windows = {WINDOW_FULL: np.ones(len(oi), dtype=bool), WINDOW_RECENT: recent}
        for model in CENTER_CANDIDATES[h]:
            mu = ho.mu[model][valid]
            avail = np.isfinite(mu)
            center = s * np.exp(mu)
            qmat = s[:, None] * np.exp(mu[:, None] + zc * sig)
            err = np.abs(center - y)
            for wname, wmask in windows.items():
                sel = wmask & avail
                n = int(sel.sum())
                if n == 0:
                    continue
                m_mae = M.mae(err[sel])
                rw_mae = M.mae(rw_err[sel])
                row: dict[str, Any] = {
                    "run_date": run_date,
                    "pair": data.pair,
                    "horizon_days": h,
                    "model": model,
                    "window": wname,
                    "n_obs": n,
                    "start_date": data.dates[oi[sel][0]].date(),
                    "end_date": data.dates[oi[sel][-1]].date(),
                    "mae": m_mae,
                    "mae_ratio_rw": m_mae / max(rw_mae, 1e-12),
                    "hit_rate": None if model == MODEL_RW else M.hit_rate(mu[sel], y_ret[sel]),
                    "pinball": M.mean_pinball(y[sel], qmat[sel], bands.QUANTILE_PROBS),
                    "pinball_ref": M.mean_pinball(y[sel], q_ref[sel], bands.QUANTILE_PROBS),
                    "dm_pvalue": None if model == MODEL_RW else M.dm_test(err[sel], rw_err[sel], h),
                }
                for col, (lo, hi) in BAND_COLS.items():
                    row[col] = M.coverage(y[sel], qmat[sel, lo], qmat[sel, hi])
                rows.append(row)
    return rows


def coverage_alerts(rows: list[dict[str, Any]]) -> list[str]:
    """Risk rule for every AMD pair (params.is_managed): the 250d 80% coverage of the model
    that would be served is below params.COVERAGE_ALERT_THRESHOLD."""
    out: list[str] = []
    pairs = [p for p, spec in PAIRS.items() if params.is_managed(spec)]
    for pair in pairs:
        for h in HORIZONS:
            recent = [
                r
                for r in rows
                if r["pair"] == pair and r["horizon_days"] == h and r["window"] == WINDOW_RECENT
            ]
            if not recent:
                continue
            summaries = [
                MetricSummary(r["model"], r["mae"], r["mae_ratio_rw"], r["dm_pvalue"], r["cov80"])
                for r in recent
            ]
            model, _ = select_from_metrics(summaries, h)
            row = next((r for r in recent if r["model"] == model), None)
            if row is not None and row["cov80"] < params.COVERAGE_ALERT_THRESHOLD:
                out.append(
                    f"{pair} {h}d: 80% band coverage {row['cov80']:.1%} over the last "
                    f"{row['n_obs']} days (model {model}) is below "
                    f"{params.COVERAGE_ALERT_THRESHOLD:.0%}"
                )
    return out


def backtest(
    session: Session, run_date: dt.date, *, start: dt.date | None = None
) -> BacktestResult:
    """Run the walk-forward for every pair, upsert backtest_metrics (caller commits)."""
    seed = get_settings().random_seed
    start = start or params.BACKTEST_FULL_START
    res = BacktestResult(run_date=run_date)
    for pair in PAIRS:
        t0 = time.monotonic()
        try:
            inputs = load_pair_inputs(session, pair, end=run_date)
            data = prepare_pair_data(inputs, widening="scheduled")
            scored = backtest_origins(data, start)
            if len(scored) == 0:
                raise InsufficientData(f"{pair}: no backtest origins on or after {start}")
            # Warm-up origins before `start` feed the band calibration of the first scored ones.
            warm = max(params.GARCH_MIN_OBS, int(scored[0]) - params.CAL_WINDOW - max(HORIZONS))
            origins = np.arange(warm, int(scored[-1]) + 1)
            wf = walk_forward(data, origins, seed=seed)
        except InsufficientData as exc:
            res.skipped[pair] = str(exc)
            log.warning("backtest skipped", extra={"pair": pair, "reason": str(exc)})
            continue
        res.rows.extend(pair_metrics(data, wf, run_date, first_scored=int(scored[0])))
        res.seconds[pair] = round(time.monotonic() - t0, 2)
        log.info(
            "backtest pair done",
            extra={"pair": pair, "origins": int(len(scored)), "seconds": res.seconds[pair]},
        )
    upsert(session, BacktestMetric, res.rows, PK_COLS, METRIC_COLS)
    session.flush()
    res.alerts = coverage_alerts(res.rows)
    if res.alerts:
        send_alert(
            f"AMD band coverage below {params.COVERAGE_ALERT_THRESHOLD:.0%}", "\n".join(res.alerts)
        )
    return res


def run_backtest(session: Session, run_date: dt.date, *, start: dt.date | None = None) -> int:
    """Walk-forward backtest for every pair; returns the number of backtest_metrics rows written."""
    return backtest(session, run_date, start=start).rows_written


def run_backtest_job(engine: Engine | None = None, *, run_date: dt.date | None = None) -> bool:
    """The weekly backtest job (constants.JOB_BACKTEST). Fails when a pair cannot be backtested."""
    rd = run_date or now_cet().date()

    def _fn(ctx: RunContext) -> None:
        t0 = time.monotonic()
        with session_scope(engine) as s:
            res = backtest(s, rd)
        ctx.rows_written = res.rows_written
        ctx.meta.update(
            {
                "run_date": rd.isoformat(),
                "seconds": {**res.seconds, "total": round(time.monotonic() - t0, 2)},
                "skipped": res.skipped,
                "coverage_alerts": res.alerts,
            }
        )
        if res.skipped:
            raise RuntimeError(
                f"backtest skipped {', '.join(sorted(res.skipped))}: insufficient data"
            )

    return run_job(JOB_BACKTEST, _fn, engine=engine, meta={"run_date": rd.isoformat()})

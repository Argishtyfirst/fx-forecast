"""Daily forecast engine (FR-08 to FR-12).

For each pair, horizon and center candidate (constants.CENTER_CANDIDATES) one forecasts row:
center and quantiles as rates, the meetings inside the horizon (FR-12), the git SHA, model
version and feature snapshot (NFR-02). Exactly one row per pair and horizon is served
(selection.choose_served, FR-11). The random walk row always exists (FR-10). When an input is
missing (no policy rates, too little history for LightGBM), that model is skipped and the
random walk with GARCH bands is still produced.

Spot is the last rate on or before run_date; the forecast origin is the spot date, so every
input is visible at forecast_cutoff(spot_date) <= forecast_cutoff(run_date).
target_date = calendars.add_trading_days(PAIR_CALENDAR[pair], spot_date, h).
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

import numpy as np
from sqlalchemy import Engine, delete, update
from sqlalchemy.orm import Session

from fxf.calendars import PAIR_CALENDAR, add_trading_days, now_cet
from fxf.config import get_settings, git_sha
from fxf.constants import (
    CENTER_CANDIDATES,
    HORIZONS,
    JOB_FORECAST,
    MODEL_FORWARD,
    MODEL_LGBM,
    MODEL_RW,
    PAIRS,
)
from fxf.db import session_scope
from fxf.events.features import last_decision, meetings_in_window
from fxf.forecast import bands, params
from fxf.forecast.core import InsufficientData, PairData, prepare_pair_data, walk_forward
from fxf.forecast.features import SERIES_BANK, input_timestamps
from fxf.forecast.inputs import load_pair_inputs
from fxf.forecast.selection import choose_served
from fxf.forecast.types import ModelForecast
from fxf.jobs import RunContext, run_job
from fxf.logging_setup import get_logger
from fxf.models import Forecast, upsert

log = get_logger(__name__)

CONFLICT_COLS = ["run_date", "pair", "horizon_days", "model"]
UPDATE_COLS = [
    "target_date",
    "model_version",
    "spot",
    "center",
    "q025",
    "q10",
    "q25",
    "q75",
    "q90",
    "q975",
    "served",
    "meetings_in_horizon",
    "git_sha",
    "features_json",
]


def jsonable(v: Any) -> Any:
    """Recursively convert numpy scalars and NaN/inf to JSON-safe values."""
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [jsonable(x) for x in v]
    if isinstance(v, np.bool_ | bool):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, float | np.floating):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, dt.date):
        return v.isoformat()
    return v


def _opt(v: float) -> float | None:
    v = float(v)
    return v if math.isfinite(v) else None


def forecast_pair(session: Session, pair: str, run_date: dt.date, seed: int) -> list[ModelForecast]:
    inputs = load_pair_inputs(session, pair, end=run_date)
    data: PairData = prepare_pair_data(inputs, widening="all")
    spec = inputs.spec
    i = data.n - 1
    spot_date = data.dates[i].date()
    spot = float(data.rates[i])
    # Trailing origins (outcomes known by the spot date) for the band calibration: a cheap
    # walk-forward without LightGBM, then the detailed forecast at the spot date.
    hist_o = np.arange(max(params.GARCH_MIN_OBS, i - max(HORIZONS) - params.CAL_WINDOW + 1), i)
    hist = (
        walk_forward(data, hist_o, seed=seed, with_lgbm=False, calibrate=False)
        if len(hist_o)
        else None
    )
    wf = walk_forward(data, [i], seed=seed, detail=True, history=hist)
    as_of = input_timestamps(inputs, spot_date)
    feats = data.features.iloc[i]

    policy_rates = {
        SERIES_BANK[spec.base_rate_series]: _opt(data.i_base[i]),
        SERIES_BANK[spec.quote_rate_series]: _opt(data.i_quote[i]),
    }
    last = {b: last_decision(inputs.events, b, spot_date) for b in spec.banks}
    common: dict[str, Any] = {
        "spot_date": spot_date.isoformat(),
        "rate_diff_bps": _opt(feats["rate_diff_bps"]),
        "rate_diff_change_21d_bps": _opt(feats["rate_diff_chg_21d_bps"]),
        "policy_rates": policy_rates,
        "garch_vol_annual": float(wf.vol_annual[0]),
        "student_t_nu": float(wf.nu[0]),
        "last_surprise_bps": {b: (d or {}).get("surprise_bps") for b, d in last.items()},
        "hawkish_score": {b: (d or {}).get("hawkish_score") for b, d in last.items()},
        "days_to_next_meeting": {
            b: (None if not math.isfinite(v) else int(v))
            for b in spec.banks
            for v in [float(feats[f"days_to_next_{b}"])]
        },
        "seed": seed,
    }
    out: list[ModelForecast] = []
    for h in HORIZONS:
        ho = wf.horizons[h]
        target = add_trading_days(PAIR_CALENDAR[pair], spot_date, h)
        meetings = meetings_in_window(
            inputs.meetings, spec.banks, spot_date - dt.timedelta(days=1), target
        )
        detail = ho.detail[0]
        sigma_pre, nu_h, cal = float(ho.sigma_pre[0]), float(ho.nu_h[0]), ho.cal[0]
        mu_fwd = float(ho.mu[MODEL_FORWARD][0])
        cands = CENTER_CANDIDATES[h]
        available = [m for m in cands if math.isfinite(float(ho.mu[m][0]))]
        served_model, reason = choose_served(session, pair, h, as_of=run_date)
        if served_model not in available:
            reason = (
                f"selected {served_model} is unavailable for this run (missing inputs); "
                "serving the random walk with GARCH bands"
            )
            served_model = MODEL_RW
        base_inputs = {
            "as_of": as_of,
            "garch": wf.garch_detail[0],
            "event_widening": detail["event_widening"],
            "horizon_dates": detail["horizon_dates"],
        }
        for model in available:
            mu = float(ho.mu[model][0])
            center, q = bands.to_rates(spot, mu, sigma_pre, nu_h, cal)
            model_inputs = {**base_inputs, "mu": mu}
            if model == MODEL_FORWARD:
                model_inputs["forward"] = detail["forward"]
            if model == MODEL_LGBM:
                li = wf.lgbm_detail[h][0] or {}
                model_inputs["lightgbm"] = li
                model_inputs["as_of"] = {**as_of, "labels_through": li.get("labels_through")}
            features = {
                **common,
                "forward_rate": spot * math.exp(mu_fwd) if math.isfinite(mu_fwd) else None,
                "horizon_sigma": float(ho.sigma[0]),
                "horizon_sigma_pre": sigma_pre,
                "band_calibration": detail["band_calibration"],
                "garch_sigma": float(ho.sigma_ref[0]),
                "event_extra_variance": float(ho.extra_var[0]),
                "empirical_check": detail["empirical_check"],
                "student_t_nu_horizon": nu_h,
                "served_reason": reason,
                "model_inputs": model_inputs,
            }
            out.append(
                ModelForecast(
                    run_date=run_date,
                    pair=pair,
                    horizon_days=h,
                    target_date=target,
                    model=model,
                    model_version=params.MODEL_VERSIONS[model],
                    spot=spot,
                    center=center,
                    quantiles=q,
                    meetings=meetings,
                    features=jsonable(features),
                    served=model == served_model,
                )
            )
    return out


def to_row(f: ModelForecast, sha: str) -> dict[str, Any]:
    return {
        "run_date": f.run_date,
        "pair": f.pair,
        "horizon_days": f.horizon_days,
        "target_date": f.target_date,
        "model": f.model,
        "model_version": f.model_version,
        "spot": round(f.spot, 8),
        "center": round(f.center, 8),
        **{c: round(v, 8) for c, v in f.quantiles.items()},
        "served": f.served,
        "meetings_in_horizon": f.meetings,
        "git_sha": sha,
        "features_json": f.features,
    }


def write_forecasts(session: Session, forecasts: list[ModelForecast]) -> int:
    """Idempotent write: upsert on (run_date, pair, horizon_days, model). Rows of the same run
    date and pair that this run did not produce (a model skipped this time) are removed, so a
    rerun leaves exactly this run's outputs and one served row per pair and horizon."""
    sha = git_sha()
    keys = {(f.run_date, f.pair) for f in forecasts}
    for run_date, pair in keys:
        session.execute(
            update(Forecast)
            .where(Forecast.run_date == run_date, Forecast.pair == pair)
            .values(served=False)
        )
        for h in HORIZONS:
            models = {f.model for f in forecasts if f.pair == pair and f.horizon_days == h}
            session.execute(
                delete(Forecast).where(
                    Forecast.run_date == run_date,
                    Forecast.pair == pair,
                    Forecast.horizon_days == h,
                    Forecast.model.not_in(models),
                )
            )
    n = upsert(session, Forecast, [to_row(f, sha) for f in forecasts], CONFLICT_COLS, UPDATE_COLS)
    session.flush()
    return n


def run_forecasts(session: Session, run_date: dt.date) -> list[ModelForecast]:
    """Compute and write (upsert, flush; the caller commits) every pair's forecasts."""
    seed = get_settings().random_seed
    out: list[ModelForecast] = []
    for pair in PAIRS:
        try:
            out.extend(forecast_pair(session, pair, run_date, seed))
        except InsufficientData as exc:
            log.warning("forecast skipped", extra={"pair": pair, "reason": str(exc)})
    write_forecasts(session, out)
    return out


def run_forecast_job(engine: Engine | None = None, *, run_date: dt.date | None = None) -> bool:
    """The daily forecast job (constants.JOB_FORECAST). Fails, and so alerts, when a pair has
    too little data to forecast; the pairs that could be forecast are still written."""
    rd = run_date or now_cet().date()

    def _fn(ctx: RunContext) -> None:
        with session_scope(engine) as s:
            fcs = run_forecasts(s, rd)
        ctx.rows_written = len(fcs)
        done = sorted({f.pair for f in fcs})
        missing = [p for p in PAIRS if p not in done]
        ctx.meta.update(
            {
                "run_date": rd.isoformat(),
                "pairs": done,
                "served": {f"{f.pair}:{f.horizon_days}": f.model for f in fcs if f.served},
                "missing_pairs": missing,
            }
        )
        if missing:
            raise RuntimeError(f"no forecast for {', '.join(missing)}: insufficient data")

    return run_job(JOB_FORECAST, _fn, engine=engine, meta={"run_date": rd.isoformat()})

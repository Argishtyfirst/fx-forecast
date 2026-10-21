"""Live track record of the AI view: only forecasts whose target date has passed.

Scored like the backtest scores every model (fxf.backtest.metrics): absolute log-return
errors against the random walk on the same dates, the one-sided Diebold–Mariano test, and
the directional hit rate, plus the Brier score of its probability. It is promoted only by
the same rule, over the same number of forecasts (constants.BACKTEST_WINDOW_DAYS).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from fxf.api.schemas import AiTrackRecord
from fxf.backtest.metrics import dm_test, hit_rate
from fxf.constants import BACKTEST_WINDOW_DAYS, MODEL_LLM, PROMOTION_DM_PVALUE, PROMOTION_MAE_RATIO
from fxf.data_access import load_rates
from fxf.models import Forecast


def track_record(
    session: Session, pair: str, horizon_days: int, rates: pd.Series | None = None
) -> AiTrackRecord:
    rates = load_rates(session, pair) if rates is None else rates
    empty = AiTrackRecord(
        n_scored=0,
        required=BACKTEST_WINDOW_DAYS,
        hit_rate=None,
        mae_ratio_rw=None,
        dm_pvalue=None,
        brier=None,
        promoted=False,
    )
    if rates.empty:
        return empty
    last_known = rates.index[-1].date()
    rows = session.scalars(
        select(Forecast)
        .where(
            Forecast.pair == pair,
            Forecast.horizon_days == horizon_days,
            Forecast.model == MODEL_LLM,
            Forecast.target_date <= last_known,
        )
        .order_by(Forecast.run_date.desc())
        .limit(BACKTEST_WINDOW_DAYS)
    ).all()
    if not rows:
        return empty
    rows = rows[::-1]
    # The outcome is the fix on the target date, or the last fix before it (holidays).
    actual = rates.reindex(
        pd.DatetimeIndex([pd.Timestamp(r.target_date) for r in rows]), method="ffill"
    )
    spot = np.array([float(r.spot) for r in rows])
    center = np.array([float(r.center) for r in rows])
    y = np.log(actual.to_numpy(dtype="float64") / spot)
    mu = np.log(center / spot)
    prob = np.array(
        [float((r.features_json or {}).get("llm", {}).get("prob_higher", 0.5)) for r in rows]
    )
    ok = np.isfinite(y)
    y, mu, prob = y[ok], mu[ok], prob[ok]
    n = len(y)
    if n == 0:
        return empty
    err_model, err_rw = np.abs(y - mu), np.abs(y)
    mae_rw = float(err_rw.mean())
    ratio = float(err_model.mean() / mae_rw) if mae_rw > 0 else None
    dm = dm_test(err_model, err_rw, horizon_days)
    brier = float(np.mean((prob - (y > 0).astype("float64")) ** 2))
    hit = hit_rate(prob - 0.5, y)
    promoted = (
        n >= BACKTEST_WINDOW_DAYS
        and ratio is not None
        and dm is not None
        and ratio < PROMOTION_MAE_RATIO
        and dm < PROMOTION_DM_PVALUE
        and hit is not None
        and hit > 0.5
    )
    return AiTrackRecord(
        n_scored=n,
        required=BACKTEST_WINDOW_DAYS,
        hit_rate=hit,
        mae_ratio_rw=None if ratio is None or math.isnan(ratio) else round(ratio, 4),
        dm_pvalue=dm,
        brier=round(brier, 4),
        promoted=promoted,
    )

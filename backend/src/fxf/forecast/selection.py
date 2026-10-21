"""Served-model selection (FR-11, spec: Promotion rule).

Among the center candidates of the horizon, serve the one with the lowest MAE in the latest
window="250d" backtest that meets the promotion rule: mae_ratio_rw < PROMOTION_MAE_RATIO and
dm_pvalue < PROMOTION_DM_PVALUE. Otherwise serve the random walk center with GARCH bands.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxf.constants import (
    CENTER_CANDIDATES,
    MODEL_RW,
    PROMOTION_DM_PVALUE,
    PROMOTION_MAE_RATIO,
    WINDOW_RECENT,
)
from fxf.models import BacktestMetric

NO_METRICS_REASON = "no backtest metrics yet; serving the random walk with GARCH bands"


@dataclass(frozen=True)
class MetricSummary:
    model: str
    mae: float
    mae_ratio_rw: float
    dm_pvalue: float | None
    cov80: float | None = None


def is_promoted(m: MetricSummary) -> bool:
    return (
        m.model != MODEL_RW
        and m.mae_ratio_rw < PROMOTION_MAE_RATIO
        and m.dm_pvalue is not None
        and m.dm_pvalue < PROMOTION_DM_PVALUE
    )


def _fmt_p(p: float | None) -> str:
    return "n/a" if p is None else f"{p:.2f}"


def select_from_metrics(metrics: Sequence[MetricSummary], horizon_days: int) -> tuple[str, str]:
    """Pure selection rule on one pair and horizon's 250d metrics. Returns (model, reason)."""
    cands = set(CENTER_CANDIDATES.get(horizon_days, (MODEL_RW,)))
    rows = [m for m in metrics if m.model in cands and m.model != MODEL_RW]
    if not rows:
        return MODEL_RW, NO_METRICS_REASON
    promoted = sorted((m for m in rows if is_promoted(m)), key=lambda m: (m.mae, m.model))
    if promoted:
        w = promoted[0]
        return w.model, (
            f"lowest 250d MAE among models meeting the promotion rule "
            f"(MAE ratio {w.mae_ratio_rw:.3f}, DM p {_fmt_p(w.dm_pvalue)})"
        )
    best = min(rows, key=lambda m: (m.mae, m.model))
    return MODEL_RW, (
        f"no model beats the random walk (best: {best.model}, "
        f"MAE ratio {best.mae_ratio_rw:.3f}, DM p {_fmt_p(best.dm_pvalue)})"
    )


def latest_metrics(
    session: Session, pair: str, horizon_days: int, *, as_of: dt.date | None = None
) -> list[MetricSummary]:
    q = select(func.max(BacktestMetric.run_date)).where(
        BacktestMetric.pair == pair,
        BacktestMetric.horizon_days == horizon_days,
        BacktestMetric.window == WINDOW_RECENT,
    )
    if as_of is not None:
        q = q.where(BacktestMetric.run_date <= as_of)
    run_date = session.execute(q).scalar_one_or_none()
    if run_date is None:
        return []
    rows = session.execute(
        select(BacktestMetric).where(
            BacktestMetric.pair == pair,
            BacktestMetric.horizon_days == horizon_days,
            BacktestMetric.window == WINDOW_RECENT,
            BacktestMetric.run_date == run_date,
        )
    ).scalars()
    return [
        MetricSummary(
            model=r.model,
            mae=float(r.mae),
            mae_ratio_rw=float(r.mae_ratio_rw),
            dm_pvalue=None if r.dm_pvalue is None else float(r.dm_pvalue),
            cov80=float(r.cov80),
        )
        for r in rows
    ]


def choose_served(
    session: Session, pair: str, horizon_days: int, *, as_of: dt.date | None = None
) -> tuple[str, str]:
    """(model, reason) for pair and horizon from the latest 250d backtest on or before as_of."""
    return select_from_metrics(
        latest_metrics(session, pair, horizon_days, as_of=as_of), horizon_days
    )

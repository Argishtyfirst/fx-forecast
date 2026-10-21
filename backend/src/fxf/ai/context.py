"""The context the AI view reads: what the dashboard shows for one pair on one run date.

Point-in-time like every other model input (NFR-03): rates on or before the spot date,
decisions before the run date, and the run's own served forecasts and backtest. It holds
public market data only.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fxf.constants import (
    BACKTEST_WINDOW_DAYS,
    BANDS,
    HORIZON_LABELS,
    MODEL_RW,
    RUBAMD,
    WINDOW_RECENT,
    PairSpec,
)
from fxf.data_access import load_rates
from fxf.models import BacktestMetric, CbEvent, Forecast

HISTORY_DAYS = 90
MAX_STATEMENT_SENTENCES = 3


def _pct(a: float, b: float) -> float:
    return round((a / b - 1.0) * 100.0, 3)


def _num(x: Any, nd: int = 4) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else round(v, nd)


def _recent_moves(session: Session, pair: str, spot_date: dt.date) -> dict[str, Any]:
    s = load_rates(session, pair, end=spot_date).iloc[-(HISTORY_DAYS + 64) :]
    if len(s) < 2:
        return {}
    last = float(s.iloc[-1])
    moves = {
        f"change_{n}d_pct": _pct(last, float(s.iloc[-1 - n])) for n in (1, 5, 21, 63) if len(s) > n
    }
    rets = (s / s.shift(1)).apply(math.log).dropna().iloc[-21:]
    window = s.iloc[-HISTORY_DAYS:]
    return {
        **moves,
        "realized_vol_21d_annual_pct": round(float(rets.std()) * math.sqrt(252) * 100, 2),
        f"min_{HISTORY_DAYS}d": round(float(window.min()), 4),
        f"max_{HISTORY_DAYS}d": round(float(window.max()), 4),
    }


def _last_decisions(
    session: Session, banks: tuple[str, ...], before: dt.date
) -> list[dict[str, Any]]:
    out = []
    for bank in banks:
        ev = session.scalars(
            select(CbEvent)
            .where(CbEvent.bank == bank, CbEvent.date < before)
            .order_by(CbEvent.date.desc())
            .limit(1)
        ).first()
        if ev is None:
            continue
        added = (ev.statement_diff or {}).get("added") or []
        out.append(
            {
                "bank": bank,
                "date": ev.date.isoformat(),
                "rate_type": ev.rate_type,
                "rate_before_pct": _num(ev.rate_before),
                "rate_after_pct": _num(ev.rate_after),
                "surprise_bps": _num(ev.surprise_bps, 1),
                "hawkish_score": _num(ev.hawkish_score, 2),
                "hawkish_reason": ev.hawkish_reason,
                "new_statement_sentences": [str(x)[:300] for x in added[:MAX_STATEMENT_SENTENCES]],
            }
        )
    return out


def _evidence(session: Session, pair: str) -> dict[str, Any]:
    run_date = session.scalar(
        select(BacktestMetric.run_date)
        .where(BacktestMetric.pair == pair)
        .order_by(BacktestMetric.run_date.desc())
        .limit(1)
    )
    if run_date is None:
        return {}
    rows = session.scalars(
        select(BacktestMetric).where(
            BacktestMetric.pair == pair,
            BacktestMetric.run_date == run_date,
            BacktestMetric.window == WINDOW_RECENT,
            BacktestMetric.model != MODEL_RW,
        )
    ).all()
    return {
        "note": f"walk-forward backtest over the last {BACKTEST_WINDOW_DAYS} trading days",
        "models": [
            {
                "horizon": HORIZON_LABELS.get(r.horizon_days, f"{r.horizon_days}D"),
                "model": r.model,
                "mae_ratio_vs_random_walk": _num(r.mae_ratio_rw, 3),
                "direction_hit_rate": _num(r.hit_rate, 3),
                "diebold_mariano_p": _num(r.dm_pvalue, 3),
            }
            for r in sorted(rows, key=lambda r: (r.horizon_days, r.model))
        ],
    }


def build_context(
    session: Session, pair: PairSpec, run_date: dt.date, served: list[Forecast]
) -> dict[str, Any]:
    """`served` are the run's served rows for the pair, one per horizon."""
    rows = sorted(served, key=lambda r: r.horizon_days)
    first = rows[0]
    spot = float(first.spot)
    spot_date = dt.date.fromisoformat(
        (first.features_json or {}).get("spot_date") or run_date.isoformat()
    )
    longest = rows[-1].features_json or {}
    ctx: dict[str, Any] = {
        "pair": f"{pair.base}/{pair.quote}",
        "quote_convention": f"{pair.quote} per 1 {pair.base}",
        "run_date": run_date.isoformat(),
        "spot": spot,
        "spot_date": spot_date.isoformat(),
        "recent_moves": _recent_moves(session, pair.id, spot_date),
        "statistical_forecast": [
            {
                "horizon": HORIZON_LABELS.get(r.horizon_days, f"{r.horizon_days}D"),
                "days": r.horizon_days,
                "target_date": r.target_date.isoformat(),
                "served_model": r.model,
                "center": _num(r.center),
                "bands": {
                    label: [_num(getattr(r, lo)), _num(getattr(r, hi))]
                    for label, (lo, hi) in BANDS.items()
                },
                "forward_rate_cip": _num((r.features_json or {}).get("forward_rate")),
                "central_bank_meetings_inside": r.meetings_in_horizon,
                "served_reason": (r.features_json or {}).get("served_reason"),
            }
            for r in rows
        ],
        "drivers": {
            "policy_rates_pct": longest.get("policy_rates"),
            "rate_differential_bps": _num(longest.get("rate_diff_bps"), 1),
            "rate_differential_change_21d_bps": _num(longest.get("rate_diff_change_21d_bps"), 1),
            "garch_vol_annual": _num(longest.get("garch_vol_annual")),
            "last_surprise_bps": longest.get("last_surprise_bps"),
            "hawkish_score": longest.get("hawkish_score"),
            "days_to_next_meeting": longest.get("days_to_next_meeting"),
        },
        "last_decisions": _last_decisions(session, pair.banks, run_date),
        "backtest_evidence": _evidence(session, pair.id),
    }
    if pair.quote == "AMD":
        ctx["rub_amd_recent_moves"] = _recent_moves(session, RUBAMD, spot_date)
    return ctx

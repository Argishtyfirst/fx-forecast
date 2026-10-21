"""Weekly report: served models and band calibration, the AI view's live track record,
the latest calls, and pipeline health, as Markdown.

The weekly workflow commits it to docs/reports/. That gives a dated history of how the
models and the AI view are doing, and the commit is repository activity, which keeps GitHub
from disabling the scheduled workflows (it does so after 60 days without activity in a
public repository).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxf.ai.track import track_record
from fxf.api.forecasts import served_models
from fxf.api.health import PIPELINE_JOBS, load_snapshots
from fxf.calendars import CET
from fxf.constants import (
    DISCLAIMER,
    HORIZON_LABELS,
    HORIZONS,
    MODEL_LLM,
    MODEL_RW,
    PAIRS,
    SOURCES,
    WINDOW_RECENT,
)
from fxf.data_access import load_rates
from fxf.models import BacktestMetric, Forecast

LEAN_WORD = {"sell_now": "Sell now", "wait": "Wait", "no_edge": "No clear answer"}
MIN_EDGE = 0.05


def _f(x: float | None, nd: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _pair_name(pair: str) -> str:
    p = PAIRS[pair]
    return f"{p.base}/{p.quote}"


def _backtest_section(session: Session) -> list[str]:
    run_date = session.scalar(select(func.max(BacktestMetric.run_date)))
    if run_date is None:
        return ["## Statistical models", "", "No backtest has run yet.", ""]
    rows = session.scalars(
        select(BacktestMetric).where(
            BacktestMetric.run_date == run_date, BacktestMetric.window == WINDOW_RECENT
        )
    ).all()
    by = {(r.pair, r.horizon_days, r.model): r for r in rows}
    out = [
        "## Statistical models (last 250 trading days)",
        "",
        f"Backtest run {run_date.isoformat()}. Target: the 80% band holds 75-85% of outcomes.",
        "",
        "| Pair | Horizon | Served | 80% band | 50% band | 95% band | Best challenger (MAE ratio, DM p) |",
        "|---|---|---|---|---|---|---|",
    ]
    for pair in PAIRS:
        served = dict(served_models(session, pair))
        for h in HORIZONS:
            model = served.get(h, MODEL_RW)
            m = by.get((pair, h, model))
            challengers = [
                r for (p, hh, mod), r in by.items() if p == pair and hh == h and mod != MODEL_RW
            ]
            best = min(challengers, key=lambda r: r.mae_ratio_rw, default=None)
            best_txt = (
                f"{best.model} ({_f(best.mae_ratio_rw)}, {_f(best.dm_pvalue, 2)})"
                if best
                else "none"
            )
            out.append(
                f"| {_pair_name(pair)} | {HORIZON_LABELS[h]} | {model} | "
                f"{_pct(m.cov80 if m else None)} | {_pct(m.cov50 if m else None)} | "
                f"{_pct(m.cov95 if m else None)} | {best_txt} |"
            )
    return [*out, ""]


def _latest_llm(session: Session, pair: str, h: int) -> Forecast | None:
    return session.scalars(
        select(Forecast)
        .where(Forecast.pair == pair, Forecast.horizon_days == h, Forecast.model == MODEL_LLM)
        .order_by(Forecast.run_date.desc())
        .limit(1)
    ).first()


def _ai_section(session: Session) -> list[str]:
    out = [
        "## AI view (live track record)",
        "",
        "Scored only on forecasts made before the outcome was known. It decides the verdict "
        "only after 250 scored forecasts that meet the promotion rule.",
        "",
        "| Pair | Horizon | Latest call | Chance better if wait | Confidence | Scored | Hit rate | Brier | MAE ratio | Promoted |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    any_row = False
    for pair in PAIRS:
        rates = load_rates(session, pair)
        for h in HORIZONS:
            row = _latest_llm(session, pair, h)
            if row is None:
                continue
            any_row = True
            llm = (row.features_json or {}).get("llm") or {}
            p = float(llm.get("prob_higher", 0.5))
            edge = round(p - 0.5, 6)
            lean = "wait" if edge >= MIN_EDGE else "sell_now" if edge <= -MIN_EDGE else "no_edge"
            tr = track_record(session, pair, h, rates, row.model_version)
            out.append(
                f"| {_pair_name(pair)} | {HORIZON_LABELS[h]} | {LEAN_WORD[lean]} ({row.run_date.isoformat()}) | "
                f"{p:.0%} | {llm.get('confidence', 'n/a')} | {tr.n_scored} of {tr.required} | "
                f"{_pct(tr.hit_rate)} | {_f(tr.brier)} | {_f(tr.mae_ratio_rw)} | "
                f"{'yes' if tr.promoted else 'no'} |"
            )
    if not any_row:
        out = [*out[:2], "The AI view has not run yet (it needs GEMINI_API_KEY).", ""]
        return out
    model = session.scalar(
        select(Forecast.model_version)
        .where(Forecast.model == MODEL_LLM)
        .order_by(Forecast.run_date.desc())
        .limit(1)
    )
    return [*out, "", f"Model and prompt: {model}.", ""]


def _health_section(session: Session) -> list[str]:
    snaps = load_snapshots(session, [*SOURCES, *PIPELINE_JOBS])
    out = [
        "## Pipeline health",
        "",
        "| Job | Last success (UTC) | Latest status |",
        "|---|---|---|",
    ]
    for job, snap in snaps.items():
        last = snap.last_success.strftime("%Y-%m-%d %H:%M") if snap.last_success else "never"
        status = snap.latest.status if snap.latest else "never ran"
        out.append(f"| {job} | {last} | {status} |")
    return [*out, ""]


def build_report(session: Session, today: dt.date) -> str:
    lines = [
        f"# Weekly report, {today.isoformat()}",
        "",
        DISCLAIMER,
        "",
        *_backtest_section(session),
        *_ai_section(session),
        *_health_section(session),
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_report(session: Session, out_dir: Path, today: dt.date | None = None) -> list[Path]:
    """Writes <out_dir>/<date>.md and <out_dir>/latest.md. Returns both paths."""
    day = today or dt.datetime.now(CET).date()
    text = build_report(session, day)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / f"{day.isoformat()}.md", out_dir / "latest.md"]
    for path in paths:
        path.write_text(text)
    return paths

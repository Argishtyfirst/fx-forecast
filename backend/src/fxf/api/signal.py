"""FR-17: "Should I sell my <base> now?" for someone converting the base currency into the
quote currency (selling EUR for AMD on EURAMD, EUR for USD on EURUSD, USD for AMD on USDAMD).

A statistical summary, not financial advice. The served forecast gives the distribution of
the rate at the horizon; the walk-forward backtest says whether that forecast has any edge
over a random walk. A lean (sell now / wait) is shown only when the served model met the
promotion rule AND called the direction better than a coin flip over the last 250 days.
Otherwise the honest answer is "no clear edge": the rate is about as likely to move for
the seller as against them, and the bands show the risk of waiting.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxf.api.schemas import ConversionSignal
from fxf.constants import (
    CURRENCY_BANK,
    HORIZON_LABELS,
    MODEL_RW,
    PROMOTION_DM_PVALUE,
    PROMOTION_MAE_RATIO,
    WINDOW_RECENT,
    PairSpec,
)
from fxf.models import BacktestMetric, Forecast

# |P(better rate) - 0.5| below this is no edge, even from a model with evidence.
MIN_EDGE = 0.05
# The AI view's own call: a lean of SLIGHT_EDGE to MIN_EDGE shows as "leaning".
SLIGHT_EDGE = 0.02


def ai_lean(prob_better_if_wait: float) -> tuple[str, str]:
    """(lean, strength) for the AI view's probability. Rounded so a stated 0.45 is a full
    5-point edge (0.45 - 0.5 is -0.04999... in floating point)."""
    edge = round(prob_better_if_wait - 0.5, 6)
    size = abs(edge)
    if size < SLIGHT_EDGE:
        return "no_edge", "none"
    return ("wait" if edge > 0 else "sell_now"), ("clear" if size >= MIN_EDGE else "slight")


# (minimum directional hit rate, minimum edge, label), strongest first.
CONFIDENCE_LEVELS: tuple[tuple[float, float, Literal["high", "medium"]], ...] = (
    (0.58, 0.10, "high"),
    (0.54, 0.07, "medium"),
)

MODEL_NAMES = {"random_walk": "random walk", "forward": "forward-rate", "lightgbm": "LightGBM"}


def prob_above(spot: float, quantiles: dict[float, float]) -> float:
    """P(rate at the target > spot), interpolating the CDF linearly through the stored
    quantiles (the center is the median). Beyond the outer bands it is clamped to the
    outermost levels, so it never claims more than 97.5% either way."""
    pts = sorted((value, p) for p, value in quantiles.items())
    values = [v for v, _ in pts]
    probs = [p for _, p in pts]
    if spot <= values[0]:
        return 1.0 - probs[0]
    if spot >= values[-1]:
        return 1.0 - probs[-1]
    i = bisect.bisect_right(values, spot)
    v0, v1, p0, p1 = values[i - 1], values[i], probs[i - 1], probs[i]
    cdf = p0 if v1 == v0 else p0 + (p1 - p0) * (spot - v0) / (v1 - v0)
    return 1.0 - cdf


def _quantiles(row: Forecast) -> dict[float, float]:
    return {
        0.025: float(row.q025),
        0.10: float(row.q10),
        0.25: float(row.q25),
        0.50: float(row.center),
        0.75: float(row.q75),
        0.90: float(row.q90),
        0.975: float(row.q975),
    }


def latest_evidence(session: Session, pair: str) -> dict[tuple[int, str], BacktestMetric]:
    """Window-250d metrics of the latest backtest run for the pair, by (horizon, model)."""
    run_date = session.scalar(
        select(func.max(BacktestMetric.run_date)).where(BacktestMetric.pair == pair)
    )
    if run_date is None:
        return {}
    rows = session.scalars(
        select(BacktestMetric).where(
            BacktestMetric.pair == pair,
            BacktestMetric.run_date == run_date,
            BacktestMetric.window == WINDOW_RECENT,
        )
    ).all()
    return {(r.horizon_days, r.model): r for r in rows}


def _confidence(hit_rate: float, edge: float) -> Literal["low", "medium", "high"]:
    for min_hit, min_edge, label in CONFIDENCE_LEVELS:
        if hit_rate >= min_hit and edge >= min_edge:
            return label
    return "low"


TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class AiBasis:
    """What the AI view contributes when its live track record meets the promotion rule."""

    prob_better_if_wait: float
    expected_change_pct: float
    model: str
    hit_rate: float | None
    dm_pvalue: float | None
    mae_ratio_rw: float | None
    n_scored: int


def _fmt(value: float, spot: float) -> str:
    return f"{value:,.4f}" if spot < 10 else f"{value:,.2f}"


def carry(pair: PairSpec, row: Forecast) -> tuple[float, float, float] | None:
    """(per year %, over the horizon %, quote units per 1 base over the horizon) for holding
    the quote currency instead of the base, at the policy rates stored with the forecast."""
    rates = (row.features_json or {}).get("policy_rates") or {}
    try:
        i_quote = float(rates[CURRENCY_BANK[pair.quote]])
        i_base = float(rates[CURRENCY_BANK[pair.base]])
    except (KeyError, TypeError, ValueError):
        return None
    per_year = i_quote - i_base
    over = per_year * row.horizon_days / TRADING_DAYS_PER_YEAR
    return per_year, over, float(row.spot) * over / 100.0


def _carry_sentence(
    pair: PairSpec, label: str, spot: float, c: tuple[float, float, float] | None
) -> str:
    if c is None:
        return ""
    per_year, _, amount = c
    if abs(per_year) < 1e-9:
        return " Policy rates are equal, so holding either currency pays about the same."
    richer, poorer = (pair.quote, pair.base) if per_year > 0 else (pair.base, pair.quote)
    return (
        f" Holding {richer} pays about {abs(per_year):.2f}%/yr more than {poorer} at policy "
        f"rates (about {_fmt(abs(amount), spot)} {pair.quote} per {pair.base} over {label})."
    )


def build_signal(
    pair: PairSpec,
    row: Forecast,
    evidence: BacktestMetric | None,
    ai: AiBasis | None = None,
) -> ConversionSignal:
    """The verdict comes from the served statistical forecast, unless `ai` is given (the AI
    view met the promotion rule on live forecasts), in which case the AI view decides."""
    spot = float(row.spot)
    label = HORIZON_LABELS.get(row.horizon_days, f"{row.horizon_days}D")
    lo, hi = float(row.q10), float(row.q90)
    risk = f"80% of the time you'd get {_fmt(lo, spot)} to {_fmt(hi, spot)} {pair.quote} per {pair.base}."
    c = carry(pair, row)
    interest = _carry_sentence(pair, label, spot, c)

    if ai is not None:
        source: Literal["statistical", "ai"] = "ai"
        p = ai.prob_better_if_wait
        expected = ai.expected_change_pct
        model, hit, dm, ratio, n = ai.model, ai.hit_rate, ai.dm_pvalue, ai.mae_ratio_rw, ai.n_scored
        beats_rw = True
        name = "AI view"
    else:
        source = "statistical"
        p = prob_above(spot, _quantiles(row))
        expected = (float(row.center) / spot - 1.0) * 100.0
        model = row.model
        hit = evidence.hit_rate if evidence is not None else None
        dm = evidence.dm_pvalue if evidence is not None else None
        ratio = evidence.mae_ratio_rw if evidence is not None else None
        n = evidence.n_obs if evidence is not None else None
        beats_rw = (
            row.model != MODEL_RW
            and ratio is not None
            and dm is not None
            and ratio < PROMOTION_MAE_RATIO
            and dm < PROMOTION_DM_PVALUE
        )
        name = f"{MODEL_NAMES.get(row.model, row.model)} model"
    edge = round(abs(p - 0.5), 6)  # 0.45 must count as a full 5-point edge

    action: Literal["sell_now", "wait", "no_edge"] = "no_edge"
    confidence: Literal["none", "low", "medium", "high"] = "none"
    if not beats_rw:
        summary = f"Waiting {label} doesn't improve your expected rate; it adds risk: {risk}"
    elif hit is None or hit <= 0.5:
        summary = (
            f"No reliable direction: the {name} is more accurate than a random walk at {label} "
            f"but calls the direction no better than a coin flip. {risk}"
        )
    elif edge < MIN_EDGE:
        confidence = "low"
        summary = f"No clear edge: {p:.0%} chance of a better rate after {label}. {risk}"
    else:
        confidence = _confidence(hit, edge)
        track = f"{name}, right on direction {hit:.0%} of the last {n} forecasts"
        if p > 0.5:
            action = "wait"
            summary = f"Wait: {p:.0%} chance of a better {pair.base}/{pair.quote} rate after {label} ({track}). {risk}"
        else:
            action = "sell_now"
            summary = f"Sell now: {1 - p:.0%} chance the {pair.base}/{pair.quote} rate is worse after {label} ({track}). {risk}"

    return ConversionSignal(
        action=action,
        verdict_source=source,
        sell=pair.base,
        receive=pair.quote,
        prob_better_if_wait=round(p, 4),
        expected_change_pct=round(expected, 4),
        downside_p10_rate=lo,
        upside_p90_rate=hi,
        risk_half_width_pct=round((hi - lo) / 2.0 / spot * 100.0, 4),
        carry_pct_per_year=None if c is None else round(c[0], 4),
        carry_over_horizon_pct=None if c is None else round(c[1], 4),
        carry_amount=None if c is None else round(c[2], 6),
        confidence=confidence,
        model=model,
        model_beats_random_walk=beats_rw,
        hit_rate=hit,
        dm_pvalue=dm,
        mae_ratio_rw=ratio,
        n_obs=n,
        summary=summary + interest,
    )

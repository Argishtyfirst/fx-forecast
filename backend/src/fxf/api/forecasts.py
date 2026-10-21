"""Forecast reads for /api/forecasts/{pair}/latest and /api/forecasts/{pair}.

The "latest" run is the most recent run_date with served rows for the pair. A forecast
job that fails leaves either no rows or no served rows for its date, so the last good
run stays visible (NFR-04).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxf.ai.track import track_record
from fxf.api import convert
from fxf.api.health import stale_sources_for_pair
from fxf.api.schemas import (
    AiView,
    Drivers,
    ForecastRow,
    ForecastRunResponse,
    HorizonForecast,
    LatestForecastResponse,
)
from fxf.api.signal import MIN_EDGE, AiBasis, build_signal, latest_evidence
from fxf.constants import BANDS, DISCLAIMER, HORIZON_LABELS, MODEL_LLM, MODELS, PairSpec
from fxf.data_access import load_rates
from fxf.models import Forecast, Rate

MAX_RUN_DATES = 60


def latest_served_run_date(session: Session, pair: str) -> dt.date | None:
    return session.scalar(
        select(func.max(Forecast.run_date)).where(Forecast.pair == pair, Forecast.served.is_(True))
    )


def served_models(session: Session, pair: str) -> set[tuple[int, str]]:
    """(horizon_days, model) served in the latest forecast run of the pair."""
    run_date = latest_served_run_date(session, pair)
    if run_date is None:
        return set()
    rows = session.execute(
        select(Forecast.horizon_days, Forecast.model).where(
            Forecast.pair == pair, Forecast.run_date == run_date, Forecast.served.is_(True)
        )
    )
    return {(h, m) for h, m in rows}


def model_order(model: str) -> tuple[int, str]:
    """Sort key: constants.MODELS order, then unknown models by name."""
    return (MODELS.index(model) if model in MODELS else len(MODELS), model)


def drivers_from_features(features: Mapping[str, Any] | None, banks: Iterable[str] = ()) -> Drivers:
    """forecasts.features_json -> Drivers (FR-15). Missing or malformed values become None;
    the per-bank maps always list `banks`."""
    f = features if isinstance(features, Mapping) else {}
    banks = tuple(banks)
    return Drivers(
        rate_diff_bps=convert.num(f.get("rate_diff_bps")),
        rate_diff_change_21d_bps=convert.num(f.get("rate_diff_change_21d_bps")),
        policy_rates=convert.num_map(f.get("policy_rates"), banks),
        forward_rate=convert.num(f.get("forward_rate")),
        garch_vol_annual=convert.num(f.get("garch_vol_annual")),
        horizon_sigma=convert.num(f.get("horizon_sigma")),
        event_extra_variance=convert.num(f.get("event_extra_variance")),
        last_surprise_bps=convert.num_map(f.get("last_surprise_bps"), banks),
        hawkish_score=convert.num_map(f.get("hawkish_score"), banks),
        days_to_next_meeting=convert.int_map(f.get("days_to_next_meeting"), banks),
        served_reason=convert.text(f.get("served_reason")),
    )


def _bands(row: Forecast) -> dict[str, tuple[float, float]]:
    return {
        label: (float(getattr(row, lo)), float(getattr(row, hi)))
        for label, (lo, hi) in BANDS.items()
    }


def ai_views(session: Session, pair: PairSpec, run_date: dt.date) -> dict[int, AiView]:
    """The AI view of the run (model "llm"), with its live track record, by horizon."""
    rows = session.scalars(
        select(Forecast).where(
            Forecast.pair == pair.id, Forecast.run_date == run_date, Forecast.model == MODEL_LLM
        )
    ).all()
    if not rows:
        return {}
    rates = load_rates(session, pair.id)
    out: dict[int, AiView] = {}
    for row in rows:
        llm = (row.features_json or {}).get("llm") or {}
        try:
            # Rounded so a stated 0.45 counts as the full 5-point edge (0.45 - 0.5 is
            # -0.04999... in floating point).
            edge = round(float(llm["prob_higher"]) - 0.5, 6)
            lean = "wait" if edge >= MIN_EDGE else "sell_now" if edge <= -MIN_EDGE else "no_edge"
            out[row.horizon_days] = AiView(
                provider=llm["provider"],
                model=llm["model"],
                prompt_version=llm["prompt_version"],
                generated_at=llm["generated_at"],
                prob_better_if_wait=llm["prob_higher"],
                expected_change_pct=llm["expected_change_pct"],
                lean=lean,
                confidence=llm["confidence"],
                reasoning=llm["reasoning"],
                track_record=track_record(
                    session, pair.id, row.horizon_days, rates, row.model_version
                ),
            )
        except (KeyError, ValueError):
            continue  # a malformed row is skipped rather than breaking the response
    return out


def _ai_basis(view: AiView | None) -> AiBasis | None:
    """The AI view decides the verdict only once its live track record is promoted."""
    if view is None or not view.track_record.promoted:
        return None
    tr = view.track_record
    return AiBasis(
        prob_better_if_wait=view.prob_better_if_wait,
        expected_change_pct=view.expected_change_pct,
        model=MODEL_LLM,
        hit_rate=tr.hit_rate,
        dm_pvalue=tr.dm_pvalue,
        mae_ratio_rw=tr.mae_ratio_rw,
        n_scored=tr.n_scored,
    )


def _spot_date(session: Session, row: Forecast) -> dt.date:
    """features_json["spot_date"], else the latest stored rate on or before the run date."""
    from_features = convert.iso_date((row.features_json or {}).get("spot_date"))
    if from_features is not None:
        return from_features
    stored = session.scalar(
        select(func.max(Rate.date)).where(Rate.pair == row.pair, Rate.date <= row.run_date)
    )
    return stored or row.run_date


def build_latest(
    session: Session, pair: PairSpec, now: dt.datetime
) -> LatestForecastResponse | None:
    run_date = latest_served_run_date(session, pair.id)
    if run_date is None:
        return None
    rows = session.scalars(
        select(Forecast)
        .where(Forecast.pair == pair.id, Forecast.run_date == run_date, Forecast.served.is_(True))
        .order_by(Forecast.horizon_days, Forecast.id)
    ).all()
    by_horizon: dict[int, Forecast] = {}
    for row in rows:
        by_horizon.setdefault(row.horizon_days, row)  # one served row per horizon
    first = by_horizon[min(by_horizon)]
    evidence = latest_evidence(session, pair.id)
    ai = ai_views(session, pair, run_date)
    return LatestForecastResponse(
        pair=pair.id,
        as_of=run_date,
        spot=float(first.spot),
        spot_date=_spot_date(session, first),
        disclaimer=DISCLAIMER,
        horizons=[
            HorizonForecast(
                days=h,
                label=HORIZON_LABELS.get(h, f"{h}D"),
                target_date=row.target_date,
                model=row.model,
                model_version=row.model_version,
                center=float(row.center),
                bands=_bands(row),
                meetings=convert.meetings(row.meetings_in_horizon),
                drivers=drivers_from_features(row.features_json, pair.banks),
                signal=build_signal(pair, row, evidence.get((h, row.model)), _ai_basis(ai.get(h))),
                ai_view=ai.get(h),
            )
            for h, row in sorted(by_horizon.items())
        ],
        stale_sources=stale_sources_for_pair(session, pair, now),
    )


def _row_out(row: Forecast) -> ForecastRow:
    return ForecastRow(
        model=row.model,
        model_version=row.model_version,
        horizon_days=row.horizon_days,
        target_date=row.target_date,
        spot=float(row.spot),
        center=float(row.center),
        q025=float(row.q025),
        q10=float(row.q10),
        q25=float(row.q25),
        q75=float(row.q75),
        q90=float(row.q90),
        q975=float(row.q975),
        served=row.served,
        meetings=convert.meetings(row.meetings_in_horizon),
        git_sha=row.git_sha,
    )


class NoForecast(LookupError):
    """No forecast rows for the pair (or for the requested run date)."""


def build_run(session: Session, pair: PairSpec, run_date: dt.date | None) -> ForecastRunResponse:
    """All model rows of one run. The default run is the latest served one (as /latest),
    or the latest run of any kind when none was served."""
    dates = list(
        session.scalars(
            select(Forecast.run_date)
            .where(Forecast.pair == pair.id)
            .distinct()
            .order_by(Forecast.run_date.desc())
            .limit(MAX_RUN_DATES)
        )
    )
    if not dates:
        raise NoForecast("no forecast yet")
    if run_date is None:
        run_date = latest_served_run_date(session, pair.id) or dates[0]
    rows = session.scalars(
        select(Forecast).where(Forecast.pair == pair.id, Forecast.run_date == run_date)
    ).all()
    if not rows:
        raise NoForecast(f"no forecast for {pair.id} on {run_date.isoformat()}")
    rows = sorted(rows, key=lambda r: (r.horizon_days, model_order(r.model)))
    return ForecastRunResponse(
        pair=pair.id,
        run_date=run_date,
        available_run_dates=dates,
        rows=[_row_out(r) for r in rows],
    )

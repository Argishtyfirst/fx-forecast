"""The read-only REST API (spec: API). Every route is GET and reads Postgres only."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict
from typing import Annotated, Final

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxf.api import convert
from fxf.api.deps import get_now, get_pair, get_session, get_today, invalid_query
from fxf.api.forecasts import NoForecast, build_latest, build_run, model_order, served_models
from fxf.api.health import build_health
from fxf.api.metrics import CONTENT_TYPE, collect_metrics
from fxf.api.schemas import (
    AiAnalysisOut,
    AiAnalysisText,
    AiTrackRow,
    BacktestMetricOut,
    BacktestResponse,
    BacktestTargets,
    BankReactionSummaryOut,
    DecisionOut,
    EventsResponse,
    EventWindowMetricOut,
    ForecastRunResponse,
    HealthResponse,
    HorizonOut,
    LatestForecastResponse,
    MeetingReactionOut,
    MeetingStudyResponse,
    PairOut,
    PairsResponse,
    PathPoint,
    QuotesResponse,
    RatePoint,
    RatesResponse,
    StatementDiff,
    TypicalPathPoint,
    UpcomingMeeting,
)
from fxf.constants import (
    BANKS,
    HORIZON_LABELS,
    HORIZONS,
    MODEL_LLM,
    PAIRS,
    PROMOTION_DM_PVALUE,
    PROMOTION_MAE_RATIO,
    WINDOW_FULL,
    WINDOW_RECENT,
    PairSpec,
)
from fxf.models import AiAnalysis, BacktestMetric, CbEvent, CbMeeting, Forecast, Rate

router = APIRouter(prefix="/api")

SessionDep = Annotated[Session, Depends(get_session)]
PairDep = Annotated[PairSpec, Depends(get_pair)]
NowDep = Annotated[dt.datetime, Depends(get_now)]
TodayDep = Annotated[dt.date, Depends(get_today)]

PAIR_SOURCE_LABELS: Final[dict[str, str]] = {
    "EURUSD": "ECB reference rate",
    "USDAMD": "CBA daily average rate",
    "EURAMD": "CBA daily average rate",
    "RUBAMD": "CBA daily average rate",
    "GBPAMD": "CBA daily average rate",
    "GBPUSD": "ECB reference rates (EUR/USD and EUR/GBP crossed)",
    "RUBUSD": "CBA daily average rates (RUB/AMD divided by USD/AMD)",
}
RATES_DEFAULT_DAYS: Final = 365
EVENTS_DEFAULT_YEARS: Final = 3
WINDOW_ORDER: Final[dict[str, int]] = {WINDOW_RECENT: 0, WINDOW_FULL: 1}


@router.get("/pairs", response_model=PairsResponse)
def list_pairs() -> PairsResponse:
    return PairsResponse(
        pairs=[
            PairOut(
                id=p.id,
                base=p.base,
                quote=p.quote,
                source=p.source,
                source_label=PAIR_SOURCE_LABELS.get(p.id, p.source),
                banks=list(p.banks),
            )
            for p in PAIRS.values()
        ],
        horizons=[HorizonOut(days=h, label=HORIZON_LABELS[h]) for h in HORIZONS],
    )


@router.get("/rates/{pair}", response_model=RatesResponse)
def get_rates(
    pair: PairDep,
    session: SessionDep,
    from_: Annotated[
        dt.date | None, Query(alias="from", description="Default: `to` minus 365 days")
    ] = None,
    to: Annotated[dt.date | None, Query(description="Default: latest stored date")] = None,
) -> RatesResponse:
    if from_ is not None and to is not None and from_ > to:
        raise invalid_query("from", from_.isoformat(), "'from' must not be after 'to'")
    if to is None:
        to = session.scalar(select(func.max(Rate.date)).where(Rate.pair == pair.id))
    if to is None:
        return RatesResponse(pair=pair.id, source=pair.source, rates=[])
    start = from_ if from_ is not None else to - dt.timedelta(days=RATES_DEFAULT_DAYS)
    rows = session.execute(
        select(Rate.date, Rate.rate)
        .where(Rate.pair == pair.id, Rate.date >= start, Rate.date <= to)
        .order_by(Rate.date)
    )
    return RatesResponse(
        pair=pair.id,
        source=pair.source,
        rates=[RatePoint(date=d, rate=float(r)) for d, r in rows],
    )


@router.get("/forecasts/{pair}/latest", response_model=LatestForecastResponse)
def get_latest_forecast(pair: PairDep, session: SessionDep, now: NowDep) -> LatestForecastResponse:
    body = build_latest(session, pair, now)
    if body is None:
        raise HTTPException(status_code=404, detail="no forecast yet")
    return body


@router.get("/forecasts/{pair}", response_model=ForecastRunResponse)
def get_forecast_run(
    pair: PairDep,
    session: SessionDep,
    run_date: Annotated[dt.date | None, Query(description="Default: latest run")] = None,
) -> ForecastRunResponse:
    try:
        return build_run(session, pair, run_date)
    except NoForecast as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/backtests/{pair}", response_model=BacktestResponse)
def get_backtests(
    pair: PairDep,
    session: SessionDep,
    horizon: Annotated[int | None, Query(description="1, 5 or 21; default: all")] = None,
) -> BacktestResponse:
    if horizon is not None and horizon not in HORIZONS:
        raise invalid_query(
            "horizon", horizon, f"horizon must be one of {', '.join(map(str, HORIZONS))}"
        )
    run_date = session.scalar(
        select(func.max(BacktestMetric.run_date)).where(BacktestMetric.pair == pair.id)
    )
    ai_track, ai_analysis = _ai_backtest_parts(session, pair, horizon)
    if run_date is None:
        return BacktestResponse(
            pair=pair.id,
            run_date=None,
            targets=BacktestTargets(),
            metrics=[],
            ai_track=ai_track,
            ai_analysis=ai_analysis,
        )
    q = select(BacktestMetric).where(
        BacktestMetric.pair == pair.id, BacktestMetric.run_date == run_date
    )
    if horizon is not None:
        q = q.where(BacktestMetric.horizon_days == horizon)
    all_rows = list(session.scalars(q))
    events = [m for m in all_rows if m.window.startswith(EVENT_WINDOW_PREFIX)]
    rows = sorted(
        (m for m in all_rows if not m.window.startswith(EVENT_WINDOW_PREFIX)),
        key=lambda m: (
            m.horizon_days,
            model_order(m.model),
            WINDOW_ORDER.get(m.window, len(WINDOW_ORDER)),
            m.window,
        ),
    )
    served = served_models(session, pair.id)
    return BacktestResponse(
        pair=pair.id,
        run_date=run_date,
        targets=BacktestTargets(),
        metrics=[
            BacktestMetricOut(
                horizon_days=m.horizon_days,
                model=m.model,
                window=m.window,
                n_obs=m.n_obs,
                start_date=m.start_date,
                end_date=m.end_date,
                mae=m.mae,
                mae_ratio_rw=m.mae_ratio_rw,
                hit_rate=m.hit_rate,
                cov50=m.cov50,
                cov80=m.cov80,
                cov95=m.cov95,
                pinball=m.pinball,
                pinball_ref=m.pinball_ref,
                dm_pvalue=m.dm_pvalue,
                promoted=is_promoted(m),
                served=(m.horizon_days, m.model) in served,
            )
            for m in rows
        ],
        event_metrics=[
            EventWindowMetricOut(
                horizon_days=m.horizon_days,
                model=m.model,
                bank=m.window[len(EVENT_WINDOW_PREFIX) :],
                n_obs=m.n_obs,
                mae_ratio_rw=m.mae_ratio_rw,
                hit_rate=m.hit_rate,
                cov50=m.cov50,
                cov80=m.cov80,
                cov95=m.cov95,
            )
            for m in sorted(events, key=lambda m: (m.horizon_days, model_order(m.model), m.window))
        ],
        ai_track=ai_track,
        ai_analysis=ai_analysis,
    )


# Backtest windows split by meetings inside the horizon: "evt_FED", "evt_ECB", "evt_CBA",
# "evt_none" (fxf.backtest.runner).
EVENT_WINDOW_PREFIX: Final = "evt_"


def _ai_backtest_parts(
    session: Session, pair: PairSpec, horizon: int | None
) -> tuple[list[AiTrackRow], AiAnalysisOut | None]:
    """The AI view's live record per horizon and its latest weekly analysis for the pair."""
    from fxf.ai.track import track_record
    from fxf.data_access import load_rates

    rates = load_rates(session, pair.id)
    track = []
    for h in [horizon] if horizon else list(HORIZONS):
        version = session.scalar(
            select(Forecast.model_version)
            .where(
                Forecast.pair == pair.id, Forecast.horizon_days == h, Forecast.model == MODEL_LLM
            )
            .order_by(Forecast.run_date.desc())
            .limit(1)
        )
        track.append(
            AiTrackRow(
                horizon_days=h,
                model_version=version,
                track_record=track_record(session, pair.id, h, rates, version),
            )
        )
    row = session.scalars(
        select(AiAnalysis)
        .where(AiAnalysis.pair == pair.id, AiAnalysis.kind == "event_study")
        .order_by(AiAnalysis.run_date.desc())
        .limit(1)
    ).first()
    analysis = None
    if row is not None:
        c = row.content or {}
        analysis = AiAnalysisOut(
            run_date=row.run_date,
            provider=c.get("provider", "gemini"),
            model=row.model,
            prompt_version=row.prompt_version,
            generated_at=c.get("generated_at") or row.created_at,
            headline=c.get("headline", ""),
            for_you=c.get("for_you", ""),
            points=list(c.get("points") or []),
            watch_next=c.get("watch_next", ""),
            i18n={k: AiAnalysisText(**v) for k, v in (c.get("i18n") or {}).items()} or None,
        )
    return track, analysis


def is_promoted(m: BacktestMetric) -> bool:
    """Promotion rule (spec: Evaluation): MAE ratio < 0.98 and DM p < 0.10 over 250 days."""
    return (
        m.window == WINDOW_RECENT
        and m.mae_ratio_rw < PROMOTION_MAE_RATIO
        and m.dm_pvalue is not None
        and m.dm_pvalue < PROMOTION_DM_PVALUE
    )


@router.get("/events", response_model=EventsResponse)
def get_events(
    session: SessionDep,
    today: TodayDep,
    bank: Annotated[str | None, Query(description="FED, ECB or CBA; default: all")] = None,
    from_: Annotated[
        dt.date | None, Query(alias="from", description="Default: today minus 3 years")
    ] = None,
) -> EventsResponse:
    bank_id = None
    if bank is not None:
        bank_id = bank.strip().upper()
        if bank_id not in BANKS:
            raise invalid_query("bank", bank, f"bank must be one of {', '.join(BANKS)}")
    start = from_ if from_ is not None else today - relativedelta(years=EVENTS_DEFAULT_YEARS)
    dq = select(CbEvent).where(CbEvent.date >= start)
    mq = select(CbMeeting).where(CbMeeting.date >= today)
    if bank_id is not None:
        dq = dq.where(CbEvent.bank == bank_id)
        mq = mq.where(CbMeeting.bank == bank_id)
    decisions = session.scalars(dq.order_by(CbEvent.date.desc(), CbEvent.bank)).all()
    meetings = session.scalars(mq.order_by(CbMeeting.date, CbMeeting.bank)).all()
    return EventsResponse(
        decisions=[_decision_out(e) for e in decisions],
        upcoming=[
            UpcomingMeeting(
                bank=m.bank,
                date=m.date,
                scheduled=bool(m.scheduled),
                days_until=(m.date - today).days,
            )
            for m in meetings
        ],
    )


def _statement_diff(value: object) -> StatementDiff | None:
    if not isinstance(value, dict):
        return None
    return StatementDiff(
        added=[str(s) for s in value.get("added") or [] if s is not None],
        removed=[str(s) for s in value.get("removed") or [] if s is not None],
        previous_event_id=convert.integer(value.get("previous_event_id")),
    )


def _rates(value: object) -> dict[str, dict[str, float | None]] | None:
    if not isinstance(value, dict):
        return None
    return {str(k): convert.num_map(v) for k, v in value.items() if isinstance(v, dict)}


def _decision_out(e: CbEvent) -> DecisionOut:
    return DecisionOut(
        id=e.id,
        bank=e.bank,
        date=e.date,
        rate_type=e.rate_type,
        rate_before=convert.num(e.rate_before),
        rate_after=convert.num(e.rate_after),
        expected=convert.num(e.expected),
        expected_source=e.expected_source,
        surprise_bps=convert.num(e.surprise_bps),
        rates=_rates(e.rates_json),
        statement_url=e.statement_url,
        statement_text=e.statement_text,
        statement_diff=_statement_diff(e.statement_diff),
        hawkish_score=convert.num(e.hawkish_score),
        hawkish_reason=e.hawkish_reason,
        scorer_version=e.scorer_version,
    )


@router.get("/meetings/{pair}", response_model=MeetingStudyResponse)
def meeting_study(
    pair: PairDep,
    session: SessionDep,
    today: TodayDep,
    lookback_days: Annotated[int, Query(ge=60, le=3650)] = 365,
) -> MeetingStudyResponse:
    """How the pair moved around each meeting of its banks: run-up, reaction, follow-through."""
    from fxf.events.study import PATH_DAYS, RUN_DAYS, load_study

    as_of = session.scalar(select(func.max(Rate.date)).where(Rate.pair == pair.id)) or today
    summaries, reactions = load_study(session, pair, as_of, lookback_days)
    return MeetingStudyResponse(
        pair=pair.id,
        as_of=as_of,
        lookback_days=lookback_days,
        window_days=RUN_DAYS,
        path_days=PATH_DAYS,
        banks=[
            BankReactionSummaryOut(
                **{
                    **asdict(s),
                    "typical_path": [
                        TypicalPathPoint(offset=k, mean_abs_pct=v, meetings=n)
                        for k, v, n in s.typical_path
                    ],
                }
            )
            for s in summaries
        ],
        meetings=[
            MeetingReactionOut(
                **{**asdict(r), "path": [PathPoint(offset=k, date=d, pct=v) for k, d, v in r.path]}
            )
            for r in reversed(reactions)
        ],
    )


@router.get("/quotes/{pair}", response_model=QuotesResponse)
def provider_quotes(
    pair: PairDep,
    session: SessionDep,
    now: NowDep,
    amount: Annotated[float, Query(gt=0, le=10_000_000)] = 1000,
) -> QuotesResponse:
    """Where to convert today: bank and transfer service rates for an amount of the base."""
    from fxf.quotes.service import QUOTE_PAIRS, build_quotes

    if pair.id not in QUOTE_PAIRS:
        raise HTTPException(status_code=404, detail="provider quotes exist for dram pairs only")
    return build_quotes(session, pair.id, amount, now)


@router.get("/health", response_model=HealthResponse)
def get_health(session: SessionDep, now: NowDep) -> HealthResponse:
    return build_health(session, now)


@router.get("/metrics", response_class=Response, responses={200: {"content": {CONTENT_TYPE: {}}}})
def get_metrics(session: SessionDep, now: NowDep) -> Response:
    """Prometheus text exposition (NFR-05)."""
    return Response(content=collect_metrics(session, now), media_type=CONTENT_TYPE)

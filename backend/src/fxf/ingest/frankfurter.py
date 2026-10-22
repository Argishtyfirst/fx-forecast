"""Daily reference rates from Frankfurter (FR-01 to FR-03).

Source frankfurter_ecb stores EURUSD and GBPUSD (ECB reference rates; Frankfurter crosses
EUR/USD with EUR/GBP for GBP/USD). Source frankfurter_cba stores USDAMD, EURAMD, RUBAMD and
GBPAMD (CBA daily averages), then derives RUBUSD = RUBAMD / USDAMD on the dates both exist:
Frankfurter's own RUB/USD cross is rounded to 5 decimals, a 0.08% step.

A pair with no rows loads its full history (FR-02). Otherwise the job refetches
[last stored date - 10 days, today] and upserts, which picks up late fixes (FR-03).
After 17:00 CET on a working day the job fails if a pair still lacks today's rate
(FR-01); the failure alerts, /api/health shows the source as stale, and the next
scheduled run fills the gap.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy import Engine

from fxf import http
from fxf.calendars import CET, PAIR_CALENDAR, is_trading_day, is_working_day
from fxf.constants import (
    EURAMD,
    EURUSD,
    GBPAMD,
    GBPUSD,
    RUBAMD,
    RUBUSD,
    SOURCE_FRANKFURTER_CBA,
    SOURCE_FRANKFURTER_ECB,
    USDAMD,
    PairSpec,
)
from fxf.data_access import load_rates
from fxf.db import session_scope
from fxf.http import SchemaError, SourceError
from fxf.ingest.store import (
    Point,
    latest_rate_date,
    raise_collected,
    unique_points,
    window_meta,
    write_rates,
)
from fxf.jobs import RunContext
from fxf.logging_setup import get_logger

log = get_logger(__name__)

TIMESERIES_URL: Final = "https://api.frankfurter.dev/v2/rates"
# Earliest dates asked for on a first run; the providers start in 1999 (ECB) and 2000 (CBA).
HISTORY_START: Final[dict[str, dt.date]] = {"ECB": dt.date(1999, 1, 1), "CBA": dt.date(1990, 1, 1)}
WINDOW_DAYS: Final = 10
# FR-01: from this local time on a working day, today's rate must be stored.
PUBLISH_DEADLINE_CET: Final = dt.time(17, 0)


@dataclass(frozen=True)
class RateSeries:
    pair: str
    base: str
    quote: str
    provider: str


def _series(p: PairSpec) -> RateSeries:
    return RateSeries(p.id, p.base, p.quote, p.provider)


SERIES: Final[dict[str, tuple[RateSeries, ...]]] = {
    SOURCE_FRANKFURTER_ECB: (_series(EURUSD), _series(GBPUSD)),
    SOURCE_FRANKFURTER_CBA: (_series(USDAMD), _series(EURAMD), _series(RUBAMD), _series(GBPAMD)),
}


class FrankfurterRate(BaseModel):
    """One row of GET /v2/rates. Extra fields are tolerated; missing or mistyped ones are not."""

    date: dt.date
    base: str
    quote: str
    rate: Decimal = Field(gt=0, allow_inf_nan=False)


TIMESERIES: Final = TypeAdapter(list[FrankfurterRate])


class RateNotPublishedError(SourceError):
    """After the publication deadline, today's rate is still missing for a pair."""


def parse_timeseries(source: str, payload: object, series: RateSeries) -> list[Point]:
    """Validate a /v2/rates body for one base/quote pair."""
    return _points(source, http.validate(source, payload, TIMESERIES), series)


def fetch_timeseries(source: str, series: RateSeries, start: dt.date, end: dt.date) -> list[Point]:
    params = {
        "base": series.base,
        "quotes": series.quote,
        "providers": series.provider,
        "from": start.isoformat(),
        "to": end.isoformat(),
    }
    rows = http.fetch_json(source, TIMESERIES_URL, TIMESERIES, params=params)
    return _points(source, rows, series)


def _points(source: str, rows: list[FrankfurterRate], series: RateSeries) -> list[Point]:
    for r in rows:
        if (r.base, r.quote) != (series.base, series.quote):
            raise SchemaError(
                f"{source}: expected {series.base}/{series.quote}, got {r.base}/{r.quote} on {r.date}"
            )
    return unique_points(source, (Point(r.date, r.rate) for r in rows))


def window(last: dt.date | None, provider: str, today: dt.date) -> dt.date:
    """Start date of the request: full history for an empty pair, else a 10-day overlap."""
    if last is None:
        return HISTORY_START[provider]
    return min(last - dt.timedelta(days=WINDOW_DAYS), today)


def check_published(latest: dict[str, dt.date | None], now: dt.datetime) -> None:
    """FR-01: on a working day after 17:00 CET, each pair trading today must have today's rate.

    Feature-only series (RUBAMD) have no calendar here and are not checked.
    """
    local = now.astimezone(CET)
    today = local.date()
    if not is_working_day(today) or local.time() < PUBLISH_DEADLINE_CET:
        return
    missing = [
        pair
        for pair, last in latest.items()
        if pair in PAIR_CALENDAR
        and is_trading_day(PAIR_CALENDAR[pair], today)
        and (last is None or last < today)
    ]
    if missing:
        detail = ", ".join(f"{p} (latest stored {latest[p]})" for p in missing)
        names = " and ".join(missing)
        raise RateNotPublishedError(
            f"today's {names} rate is not published yet ({today}, after "
            f"{PUBLISH_DEADLINE_CET:%H:%M} CET): {detail}"
        )


def ingest(
    source: str,
    ctx: RunContext,
    *,
    engine: Engine | None,
    now: dt.datetime,
    full: bool = False,
) -> None:
    """Fetch and upsert every series of a Frankfurter source, then apply the FR-01 check.

    Each series is committed on its own, so a broken RUBAMD request never loses USDAMD,
    and rows that were published are stored even when the job then fails FR-01.
    """
    today = now.astimezone(CET).date()
    latest: dict[str, dt.date | None] = {}
    errors: list[tuple[str, Exception]] = []
    for series in SERIES[source]:
        try:
            last = None if full else latest_rate_date(engine, series.pair)
            start = window(last, series.provider, today)
            points = fetch_timeseries(source, series, start, today)
            written = write_rates(engine, series.pair, source, points, now)
        except Exception as exc:
            log.error(
                "rate ingest failed", extra={"job": source, "pair": series.pair, "error": str(exc)}
            )
            ctx.meta[series.pair] = {"error": f"{type(exc).__name__}: {exc}"}
            errors.append((series.pair, exc))
            continue
        ctx.rows_written += written
        ctx.meta[series.pair] = window_meta(
            start, points, written=written, mode="history" if last is None else "window"
        )
        latest[series.pair] = latest_rate_date(engine, series.pair)
        log.info(
            "rates ingested",
            extra={"job": source, "pair": series.pair, "from": start.isoformat(), "rows": written},
        )
    if source == SOURCE_FRANKFURTER_CBA:
        try:
            written = derive_rubusd(engine, now, full=full)
        except Exception as exc:
            log.error(
                "rate derive failed", extra={"job": source, "pair": RUBUSD.id, "error": str(exc)}
            )
            ctx.meta[RUBUSD.id] = {"error": f"{type(exc).__name__}: {exc}"}
            errors.append((RUBUSD.id, exc))
        else:
            ctx.rows_written += written
            ctx.meta[RUBUSD.id] = {"derived": written}
            latest[RUBUSD.id] = latest_rate_date(engine, RUBUSD.id)
    raise_collected(errors)
    check_published(latest, now)


def derive_rubusd(engine: Engine | None, now: dt.datetime, *, full: bool = False) -> int:
    """RUBUSD = RUBAMD / USDAMD on every date both are stored (the last WINDOW_DAYS unless
    the series is empty or full is set), rounded to 8 decimals."""
    last = None if full else latest_rate_date(engine, RUBUSD.id)
    start = None if last is None else last - dt.timedelta(days=WINDOW_DAYS)
    with session_scope(engine) as s:
        rub = load_rates(s, RUBAMD.id)
        usd = load_rates(s, USDAMD.id)
    both = rub.to_frame("rub").join(usd.to_frame("usd"), how="inner").dropna()
    if start is not None:
        both = both[both.index >= start.isoformat()]
    points = [
        Point(ts.date(), Decimal(str(round(float(r.rub) / float(r.usd), 8))))
        for ts, r in both.iterrows()
        if float(r.usd) > 0
    ]
    return write_rates(
        engine, RUBUSD.id, SOURCE_FRANKFURTER_CBA, unique_points("derived", points), now
    )

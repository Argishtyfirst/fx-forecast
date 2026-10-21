"""Shared ingest plumbing: parsed points, idempotent writers, and the per-series loop.

Rates are upserted (a late fix by the source replaces the stored value). Macro rows
are insert-only (see fxf.ingest.pit for why we never overwrite them).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal
from typing import Any, Final, NamedTuple

from sqlalchemy import Engine, func, select

from fxf.db import session_scope
from fxf.http import SchemaError, SourceError
from fxf.ingest.pit import publication_time
from fxf.jobs import RunContext
from fxf.logging_setup import get_logger
from fxf.models import MacroSeries, Rate, upsert

log = get_logger(__name__)

# Full macro history starts here: enough warm-up for 63-day features before 1999.
MACRO_HISTORY_START: Final = dt.date(1990, 1, 1)
# Daily macro runs refetch this many days before the last stored observation. It covers
# late-arriving observations and a whole month for monthly series (HICP).
MACRO_LOOKBACK_DAYS: Final = 45


class Point(NamedTuple):
    date: dt.date
    value: Decimal


class IngestError(SourceError):
    """Several series of one source failed; the message lists each failure."""


def unique_points(source: str, points: Iterable[Point]) -> list[Point]:
    """Sorted points; a repeated date means we misread the response, so it is a SchemaError."""
    out = sorted(points)
    for a, b in zip(out, out[1:], strict=False):
        if a.date == b.date:
            raise SchemaError(f"{source}: duplicate observation for {a.date}")
    return out


def parse_decimal(source: str, raw: str) -> Decimal | None:
    """A numeric cell, or None for the sources' missing markers ('', '.', 'NaN')."""
    text = raw.strip()
    if text in ("", ".", "NaN", "NA"):
        return None
    try:
        value = Decimal(text)
    except ArithmeticError:
        raise SchemaError(f"{source}: non-numeric value {raw!r}") from None
    if not value.is_finite():
        raise SchemaError(f"{source}: non-numeric value {raw!r}")
    return value


def latest_rate_date(engine: Engine | None, pair: str) -> dt.date | None:
    with session_scope(engine) as s:
        return s.scalar(select(func.max(Rate.date)).where(Rate.pair == pair))


def latest_macro_date(engine: Engine | None, series_id: str) -> dt.date | None:
    with session_scope(engine) as s:
        return s.scalar(
            select(func.max(MacroSeries.date)).where(MacroSeries.series_id == series_id)
        )


def write_rates(
    engine: Engine | None,
    pair: str,
    source: str,
    points: Sequence[Point],
    fetched_at: dt.datetime,
) -> int:
    """Upsert one pair's rates. Returns the number of rows inserted or updated."""
    rows = [
        {"pair": pair, "date": p.date, "rate": p.value, "source": source, "fetched_at": fetched_at}
        for p in points
    ]
    with session_scope(engine) as s:
        return upsert(s, Rate, rows, ["pair", "date"], update_cols=["rate", "source", "fetched_at"])


def write_macro(
    engine: Engine | None,
    series_id: str,
    source: str,
    points: Sequence[Point],
    fetched_at: dt.datetime,
) -> int:
    """Insert new observations, keep existing ones untouched. Returns the number inserted."""
    rows = [
        {
            "series_id": series_id,
            "date": p.date,
            "value": p.value,
            "source": source,
            "published_at": publication_time(series_id, p.date, fetched_at),
            "fetched_at": fetched_at,
        }
        for p in points
    ]
    count = select(func.count()).select_from(MacroSeries).where(MacroSeries.series_id == series_id)
    with session_scope(engine) as s:
        before = s.scalar(count) or 0
        upsert(s, MacroSeries, rows, ["series_id", "date"])
        return (s.scalar(count) or 0) - before


def raise_collected(errors: list[tuple[str, Exception]]) -> None:
    """Fail the job after every item had its chance: one error as is, several combined."""
    if not errors:
        return
    if len(errors) == 1:
        raise errors[0][1]
    detail = "; ".join(f"{key}: {type(exc).__name__}: {exc}" for key, exc in errors)
    raise IngestError(detail) from errors[0][1]


def ingest_macro(
    ctx: RunContext,
    *,
    source: str,
    series_ids: Sequence[str],
    fetch: Callable[[str, dt.date], list[Point]],
    engine: Engine | None,
    now: dt.datetime,
    full: bool,
) -> None:
    """Fetch and store each series of a macro source. One broken series does not block the
    others; the job still fails at the end so the alert fires."""
    today = now.astimezone(dt.UTC).date()
    errors: list[tuple[str, Exception]] = []
    for series_id in series_ids:
        try:
            last = None if full else latest_macro_date(engine, series_id)
            if last is None:
                start = MACRO_HISTORY_START
            else:
                start = min(last - dt.timedelta(days=MACRO_LOOKBACK_DAYS), today)
            points = fetch(series_id, start)
            if not points and last is None:
                raise SourceError(f"{source}: {series_id} returned no observations since {start}")
            inserted = write_macro(engine, series_id, source, points, now)
        except Exception as exc:
            log.error(
                "series ingest failed",
                extra={"job": source, "series_id": series_id, "error": str(exc)},
            )
            ctx.meta[series_id] = {"error": f"{type(exc).__name__}: {exc}"}
            errors.append((series_id, exc))
            continue
        ctx.rows_written += inserted
        ctx.meta[series_id] = window_meta(start, points, inserted=inserted)
        log.info(
            "series ingested",
            extra={
                "job": source,
                "series_id": series_id,
                "fetched": len(points),
                "inserted": inserted,
            },
        )
    raise_collected(errors)


def window_meta(start: dt.date, points: Sequence[Point], **extra: Any) -> dict[str, Any]:
    """What a job fetched for one series, kept in job_runs.meta for debugging."""
    return {
        "from": start.isoformat(),
        "fetched": len(points),
        "last": points[-1].date.isoformat() if points else None,
        **extra,
    }

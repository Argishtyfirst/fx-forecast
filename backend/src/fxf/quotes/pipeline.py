"""Job `provider_quotes`, run from the hourly workflow.

Bank board rates are read hourly while Armenian banks are open (rate.am shows the same
numbers overnight); Wise every few hours, any day. A source that fails is logged and
skipped; the job fails only when every due source failed. Rows older than KEEP_DAYS go.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, delete, func, select

from fxf.alerts import send_alert
from fxf.constants import JOB_QUOTES
from fxf.db import session_scope
from fxf.jobs import job_run
from fxf.logging_setup import get_logger
from fxf.models import ProviderQuote, Rate, upsert, utcnow
from fxf.quotes.sources import (
    CURRENCIES,
    Quote,
    fetch_inecobank,
    fetch_paysend,
    fetch_rateam,
    fetch_wise,
)

log = get_logger(__name__)

YEREVAN: Final = ZoneInfo("Asia/Yerevan")
BANK_HOURS: Final = (9, 21)  # local hours the bank sources are read
KEEP_DAYS: Final = 30
SLACK: Final = dt.timedelta(minutes=10)
STALE_ALERT: Final = dt.timedelta(hours=26)  # the age at which the card shows a quote as stale


@dataclass(frozen=True)
class Source:
    name: str
    fetch: Callable[[dict[str, float]], list[Quote]]
    every: dt.timedelta
    bank_hours_only: bool


SOURCES: Final = (
    Source("rate.am", fetch_rateam, dt.timedelta(hours=1), True),
    Source("inecobank", fetch_inecobank, dt.timedelta(hours=1), True),
    Source("wise", fetch_wise, dt.timedelta(hours=3), False),
    Source("paysend", fetch_paysend, dt.timedelta(hours=3), False),
)


def reference_rates(session) -> dict[str, float]:
    """The latest CBA rate per pair, the yardstick every quote is checked against."""
    out = {}
    for pair in CURRENCIES.values():
        rate = session.scalar(
            select(Rate.rate).where(Rate.pair == pair).order_by(Rate.date.desc()).limit(1)
        )
        if rate is not None:
            out[pair] = float(rate)
    return out


def _due(src: Source, last: dt.datetime | None, now: dt.datetime) -> bool:
    if last is None:
        return True
    if src.bank_hours_only and not (BANK_HOURS[0] <= now.astimezone(YEREVAN).hour < BANK_HOURS[1]):
        return False
    return now - last >= src.every - SLACK


def _row(q: Quote, now: dt.datetime) -> dict:
    def dec(x: float | None) -> Decimal | None:
        return None if x is None else Decimal(str(round(x, 8)))

    return {
        "fetched_at": now,
        "provider": q.provider,
        "name": q.name,
        "kind": q.kind,
        "pair": q.pair,
        "channel": q.channel,
        "buy": dec(q.buy),
        "sell": dec(q.sell),
        "fee_fixed": dec(q.fee_fixed),
        "fee_pct": q.fee_pct,
        "quoted_at": q.quoted_at,
        "source": q.source,
        "url": q.url,
        "meta": q.meta,
    }


def run_quotes(
    engine: Engine | None = None, *, now: dt.datetime | None = None, force: bool = False
) -> tuple[int, dict]:
    now = (now or utcnow()).replace(microsecond=0)
    with session_scope(engine) as s:
        reference = reference_rates(s)
        last = dict(
            s.execute(
                select(ProviderQuote.source, func.max(ProviderQuote.fetched_at)).group_by(
                    ProviderQuote.source
                )
            ).all()
        )
    due = [src for src in SOURCES if force or _due(src, last.get(src.name), now)]
    quotes: list[Quote] = []
    report: dict = {"due": [src.name for src in due], "errors": {}, "counts": {}}
    for src in due:
        try:
            got = src.fetch(reference)
        except Exception as exc:  # one source failing must not lose the others
            log.warning("quote source failed", extra={"source": src.name, "error": str(exc)})
            report["errors"][src.name] = str(exc)[:300]
            # A blip is retried on the next run. A source that has given nothing for a day
            # (its page changed, or it now blocks us) alerts on every failed run until fixed.
            ok_at = last.get(src.name)
            if ok_at is None or now - ok_at > STALE_ALERT:
                send_alert(
                    f"Quote source failing: {src.name}",
                    f"No rates since {ok_at.isoformat() if ok_at else 'ever'}: {exc}",
                )
            continue
        for q in got:
            q.source = src.name
        report["counts"][src.name] = len(got)
        quotes.extend(got)
    with session_scope(engine) as s:
        written = upsert(
            s,
            ProviderQuote,
            [_row(q, now) for q in quotes],
            ["provider", "pair", "channel", "fetched_at"],
        )
        s.execute(
            delete(ProviderQuote).where(
                ProviderQuote.fetched_at < now - dt.timedelta(days=KEEP_DAYS)
            )
        )
    if due and len(report["errors"]) == len(due):
        raise RuntimeError("; ".join(f"{k}: {v}" for k, v in report["errors"].items()))
    return written, report


def run_quotes_job(engine: Engine | None = None, *, force: bool = False) -> bool:
    try:
        with job_run(JOB_QUOTES, engine=engine) as run:
            run.rows_written, report = run_quotes(engine, force=force)
            run.meta.update(report)
        return True
    except Exception:
        return False

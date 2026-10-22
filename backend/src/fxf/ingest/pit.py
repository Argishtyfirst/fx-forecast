"""Point-in-time publication rules for macro series (FR-04, NFR-03).

A backtest on day t may only use values that were public at its cutoff, so every
macro row needs `published_at`. The sources do not tell us when each observation
was first released, so each series gets a conservative publication-lag rule: the
rule time is at or after the real release time, never before it.

A new row gets published_at = min(rule(obs_date), fetched_at): if we have already
fetched a value, it was public by then, even if the rule says it is not out yet.

We do not keep vintages. The first value we store for (series_id, date) is kept
forever (on conflict do nothing), so later revisions by the source are ignored.
For the policy rates this changes nothing; for DFF, DGS2 and the other market
series revisions are rare and small. A backtest therefore sees today's first-fetch
value with a conservative publication time, not the historical first release.

| Series | Rule (UTC) | Why |
| --- | --- | --- |
| DFEDTARU, DFEDTARL, ECB_DFR, BOE_BANK, CBR_KEY | obs date 00:00 | Decisions are announced before the effective date. |
| DFF | next US business day 14:00 | NY Fed publishes EFFR the next morning. |
| DGS2 | next US business day 22:00 | Treasury yields reach FRED the next evening. |
| DTWEXBGS | obs + 7 days 22:00 | Weekly H.10 release covers the prior week. |
| DCOILBRENTEU | obs + 7 days 22:00 | EIA spot prices are posted weekly. |
| ESTR | next TARGET2 day 07:00 | The ECB publishes €STR at 08:00 CET on T+1. |
| HICP | month end + 18 days 09:00 | Eurostat's full release is mid-month; obs date is the 1st of the month. |
| FEDTARMD | fetched_at | SEP projections; models do not use them. |
"""

from __future__ import annotations

import calendar
import datetime as dt
from collections.abc import Callable
from typing import Final

from fxf.calendars import CALENDAR_TARGET2, CALENDAR_US, add_trading_days

PublicationRule = Callable[[dt.date, dt.datetime], dt.datetime]


def _at(d: dt.date, hour: int) -> dt.datetime:
    return dt.datetime.combine(d, dt.time(hour), tzinfo=dt.UTC)


def _same_day(obs: dt.date, _fetched: dt.datetime) -> dt.datetime:
    return _at(obs, 0)


def _next_business_day(calendar_id: str, hour: int) -> PublicationRule:
    return lambda obs, _fetched: _at(add_trading_days(calendar_id, obs, 1), hour)


def _days_later(days: int, hour: int) -> PublicationRule:
    return lambda obs, _fetched: _at(obs + dt.timedelta(days=days), hour)


def _month_end_plus(days: int, hour: int) -> PublicationRule:
    def rule(obs: dt.date, _fetched: dt.datetime) -> dt.datetime:
        last = dt.date(obs.year, obs.month, calendar.monthrange(obs.year, obs.month)[1])
        return _at(last + dt.timedelta(days=days), hour)

    return rule


def _when_fetched(_obs: dt.date, fetched: dt.datetime) -> dt.datetime:
    return fetched


RULES: Final[dict[str, PublicationRule]] = {
    "DFEDTARU": _same_day,
    "DFEDTARL": _same_day,
    "ECB_DFR": _same_day,
    "BOE_BANK": _same_day,
    "CBR_KEY": _same_day,
    "DFF": _next_business_day(CALENDAR_US, 14),
    "DGS2": _next_business_day(CALENDAR_US, 22),
    "DTWEXBGS": _days_later(7, 22),
    "DCOILBRENTEU": _days_later(7, 22),
    "ESTR": _next_business_day(CALENDAR_TARGET2, 7),
    "HICP": _month_end_plus(18, 9),
    "FEDTARMD": _when_fetched,
}


def publication_time(series_id: str, obs_date: dt.date, fetched_at: dt.datetime) -> dt.datetime:
    """published_at for a newly stored observation: min(rule(obs_date), fetched_at)."""
    if fetched_at.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware")
    try:
        rule = RULES[series_id]
    except KeyError:
        raise ValueError(f"no publication rule for series {series_id!r}") from None
    return min(rule(obs_date, fetched_at), fetched_at)

"""Trading-day calendars: TARGET2 (ECB fixing days), US (Fed/FRED), Armenia (CBA fixing days).

Verified against the Frankfurter histories: every missing EUR/USD weekday since 2015 is a
TARGET2 holiday, and every missing USD/AMD weekday but one is an Armenian public holiday.
The CBA also fixes on a few transferred Saturdays; history uses the rate series' own dates,
so this calendar only matters for future target dates.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from zoneinfo import ZoneInfo

import holidays

CALENDAR_TARGET2 = "TARGET2"
CALENDAR_US = "US"
CALENDAR_AM = "AM"

PAIR_CALENDAR = {"EURUSD": CALENDAR_TARGET2, "USDAMD": CALENDAR_AM, "EURAMD": CALENDAR_AM}
BANK_CALENDAR = {"ECB": CALENDAR_TARGET2, "FED": CALENDAR_US, "CBA": CALENDAR_AM}

CET = ZoneInfo("Europe/Berlin")


@lru_cache(maxsize=64)
def _holidays(calendar: str, year: int) -> frozenset[dt.date]:
    if calendar == CALENDAR_TARGET2:
        h = holidays.financial_holidays("ECB", years=year)
    elif calendar == CALENDAR_US:
        h = holidays.financial_holidays("NYSE", years=year) | holidays.US(years=year)
    elif calendar == CALENDAR_AM:
        h = holidays.Armenia(years=year)
    else:
        raise ValueError(f"unknown calendar {calendar!r}")
    return frozenset(h.keys())


def is_holiday(calendar: str, d: dt.date) -> bool:
    return d in _holidays(calendar, d.year)


def is_trading_day(calendar: str, d: dt.date) -> bool:
    return d.weekday() < 5 and not is_holiday(calendar, d)


def add_trading_days(calendar: str, d: dt.date, n: int) -> dt.date:
    """The n-th trading day after d (n >= 0). n=0 returns d itself."""
    if n < 0:
        raise ValueError("n must be >= 0")
    cur = d
    left = n
    while left > 0:
        cur += dt.timedelta(days=1)
        if is_trading_day(calendar, cur):
            left -= 1
    return cur


def trading_days_between(calendar: str, start: dt.date, end: dt.date) -> list[dt.date]:
    """Trading days in (start, end]."""
    out = []
    cur = start + dt.timedelta(days=1)
    while cur <= end:
        if is_trading_day(calendar, cur):
            out.append(cur)
        cur += dt.timedelta(days=1)
    return out


def previous_trading_day(calendar: str, d: dt.date) -> dt.date:
    cur = d - dt.timedelta(days=1)
    while not is_trading_day(calendar, cur):
        cur -= dt.timedelta(days=1)
    return cur


def is_working_day(d: dt.date) -> bool:
    """A pipeline working day: a TARGET2 business day (the ECB rate is the daily anchor)."""
    return is_trading_day(CALENDAR_TARGET2, d)


def now_cet() -> dt.datetime:
    return dt.datetime.now(CET)

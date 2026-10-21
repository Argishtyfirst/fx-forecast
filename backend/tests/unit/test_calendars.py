"""Trading-day calendars (fxf.calendars): TARGET2, US and Armenian holidays."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from fxf import calendars as cal

D = dt.date
FIX = Path(__file__).resolve().parents[1] / "fixtures" / "frankfurter"


@pytest.mark.parametrize(
    "day",
    [
        D(2025, 1, 1),  # New Year's Day
        D(2025, 4, 18),  # Good Friday
        D(2025, 4, 21),  # Easter Monday
        D(2025, 5, 1),  # Labour Day
        D(2025, 12, 25),  # Christmas Day
        D(2025, 12, 26),  # Boxing Day
        D(2026, 4, 3),  # Good Friday
        D(2026, 4, 6),  # Easter Monday
    ],
)
def test_target2_holidays_are_not_trading_days(day):
    assert day.weekday() < 5
    assert cal.is_holiday(cal.CALENDAR_TARGET2, day)
    assert not cal.is_trading_day(cal.CALENDAR_TARGET2, day)


@pytest.mark.parametrize("day", [D(2025, 12, 24), D(2025, 12, 31), D(2025, 11, 27)])
def test_target2_open_on_days_other_markets_close(day):
    assert cal.is_trading_day(cal.CALENDAR_TARGET2, day)


@pytest.mark.parametrize(
    "day",
    [
        D(2025, 11, 27),  # Thanksgiving
        D(2026, 11, 26),  # Thanksgiving
        D(2025, 7, 4),  # Independence Day on a Friday
        D(2026, 7, 3),  # Independence Day (Saturday) observed on Friday
        D(2027, 7, 5),  # Independence Day (Sunday) observed on Monday
    ],
)
def test_us_holidays_are_not_trading_days(day):
    assert day.weekday() < 5
    assert not cal.is_trading_day(cal.CALENDAR_US, day)


def test_us_day_after_thanksgiving_is_a_trading_day():
    assert cal.is_trading_day(cal.CALENDAR_US, D(2025, 11, 28))


@pytest.mark.parametrize(
    "day",
    [
        D(2025, 1, 6),  # Christmas (Armenian Apostolic)
        D(2025, 1, 28),  # Army Day
        D(2025, 4, 24),  # Genocide Remembrance Day
        D(2025, 5, 28),  # Republic Day
    ],
)
def test_armenian_holidays_are_not_trading_days(day):
    assert day.weekday() < 5
    assert not cal.is_trading_day(cal.CALENDAR_AM, day)


def test_add_trading_days_skips_holidays_and_weekends():
    # Thursday before Easter: Good Friday, the weekend and Easter Monday are skipped.
    assert cal.add_trading_days(cal.CALENDAR_TARGET2, D(2025, 4, 17), 1) == D(2025, 4, 22)
    # Over Christmas: 24th, then 29th, 30th (25th, 26th and the weekend are closed).
    assert cal.add_trading_days(cal.CALENDAR_TARGET2, D(2025, 12, 23), 3) == D(2025, 12, 30)
    assert cal.add_trading_days(cal.CALENDAR_AM, D(2025, 1, 27), 1) == D(2025, 1, 29)
    assert cal.add_trading_days(cal.CALENDAR_US, D(2025, 11, 26), 1) == D(2025, 11, 28)
    assert cal.add_trading_days(cal.CALENDAR_US, D(2025, 11, 26), 0) == D(2025, 11, 26)


def test_add_trading_days_rejects_negative_n():
    with pytest.raises(ValueError):
        cal.add_trading_days(cal.CALENDAR_US, D(2025, 1, 2), -1)


def test_previous_trading_day_skips_holidays_and_weekends():
    assert cal.previous_trading_day(cal.CALENDAR_TARGET2, D(2025, 4, 22)) == D(2025, 4, 17)
    assert cal.previous_trading_day(cal.CALENDAR_TARGET2, D(2026, 1, 2)) == D(2025, 12, 31)
    assert cal.previous_trading_day(cal.CALENDAR_AM, D(2025, 1, 29)) == D(2025, 1, 27)
    assert cal.previous_trading_day(cal.CALENDAR_US, D(2025, 12, 1)) == D(2025, 11, 28)


def test_trading_days_between_is_half_open():
    days = cal.trading_days_between(cal.CALENDAR_TARGET2, D(2025, 4, 16), D(2025, 4, 22))
    assert days == [D(2025, 4, 17), D(2025, 4, 22)]


def test_working_day_follows_target2():
    assert cal.is_working_day(D(2025, 1, 28))  # Armenian holiday, TARGET2 open
    assert not cal.is_working_day(D(2025, 5, 1))
    assert not cal.is_working_day(D(2025, 5, 3))


def test_unknown_calendar_is_rejected():
    with pytest.raises(ValueError):
        cal.is_trading_day("XX", D(2025, 1, 2))


def _fixture_dates(name: str, year: int) -> set[dt.date]:
    rows = json.loads((FIX / name).read_text())
    return {D.fromisoformat(r["date"]) for r in rows if r["date"].startswith(str(year))}


def _calendar_dates(calendar: str, year: int) -> set[dt.date]:
    start = D(year, 1, 1)
    days = (start + dt.timedelta(days=i) for i in range(366))
    return {d for d in days if d.year == year and cal.is_trading_day(calendar, d)}


@pytest.mark.parametrize(
    ("fixture", "calendar"),
    [("ecb_EUR_USD.json", cal.CALENDAR_TARGET2), ("cba_USD_AMD.json", cal.CALENDAR_AM)],
)
def test_recorded_2025_fixing_dates_match_the_pair_calendar(fixture, calendar):
    fixed = _fixture_dates(fixture, 2025)
    expected = _calendar_dates(calendar, 2025)
    assert fixed - expected == set(), "fixings on days the calendar calls closed"
    assert expected - fixed == set(), "trading days without a fixing"

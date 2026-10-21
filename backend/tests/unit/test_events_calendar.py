"""Meeting calendars: page parsers, the checked-in seed, and FR-12 coverage."""

import datetime as dt

import pandas as pd
import pytest

from fxf.constants import BANKS
from fxf.events import calendar as cal
from fxf.events import cba
from fxf.events.features import load_meetings, meetings_in_window

AS_OF = dt.date(2026, 10, 21)


def test_fed_calendar_uses_decision_day_and_reads_future_year(fixtures_dir):
    meetings = cal.parse_fed_calendar((fixtures_dir / "fed/fomccalendars.htm").read_text())
    days = {m.date for m in meetings}
    assert dt.date(2026, 1, 28) in days  # "January 27-28" -> second day
    assert dt.date(2026, 9, 16) in days
    assert dt.date(2027, 1, 27) in days and dt.date(2027, 12, 8) in days
    assert dt.date(2025, 8, 22) not in days  # notation vote, not a meeting
    assert all(m.scheduled for m in meetings)


def test_fed_historical_marks_unscheduled_meetings_on_statement_date(fixtures_dir):
    meetings = cal.parse_fed_historical(
        (fixtures_dir / "fed/fomchistorical2020.htm").read_text(), 2020
    )
    by_day = {m.date: m.scheduled for m in meetings}
    assert by_day[dt.date(2020, 3, 3)] is False  # "March 2 (unscheduled)", statement March 3
    assert by_day[dt.date(2020, 3, 15)] is False
    assert dt.date(2020, 3, 18) not in by_day  # "March 17-18 (cancelled)"
    assert dt.date(2020, 3, 23) not in by_day  # notation vote
    assert by_day[dt.date(2020, 1, 29)] is True
    assert len([d for d, s in by_day.items() if s]) == 7


def test_fed_historical_handles_month_spanning_meeting(fixtures_dir):
    meetings = cal.parse_fed_historical(
        (fixtures_dir / "fed/fomchistorical2012.htm").read_text(), 2012
    )
    days = [m.date for m in meetings]
    assert dt.date(2012, 8, 1) in days  # "July 31-August 1 Meeting"
    assert len(days) == 8


def test_ecb_schedule_keeps_only_monetary_policy_decision_days(fixtures_dir):
    meetings = cal.parse_ecb_schedule((fixtures_dir / "ecb_rss/mgcgc.htm").read_text())
    days = [m.date for m in meetings]
    assert days[:2] == [dt.date(2026, 10, 29), dt.date(2026, 12, 17)]
    assert dt.date(2026, 10, 28) not in days  # Day 1
    assert dt.date(2026, 11, 25) not in days  # non-monetary meeting
    assert dt.date(2028, 10, 12) in days and dt.date(2028, 10, 11) not in days  # unlabelled day 1


def test_ecb_decision_listing_returns_release_urls(fixtures_dir):
    pairs = cal.parse_ecb_decisions((fixtures_dir / "ecb_rss/mopo_2026_include.htm").read_text())
    assert [m.date for m, _ in pairs] == [
        dt.date(2026, 2, 5),
        dt.date(2026, 3, 19),
        dt.date(2026, 4, 30),
        dt.date(2026, 6, 11),
        dt.date(2026, 7, 23),
        dt.date(2026, 9, 10),
    ]
    assert pairs[-1][1].endswith("ecb.mp260910~314e508016.en.html")
    old = cal.parse_ecb_decisions((fixtures_dir / "ecb_rss/mopo_2008_include.htm").read_text())
    assert {m.date: m.scheduled for m, _ in old}[dt.date(2008, 10, 8)] is False


def test_cba_calendar_pdf_glyph_table_decodes_2026_to_2028(fixtures_dir):
    data = (fixtures_dir / "cba/interest_rate_calendar_2026_2028_eng.pdf").read_bytes()
    meetings = cba.parse_calendar_pdf(data, "https://www.cba.am/x.pdf")
    days = [m.date for m in meetings]
    assert len(days) == 24
    assert days[:3] == [dt.date(2026, 2, 3), dt.date(2026, 3, 17), dt.date(2026, 5, 5)]
    assert dt.date(2026, 11, 3) in days and dt.date(2026, 12, 15) in days
    assert days[-1] == dt.date(2028, 12, 12)


def test_cba_calendar_pdf_with_unknown_glyphs_fails_loudly(fixtures_dir):
    from fxf.http import SchemaError

    data = (fixtures_dir / "cba/interest_rate_calendar_2026_2028_eng.pdf").read_bytes()
    with pytest.raises(SchemaError):
        cba.parse_calendar_pdf(data, "u", glyphs={})


def test_seed_is_valid_and_sorted():
    seed = cal.load_seed()
    assert {m.bank for m in seed} == set(BANKS)
    keys = [(m.bank, m.date) for m in seed]
    assert len(keys) == len(set(keys))
    fed = {m.date: m.scheduled for m in seed if m.bank == "FED"}
    assert fed[dt.date(2020, 3, 3)] is False and fed[dt.date(2020, 3, 15)] is False
    for bank, first in (("FED", 2010), ("ECB", 2010), ("CBA", 2015)):
        years = {m.date.year for m in seed if m.bank == bank}
        assert set(range(first, 2027)) <= years, bank


@pytest.mark.parametrize("bank", BANKS)
def test_fr12_calendar_holds_six_months_of_future_meetings(bank):
    """Spec rule: the published calendar is stored at least 6 months ahead (as of 2026-10-21)."""
    future = sorted(
        m.date for m in cal.load_seed() if m.bank == bank and m.date > AS_OF and m.scheduled
    )
    assert future, bank
    assert future[-1] >= AS_OF + dt.timedelta(days=183), (bank, future[-1])
    # No gap of more than ~2.5 months inside the next six months.
    horizon = [AS_OF, *[d for d in future if d <= AS_OF + dt.timedelta(days=183)]]
    assert max((b - a).days for a, b in zip(horizon, horizon[1:], strict=False)) <= 80


def test_fr12_meetings_in_window_reads_stored_calendar(session, clean_db):
    cal.load_seed_into_db(clean_db)
    meetings = load_meetings(session)
    window = meetings_in_window(meetings, ("FED", "ECB"), AS_OF, AS_OF + dt.timedelta(days=30))
    assert window == [{"bank": "FED", "date": "2026-10-28"}, {"bank": "ECB", "date": "2026-10-29"}]
    assert isinstance(meetings["date"].iloc[0], pd.Timestamp)


def test_store_meetings_is_idempotent(clean_db):
    m = [cal.Meeting("ECB", dt.date(2026, 10, 29), True, "u")]
    cal.store_meetings(clean_db, m)
    cal.store_meetings(clean_db, m + [cal.Meeting("ECB", dt.date(2026, 10, 29), False, "v")])
    stored = cal.stored_meetings(clean_db, "ECB")
    assert [(x.date, x.scheduled, x.source_url) for x in stored] == [
        (dt.date(2026, 10, 29), False, "v")
    ]

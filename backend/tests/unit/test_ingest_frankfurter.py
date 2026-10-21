"""Frankfurter ingest rules: request window and the FR-01 publication check."""

from __future__ import annotations

import datetime as dt

import pytest

from fxf.calendars import CET
from fxf.constants import RUBAMD
from fxf.ingest.frankfurter import (
    HISTORY_START,
    SERIES,
    RateNotPublishedError,
    check_published,
    window,
)

D = dt.date


def cet(y: int, m: int, d: int, hh: int, mm: int = 0) -> dt.datetime:
    return dt.datetime(y, m, d, hh, mm, tzinfo=CET)


def test_window_is_full_history_for_an_empty_pair():
    assert window(None, "ECB", D(2026, 10, 21)) == HISTORY_START["ECB"] == D(1999, 1, 1)
    assert window(None, "CBA", D(2026, 10, 21)) == D(1990, 1, 1)


def test_window_overlaps_the_last_10_days():
    assert window(D(2026, 10, 19), "ECB", D(2026, 10, 21)) == D(2026, 10, 9)


def test_window_never_starts_after_today():
    assert window(D(2026, 12, 31), "CBA", D(2026, 10, 21)) == D(2026, 10, 21)


def test_sources_cover_the_pairs_and_the_rubamd_feature():
    assert [s.pair for s in SERIES["frankfurter_ecb"]] == ["EURUSD"]
    assert [s.pair for s in SERIES["frankfurter_cba"]] == ["USDAMD", "EURAMD", RUBAMD]


def test_fr01_missing_today_after_1700_cet_raises():
    with pytest.raises(RateNotPublishedError, match="today's EURUSD rate is not published yet"):
        check_published({"EURUSD": D(2026, 10, 20)}, cet(2026, 10, 21, 17, 0))


def test_fr01_names_every_missing_pair():
    with pytest.raises(RateNotPublishedError, match="EURUSD and USDAMD"):
        check_published({"EURUSD": None, "USDAMD": D(2026, 10, 20)}, cet(2026, 10, 21, 18))


def test_fr01_uses_central_european_local_time_across_dst():
    # 15:30 UTC in October is 17:30 CEST: past the deadline.
    with pytest.raises(RateNotPublishedError):
        check_published(
            {"EURUSD": D(2026, 10, 20)}, dt.datetime(2026, 10, 21, 15, 30, tzinfo=dt.UTC)
        )
    # 15:30 UTC in December is 16:30 CET: not yet.
    check_published({"EURUSD": D(2026, 12, 8)}, dt.datetime(2026, 12, 9, 15, 30, tzinfo=dt.UTC))


@pytest.mark.parametrize(
    ("latest", "now"),
    [
        ({"EURUSD": D(2026, 10, 21)}, cet(2026, 10, 21, 17, 30)),  # stored
        ({"EURUSD": D(2026, 10, 20)}, cet(2026, 10, 21, 16, 59)),  # before 17:00
        ({"EURUSD": D(2026, 10, 23)}, cet(2026, 10, 24, 18)),  # Saturday
        ({"EURUSD": D(2026, 4, 2)}, cet(2026, 4, 3, 18)),  # Good Friday: not a working day
        ({"USDAMD": D(2025, 1, 27)}, cet(2025, 1, 28, 18)),  # Army Day: AMD not fixed
        ({RUBAMD: D(2026, 10, 1)}, cet(2026, 10, 21, 18)),  # feature series is not checked
    ],
)
def test_fr01_no_error_when_today_is_not_due(latest, now):
    check_published(latest, now)

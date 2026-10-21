"""Publication-lag rules for macro series (FR-04, NFR-03)."""

from __future__ import annotations

import datetime as dt

import pytest

from fxf.constants import ECB_SERIES, FRED_SERIES
from fxf.ingest.pit import RULES, publication_time

D = dt.date
LATE = dt.datetime(2030, 1, 1, tzinfo=dt.UTC)  # fetched long after any release


def utc(y: int, m: int, d: int, h: int = 0) -> dt.datetime:
    return dt.datetime(y, m, d, h, tzinfo=dt.UTC)


def test_every_fred_and_ecb_series_has_a_rule():
    assert set(RULES) == set(FRED_SERIES) | set(ECB_SERIES)


@pytest.mark.parametrize(
    ("series_id", "obs", "published"),
    [
        ("DFEDTARU", D(2026, 9, 17), utc(2026, 9, 17)),
        ("DFEDTARL", D(2026, 9, 17), utc(2026, 9, 17)),
        ("ECB_DFR", D(2026, 9, 16), utc(2026, 9, 16)),
        # Next US business day: Thursday 2026-07-02 -> Monday 07-06 (07-03 is observed July 4).
        ("DFF", D(2026, 7, 2), utc(2026, 7, 6, 14)),
        ("DFF", D(2026, 10, 16), utc(2026, 10, 19, 14)),
        # Friday 2026-10-09 -> Tuesday 10-13 (Columbus Day is a federal holiday).
        ("DGS2", D(2026, 10, 9), utc(2026, 10, 13, 22)),
        ("DTWEXBGS", D(2026, 10, 9), utc(2026, 10, 16, 22)),
        ("DCOILBRENTEU", D(2026, 10, 9), utc(2026, 10, 16, 22)),
        # Next TARGET2 day: Maundy Thursday 2025-04-17 -> Tuesday 04-22.
        ("ESTR", D(2025, 4, 17), utc(2025, 4, 22, 7)),
        ("ESTR", D(2026, 10, 20), utc(2026, 10, 21, 7)),
        ("HICP", D(2026, 9, 1), utc(2026, 10, 18, 9)),
        ("HICP", D(2024, 2, 1), utc(2024, 3, 18, 9)),  # leap February ends on the 29th
        ("HICP", D(2025, 12, 1), utc(2026, 1, 18, 9)),
    ],
)
def test_rule_gives_a_conservative_release_time(series_id, obs, published):
    assert publication_time(series_id, obs, LATE) == published


def test_publication_never_after_we_fetched_the_value():
    fetched = utc(2026, 10, 21, 12)
    # Rule says 2026-10-23 22:00, but the value is in our hands already.
    assert publication_time("DTWEXBGS", D(2026, 10, 16), fetched) == fetched
    assert publication_time("ESTR", D(2026, 10, 21), fetched) == fetched


def test_projections_are_published_when_fetched():
    fetched = utc(2026, 10, 21, 12)
    assert publication_time("FEDTARMD", D(2027, 1, 1), fetched) == fetched
    assert publication_time("FEDTARMD", D(2026, 1, 1), fetched) == fetched


def test_rules_never_publish_before_the_observation_date():
    for series_id in RULES:
        obs = D(2026, 3, 2)
        assert publication_time(series_id, obs, LATE) >= utc(2026, 3, 2)


def test_unknown_series_and_naive_fetch_time_are_rejected():
    with pytest.raises(ValueError, match="no publication rule"):
        publication_time("CBA_REFI_UNKNOWN", D(2026, 1, 1), LATE)
    with pytest.raises(ValueError, match="timezone-aware"):
        publication_time("DFF", D(2026, 1, 1), dt.datetime(2026, 1, 2))

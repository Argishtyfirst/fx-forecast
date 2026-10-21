"""Decision rows, surprise calculation and the history builders for each bank (FR-05)."""

import datetime as dt
import json

import pandas as pd
import pytest

from fxf.events import cba, ecb, fed
from fxf.events.calendar import Meeting
from fxf.events.decisions import (
    EXPECTED_ATLFED,
    EXPECTED_PREVIOUS,
    Decision,
    event_row,
    refresh_diffs,
    stored_events,
    surprise_bps,
    upsert_events,
)


@pytest.mark.parametrize(
    ("after", "expected", "bps"),
    [
        (4.375, 4.375, 0.0),
        (4.125, 4.375, -25.0),
        (5.25, 4.993, 25.7),
        (None, 1.0, None),
        (1.0, None, None),
    ],
)
def test_surprise_is_actual_minus_expected_in_bps(after, expected, bps):
    assert surprise_bps(after, expected) == bps


def test_event_row_defaults_expected_to_previous_rate():
    d = Decision(
        "CBA",
        dt.date(2026, 9, 15),
        {"refinancing": 6.5, "lombard": 8, "deposit": 5},
        {"refinancing": 6.75, "lombard": 8.25, "deposit": 5.25},
    )
    row = event_row(d)
    assert row["rate_type"] == "refinancing"
    assert float(row["rate_before"]) == 6.5 and float(row["rate_after"]) == 6.75
    assert row["expected_source"] == EXPECTED_PREVIOUS and row["surprise_bps"] == 25.0
    assert row["rates_json"]["lombard"] == {"before": 8, "after": 8.25}


def test_fed_history_uses_range_midpoint_and_tracker_expectation():
    idx = pd.date_range("2024-09-01", "2024-09-30")
    upper = pd.Series([5.5 if d <= pd.Timestamp("2024-09-18") else 5.0 for d in idx], index=idx)
    lower = upper - 0.25
    atl = pd.Series([4.99], index=pd.DatetimeIndex(["2024-09-17"]))
    meetings = [Meeting("FED", dt.date(2024, 9, 18)), Meeting("FED", dt.date(2024, 9, 25), False)]
    out = fed.history_decisions(meetings, upper, lower, atl, dt.date(2024, 10, 1))
    assert len(out) == 1  # the unscheduled meeting moved nothing
    d = out[0]
    assert d.rate_before == 5.375 and d.rate_after == 4.875
    assert d.after == {"upper": 5.0, "lower": 4.75, "mid": 4.875}
    assert d.expected == 4.99 and d.expected_source == EXPECTED_ATLFED
    assert event_row(d)["surprise_bps"] == -11.5
    assert d.published_at == dt.datetime(2024, 9, 18, 18, 30, tzinfo=dt.UTC)  # 14:30 EDT


def test_fed_history_skips_meeting_not_yet_in_series():
    idx = pd.date_range("2026-09-01", "2026-09-17")
    s = pd.Series(4.0, index=idx)
    assert (
        fed.history_decisions(
            [Meeting("FED", dt.date(2026, 9, 16))],
            s,
            s - 0.25,
            pd.Series(dtype=float),
            dt.date(2026, 9, 17),
        )
        == []
    )


def test_ecb_history_reads_effective_date_series(fixtures_dir):
    dfr = ecb.parse_fm_csv("DFR", (fixtures_dir / "ecb_decisions/fm_dfr.csv").read_text())
    mro = ecb.parse_fm_csv("MRR_FR", (fixtures_dir / "ecb_decisions/fm_mrr_fr.csv").read_text())
    meetings = [
        Meeting("ECB", dt.date(2026, 6, 11)),
        Meeting("ECB", dt.date(2026, 7, 23)),
        Meeting("ECB", dt.date(2026, 9, 10)),
    ]
    out = {
        d.date: d
        for d in ecb.history_decisions(
            meetings, {"deposit": dfr, "mro": mro}, dt.date(2026, 10, 21)
        )
    }
    sep = out[dt.date(2026, 9, 10)]
    assert sep.before["deposit"] == 2.25 and sep.after["deposit"] == 2.5
    assert sep.before["mro"] == 2.4 and sep.after["mro"] == 2.65
    assert out[dt.date(2026, 7, 23)].rate_before == out[dt.date(2026, 7, 23)].rate_after


def test_cba_export_cleaning_fixes_known_defects(fixtures_dir):
    rows = cba.parse_rates_export(json.loads((fixtures_dir / "cba/rates_export.json").read_text()))
    meetings = {d.decision_date for d in cba.load_decisions()}
    clean = {r.date: r for r in cba.clean_rate_history(rows, meetings)}
    # 2008-2009 rows carry the previous decision's rates in the raw export.
    assert {r.date: r for r in rows}[dt.date(2009, 9, 8)].refinancing == 5.25
    assert clean[dt.date(2009, 9, 8)].refinancing == 5.0  # press release: "to 5.00 percent"
    assert clean[dt.date(2008, 12, 2)].refinancing == 7.25
    # 2011 next-day duplicates are dropped (the 2011-02-09 row is wrong).
    assert dt.date(2011, 2, 9) not in clean and clean[dt.date(2011, 2, 8)].refinancing == 7.75
    # A row one day off the Board meeting snaps to it.
    assert dt.date(2013, 8, 12) not in clean and clean[dt.date(2013, 8, 13)].refinancing == 8.5
    assert clean[dt.date(2026, 9, 15)].as_dict() == {
        "refinancing": 6.75,
        "lombard": 8.25,
        "deposit": 5.25,
    }


def test_cba_seed_matches_cleaned_export_and_has_effective_dates():
    seed = cba.load_decisions()
    assert seed[0].decision_date == dt.date(2004, 3, 8)
    for d in seed:
        assert d.effective_date == d.decision_date + dt.timedelta(days=1)
        assert d.announced_at.tzinfo is not None
    by_day = {d.decision_date: d for d in seed}
    assert by_day[dt.date(2009, 3, 3)].scheduled is False  # extraordinary session
    assert by_day[dt.date(2025, 5, 6)].refinancing == 6.75  # hold recovered from old.cba.am


def test_cba_merge_live_adds_new_decision_and_keeps_known():
    seed = cba.load_decisions()
    live = [
        cba.RateSet(dt.date(2026, 11, 3), 7.0, 8.5, 5.5),
        cba.RateSet(dt.date(2009, 9, 8), 9.9, 9.9, 9.9),
    ]
    merged = {d.decision_date: d for d in cba.merge_live(seed, live)}
    assert merged[dt.date(2026, 11, 3)].refinancing == 7.0
    assert merged[dt.date(2009, 9, 8)].refinancing == 5.0  # before LIVE_FROM: curated value wins
    rows = cba.macro_rows([merged[dt.date(2026, 11, 3)]], dt.datetime(2026, 11, 3, tzinfo=dt.UTC))
    assert {(r["series_id"], r["date"], r["value"]) for r in rows} == {
        ("CBA_REFI", dt.date(2026, 11, 4), 7.0),
        ("CBA_LOMBARD", dt.date(2026, 11, 4), 8.5),
        ("CBA_DEPOSIT", dt.date(2026, 11, 4), 5.5),
    }


def test_upsert_events_is_idempotent_and_history_keeps_live_source(clean_db):
    day = dt.date(2026, 9, 16)
    live = Decision(
        "FED",
        day,
        fed.rates_from_range(3.5, 3.75),
        fed.rates_from_range(3.75, 4.0),
        source="fed_rss",
        published_at=dt.datetime(2026, 9, 16, 18, tzinfo=dt.UTC),
        statement_text="A. B.",
    )
    upsert_events(clean_db, [live])
    hist = Decision(
        "FED",
        day,
        fed.rates_from_range(3.5, 3.75),
        fed.rates_from_range(3.75, 4.0),
        source="fred",
        published_at=dt.datetime(2026, 9, 16, 18, 30, tzinfo=dt.UTC),
    )
    upsert_events(clean_db, [hist], keep_existing_source=True)
    upsert_events(clean_db, [hist], keep_existing_source=True)
    (ev,) = stored_events(clean_db, "FED")
    assert ev.source == "fed_rss" and ev.published_at == dt.datetime(2026, 9, 16, 18, tzinfo=dt.UTC)
    assert (
        ev.statement_text == "A. B." and float(ev.rate_after) == 3.875 and ev.surprise_bps == 25.0
    )


def test_refresh_diffs_links_previous_statement_of_same_bank(clean_db):
    def mk(bank, day, text):
        rate = {"deposit": 2.0} if bank == "ECB" else {"mid": 4.0}
        return Decision(bank, day, rate, dict(rate), statement_text=text)

    upsert_events(
        clean_db,
        [
            mk("ECB", dt.date(2026, 7, 23), "Rates unchanged. Inflation is at target."),
            mk("FED", dt.date(2026, 7, 29), "Something else entirely."),
            mk("ECB", dt.date(2026, 9, 10), "Rates raised. Inflation is at target."),
        ],
    )
    assert refresh_diffs(clean_db) == 3
    ecb_events = stored_events(clean_db, "ECB")
    first, second = ecb_events
    assert first.statement_diff["previous_event_id"] is None
    assert second.statement_diff == {
        "added": ["Rates raised."],
        "removed": ["Rates unchanged."],
        "previous_event_id": first.id,
    }
    assert refresh_diffs(clean_db) == 0

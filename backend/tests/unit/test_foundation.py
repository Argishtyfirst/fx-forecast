"""Smoke tests for the shared foundation modules."""

import datetime as dt

import pandas as pd

from fxf import calendars as cal
from fxf.data_access import point_in_time_series
from fxf.events.features import cb_feature_frame, meetings_in_window
from fxf.jobs import job_run, run_job
from fxf.models import JobRun


def test_target2_skips_christmas_and_weekend():
    assert not cal.is_trading_day(cal.CALENDAR_TARGET2, dt.date(2026, 12, 25))
    assert not cal.is_trading_day(cal.CALENDAR_TARGET2, dt.date(2026, 12, 26))
    assert cal.add_trading_days(cal.CALENDAR_TARGET2, dt.date(2026, 12, 24), 1) == dt.date(
        2026, 12, 28
    )


def test_armenia_calendar_skips_army_day():
    assert not cal.is_trading_day(cal.CALENDAR_AM, dt.date(2026, 1, 28))


def test_us_calendar_skips_thanksgiving():
    assert not cal.is_trading_day(cal.CALENDAR_US, dt.date(2026, 11, 26))


def test_point_in_time_series_hides_unpublished_values():
    frame = pd.DataFrame(
        {
            "value": [1.0, 2.0],
            "published_at": pd.to_datetime(["2026-01-02T12:00Z", "2026-01-06T12:00Z"]),
        },
        index=pd.DatetimeIndex(["2026-01-01", "2026-01-02"]),
    )
    s = point_in_time_series(
        frame, pd.DatetimeIndex(["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"])
    )
    assert pd.isna(s.iloc[0])
    assert s.tolist()[1:] == [1.0, 1.0, 2.0]


def test_cb_features_use_only_prior_decisions():
    meetings = pd.DataFrame(
        {
            "bank": ["ECB", "ECB"],
            "date": pd.to_datetime(["2026-01-10", "2026-02-10"]),
            "scheduled": [True, True],
        }
    )
    events = pd.DataFrame(
        {
            "bank": ["ECB"],
            "date": pd.to_datetime(["2026-01-10"]),
            "surprise_bps": [25.0],
            "hawkish_score": [0.5],
            "rate_after": [2.0],
        }
    )
    f = cb_feature_frame(pd.DatetimeIndex(["2026-01-10", "2026-01-11"]), meetings, events)
    assert f.loc["2026-01-10", "last_surprise_ECB"] == 0.0  # same-day decision is not yet visible
    assert f.loc["2026-01-11", "last_surprise_ECB"] == 25.0
    assert f.loc["2026-01-11", "days_to_next_ECB"] == 30
    assert meetings_in_window(meetings, ["ECB"], dt.date(2026, 1, 10), dt.date(2026, 2, 10)) == [
        {"bank": "ECB", "date": "2026-02-10"}
    ]


def test_job_run_records_success_and_failure(clean_db, _capture_alerts):
    with job_run("unit_job", engine=clean_db) as run:
        run.rows_written = 3

    def boom(_):
        raise RuntimeError("source down")

    assert run_job("unit_job", boom, engine=clean_db) is False
    from sqlalchemy.orm import Session

    with Session(clean_db) as s:
        rows = s.query(JobRun).order_by(JobRun.id).all()
    assert [(r.status, r.rows_written) for r in rows] == [("success", 3), ("failed", 0)]
    assert "source down" in rows[1].error
    assert _capture_alerts and "unit_job" in _capture_alerts[0]["title"]


def test_fed_mid_falls_back_to_the_feds_own_decisions_after_freds_last_value(session):
    import datetime as dt
    from decimal import Decimal

    from fxf.constants import FED_MID
    from fxf.data_access import load_macro_frame
    from fxf.models import CbEvent, MacroSeries, utcnow

    for sid, v in (("DFEDTARU", "4.50"), ("DFEDTARL", "4.25")):
        session.add(
            MacroSeries(
                series_id=sid,
                date=dt.date(2026, 9, 10),
                value=Decimal(v),
                source="fred",
                published_at=dt.datetime(2026, 9, 10, tzinfo=dt.UTC),
                fetched_at=utcnow(),
            )
        )
    session.add(
        CbEvent(
            bank="FED",
            date=dt.date(2026, 7, 29),
            rate_type="target_mid",
            rate_after=Decimal("4.375"),
        )
    )
    session.add(
        CbEvent(
            bank="FED",
            date=dt.date(2026, 9, 16),
            rate_type="target_mid",
            rate_after=Decimal("4.125"),
        )
    )
    session.commit()

    frame = load_macro_frame(session, FED_MID)
    assert frame["value"].tolist() == [4.375, 4.125]  # FRED's value, then the Fed's decision
    assert frame.index[-1] == pd.Timestamp("2026-09-17")  # effective the next day
    assert frame["published_at"].iloc[-1] == pd.Timestamp("2026-09-16T19:00Z")

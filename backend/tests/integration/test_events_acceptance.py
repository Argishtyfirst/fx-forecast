"""Acceptance tests for central bank events (FR-05, FR-06, FR-07, FR-12) on recorded fixtures.

Every external source is mocked with respx; no network.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxf import http
from fxf.constants import ATLFED_SERIES
from fxf.events import atlanta, calendar, cba, ecb, fed, live
from fxf.events.pipeline import backfill_events, run_events
from fxf.models import CbEvent, CbMeeting, MacroSeries

FED_T = dt.datetime(2026, 9, 16, 18, 0, tzinfo=dt.UTC)  # RSS pubDate of the FOMC statement
ECB_T = dt.datetime(2026, 9, 10, 12, 15, tzinfo=dt.UTC)
CBA_T = dt.datetime(2026, 9, 15, 8, 0, tzinfo=dt.UTC)  # 12:00 Yerevan
FED_STATEMENT = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm"
ECB_RELEASE = "https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.mp260910~314e508016.en.html"
CBA_RELEASE = "https://www.cba.am/en/press-releases/10606/"
CBA_EMPS = "https://www.cba.am/file_manager/Monetary%20policy%20en/Statement/EMPS_Q3_2026_Eng.pdf"
CBA_CALENDAR = "https://www.cba.am/file_manager/Interest-rate-calendar-2026-2028-eng.pdf"


@pytest.fixture(autouse=True)
def _no_api_key_no_sleep(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from fxf.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(http, "sleep", lambda s: None)


def _routes(router: respx.Router, fx: Path, *, cba_down: bool = False) -> None:
    text = lambda p: httpx.Response(200, text=(fx / p).read_text())  # noqa: E731
    raw = lambda p: httpx.Response(200, content=(fx / p).read_bytes())  # noqa: E731
    router.get(fed.RSS_URL).mock(return_value=text("fed/press_monetary.xml"))
    router.get(FED_STATEMENT).mock(return_value=text("fed/monetary20260916a.htm"))
    router.get(calendar.FED_CALENDAR_URL).mock(return_value=text("fed/fomccalendars.htm"))
    router.get(calendar.FED_HISTORICAL_URL.format(year=2020)).mock(
        return_value=text("fed/fomchistorical2020.htm")
    )
    router.get(ecb.RSS_URL).mock(return_value=text("ecb_rss/press_with_decision.xml"))
    router.get(ECB_RELEASE).mock(return_value=text("ecb_decisions/mp260910.htm"))
    router.get(calendar.ECB_SCHEDULE_URL).mock(return_value=text("ecb_rss/mgcgc.htm"))
    router.get(calendar.ECB_DECISIONS_URL.format(year=2026)).mock(
        return_value=text("ecb_rss/mopo_2026_include.htm")
    )
    router.get(calendar.ECB_DECISIONS_URL.format(year=2025)).mock(
        return_value=text("ecb_rss/mopo_2026_include.htm")
    )
    router.get(url__startswith=ecb.FM_URL.format(key="DFR")).mock(
        return_value=text("ecb_decisions/fm_dfr.csv")
    )
    router.get(url__startswith=ecb.FM_URL.format(key="MRR_FR")).mock(
        return_value=text("ecb_decisions/fm_mrr_fr.csv")
    )
    router.get(url__startswith=ecb.FM_URL.format(key="MLFR")).mock(return_value=httpx.Response(500))
    if cba_down:
        router.get(cba.PRESS_URL).mock(return_value=httpx.Response(503))
    else:
        router.get(cba.PRESS_URL).mock(return_value=text("cba/press_list.htm"))
    router.get(CBA_RELEASE).mock(return_value=text("cba/press_10606.htm"))
    router.get(CBA_EMPS).mock(return_value=raw("cba/emps_q3_2026_eng.pdf"))
    router.get(cba.DMP_URL).mock(return_value=text("cba/decision_making_process.htm"))
    router.get(CBA_CALENDAR).mock(return_value=raw("cba/interest_rate_calendar_2026_2028_eng.pdf"))
    router.get(url__startswith=cba.RATES_URL).mock(
        return_value=httpx.Response(
            200, json=json.loads((fx / "cba/rates_export.json").read_text())
        )
    )
    router.get(url__startswith="https://old.cba.am/").mock(
        return_value=text("cba/old_news_18032025.htm")
    )
    router.get(cba.ARKA_RSS_URL).mock(return_value=text("arka/rss.xml"))
    router.get(cba.INTERFAX_RSS_URL).mock(return_value=text("interfax/rss.xml"))
    router.get(atlanta.MPT_URL).mock(return_value=raw("atlanta_fed/mpt_histdata_trimmed.xlsx"))
    router.get(url__startswith=atlanta.SOFR_URL).mock(
        return_value=httpx.Response(
            200, json=json.loads((fx / "atlanta_fed/sofr.json").read_text())
        )
    )
    # Anything else on these hosts is a page we did not record: answer like a missing page.
    for host in (
        "https://www.federalreserve.gov/",
        "https://www.ecb.europa.eu/",
        "https://www.cba.am/",
    ):
        router.get(url__startswith=host).mock(return_value=httpx.Response(404))


def _seed_rate_series(engine) -> None:
    """DFEDTARU/L as the FRED ingest job stores them (owned by fxf.ingest; inserted here)."""
    rows = []
    for d in (dt.date(2026, 9, 1) + dt.timedelta(days=i) for i in range(40)):
        up = 3.75 if d <= dt.date(2026, 9, 16) else 4.0
        for sid, v in (("DFEDTARU", up), ("DFEDTARL", up - 0.25)):
            rows.append(
                MacroSeries(
                    series_id=sid,
                    date=d,
                    value=v,
                    source="fred",
                    published_at=dt.datetime.combine(
                        d + dt.timedelta(days=1), dt.time(14), tzinfo=dt.UTC
                    ),
                    fetched_at=dt.datetime(2026, 10, 21, tzinfo=dt.UTC),
                )
            )
    with Session(engine) as s:
        s.add_all(rows)
        s.commit()


@pytest.fixture
def world(clean_db, fixtures_dir):
    calendar.load_seed_into_db(clean_db)
    _seed_rate_series(clean_db)
    with respx.mock(assert_all_called=False) as router:
        _routes(router, fixtures_dir)
        yield clean_db


def _event(engine, bank: str, day: dt.date) -> CbEvent | None:
    with Session(engine) as s:
        return s.scalars(select(CbEvent).where(CbEvent.bank == bank, CbEvent.date == day)).first()


def test_fr05_decision_recorded_within_2_hours(world):
    """A Fed RSS item published at T, polled at T+50 min: the event exists, published_at = T."""
    result = run_events(world, now=FED_T + dt.timedelta(minutes=50))
    assert result["fed_rss"] is True
    ev = _event(world, "FED", dt.date(2026, 9, 16))
    assert ev is not None
    assert ev.published_at == FED_T
    assert ev.created_at - ev.published_at < dt.timedelta(hours=2)
    assert ev.source == "fed_rss" and ev.statement_url == FED_STATEMENT
    assert ev.rate_type == "target_mid"
    assert float(ev.rate_before) == 3.625 and float(ev.rate_after) == 3.875
    assert ev.rates_json["upper"] == {"before": 3.75, "after": 4.0}
    assert ev.statement_text.startswith("The Federal Open Market Committee approved")


def test_fr05_ecb_decision_recorded_within_2_hours(world):
    run_events(world, now=ECB_T + dt.timedelta(minutes=50))
    ev = _event(world, "ECB", dt.date(2026, 9, 10))
    assert ev is not None and ev.published_at == ECB_T
    assert ev.created_at - ev.published_at < dt.timedelta(hours=2)
    assert ev.rate_type == "deposit" and float(ev.rate_after) == 2.5
    assert ev.rates_json["mro"]["after"] == 2.65 and ev.rates_json["mlf"]["after"] == 2.9


def test_fr05_cba_decision_recorded_within_2_hours_with_all_three_rates(world):
    result = run_events(world, now=CBA_T + dt.timedelta(minutes=50))
    assert result["cba_news"] is True
    ev = _event(world, "CBA", dt.date(2026, 9, 15))
    assert ev is not None and ev.source == "cba_news" and ev.published_at == CBA_T
    assert ev.created_at - ev.published_at < dt.timedelta(hours=2)
    assert {k: v["after"] for k, v in ev.rates_json.items()} == {
        "refinancing": 6.75,
        "lombard": 8.25,
        "deposit": 5.25,
    }
    assert ev.statement_text.startswith(
        "The Board of the CBA decided today to increase the policy rate"
    )
    with Session(world) as s:
        refi = s.scalars(
            select(MacroSeries).where(
                MacroSeries.series_id == "CBA_REFI", MacroSeries.date == dt.date(2026, 9, 16)
            )
        ).one()
    assert float(refi.value) == 6.75 and refi.published_at == CBA_T


def test_fr05_cba_falls_back_to_arka_when_cba_am_is_down(clean_db, fixtures_dir):
    calendar.load_seed_into_db(clean_db)
    with respx.mock(assert_all_called=False) as router:
        _routes(router, fixtures_dir, cba_down=True)
        result = run_events(clean_db, now=CBA_T + dt.timedelta(minutes=50))
    assert result["cba_news"] is True
    ev = _event(clean_db, "CBA", dt.date(2026, 9, 15))
    assert ev is not None and ev.source == "cba_news:arka"
    assert ev.rates_json["refinancing"]["after"] == 6.75


def test_fr05_poll_is_idempotent(world):
    now = FED_T + dt.timedelta(minutes=50)
    run_events(world, now=now)
    first = _event(world, "FED", dt.date(2026, 9, 16))
    run_events(world, now=now + dt.timedelta(hours=1))
    with Session(world) as s:
        n = s.scalar(
            select(func.count())
            .select_from(CbEvent)
            .where(CbEvent.bank == "FED", CbEvent.date == dt.date(2026, 9, 16))
        )
        meetings = s.scalar(select(func.count()).select_from(CbMeeting))
    assert n == 1
    assert _event(world, "FED", dt.date(2026, 9, 16)).created_at == first.created_at
    assert meetings == len({(m.bank, m.date) for m in calendar.load_seed()})


def test_fr06_diff_shows_added_and_removed_sentences(world):
    prev = "The Committee decided to maintain the target range for the federal funds rate at 3-1/2 to 3-3/4 percent. Inflation remains elevated."
    from fxf.events.decisions import Decision, upsert_events

    upsert_events(
        world,
        [
            Decision(
                "FED",
                dt.date(2026, 7, 29),
                fed.rates_from_range(3.5, 3.75),
                fed.rates_from_range(3.5, 3.75),
                statement_text=prev,
            )
        ],
    )
    run_events(world, now=FED_T + dt.timedelta(minutes=50))
    ev = _event(world, "FED", dt.date(2026, 9, 16))
    july = _event(world, "FED", dt.date(2026, 7, 29))
    diff = ev.statement_diff
    assert diff["previous_event_id"] == july.id
    # Unchanged sentences are neither added nor removed.
    assert "Inflation remains elevated." not in diff["added"] + diff["removed"]
    assert any(
        s.startswith("The Committee decided to raise the target range") for s in diff["added"]
    )
    assert diff["removed"] == [
        "The Committee decided to maintain the target range for the federal funds rate at 3-1/2 to 3-3/4 percent."
    ]


def test_fr07_statements_are_scored_with_version_after_poll(world):
    run_events(world, now=FED_T + dt.timedelta(minutes=50))
    ev = _event(world, "FED", dt.date(2026, 9, 16))
    assert ev.scorer_version == "lexicon@v1"  # no ANTHROPIC_API_KEY in tests
    assert -1.0 <= ev.hawkish_score <= 1.0 and ev.hawkish_reason


def test_fr12_calendar_refresh_keeps_six_months_ahead(world):
    now = dt.datetime(2026, 10, 21, 9, tzinfo=dt.UTC)
    result = run_events(world, now=now)
    assert result["fed_calendar"] and result["ecb_calendar"] and result["cba_calendar"]
    for bank in ("FED", "ECB", "CBA"):
        future = [m.date for m in calendar.stored_meetings(world, bank) if m.date > now.date()]
        assert max(future) >= now.date() + dt.timedelta(days=183), bank


def test_backfill_events_writes_all_tables_on_fixtures(clean_db, fixtures_dir, monkeypatch):
    monkeypatch.setattr(calendar, "FED_HISTORY_FROM", 2020)
    monkeypatch.setattr(calendar, "ECB_HISTORY_FROM", 2026)
    monkeypatch.setattr(live, "STATEMENT_BACKFILL_N", 2)
    _seed_rate_series(clean_db)

    def fed_meetings(*, full=False, today=None):
        # The current-page fixture covers 2025-2027; history comes from the 2020 page only.
        meetings = calendar.parse_fed_calendar((fixtures_dir / "fed/fomccalendars.htm").read_text())
        if full:
            meetings += calendar.parse_fed_historical(
                (fixtures_dir / "fed/fomchistorical2020.htm").read_text(), 2020
            )
        return meetings

    monkeypatch.setattr(calendar, "fetch_fed_meetings", fed_meetings)
    with respx.mock(assert_all_called=False) as router:
        _routes(router, fixtures_dir)
        result = backfill_events(clean_db)
    failed = {k for k, ok in result.items() if not ok}
    from fxf import alerts

    assert failed == set(), (failed, [a["text"][:400] for a in alerts.SENT])
    with Session(clean_db) as s:
        count = lambda q: s.scalar(select(func.count()).select_from(q.subquery()))  # noqa: E731
        assert count(select(CbMeeting.date).where(CbMeeting.bank == "CBA")) >= 200
        cba_events = count(select(CbEvent.id).where(CbEvent.bank == "CBA"))
        assert cba_events == len(cba.load_decisions())
        assert (
            count(
                select(CbEvent.id).where(CbEvent.bank == "ECB", CbEvent.date >= dt.date(2026, 6, 1))
            )
            == 3
        )
        assert count(select(MacroSeries.date).where(MacroSeries.series_id == "CBA_REFI")) == len(
            cba.load_decisions()
        )
        assert count(select(MacroSeries.date).where(MacroSeries.series_id == ATLFED_SERIES)) == 5
        sept = s.scalars(
            select(CbEvent).where(CbEvent.bank == "FED", CbEvent.date == dt.date(2026, 9, 16))
        ).one()
        assert sept.statement_text and sept.scorer_version == "lexicon@v1"
        assert sept.expected_source in ("atlanta_fed_mpt", "previous_rate")
        texts = count(select(CbEvent.id).where(CbEvent.statement_text.is_not(None)))
        assert texts >= 4

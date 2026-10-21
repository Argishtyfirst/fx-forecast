"""Macro ingest plumbing: FRED path choice, request windows and per-series isolation."""

from __future__ import annotations

import datetime as dt
import json
import traceback
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session

from fxf import http
from fxf.config import get_settings
from fxf.http import SchemaError, SourceError
from fxf.ingest import ecb, fred
from fxf.ingest.store import (
    MACRO_HISTORY_START,
    IngestError,
    Point,
    ingest_macro,
    parse_decimal,
)
from fxf.jobs import RunContext
from fxf.models import MacroSeries

FIX = Path(__file__).resolve().parents[1] / "fixtures"
NOW = dt.datetime(2026, 10, 21, 12, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(http, "sleep", lambda _s: None)


@pytest.fixture
def fred_key(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key-0000")
    get_settings.cache_clear()
    yield "test-key-0000"
    get_settings.cache_clear()


@pytest.fixture
def no_fred_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    get_settings.cache_clear()


def test_parse_decimal_skips_missing_markers():
    assert parse_decimal("x", "4.05") == Decimal("4.05")
    for missing in ("", ".", " ", "NaN"):
        assert parse_decimal("x", missing) is None
    with pytest.raises(SchemaError):
        parse_decimal("x", "n/a")
    with pytest.raises(SchemaError):
        parse_decimal("x", "Infinity")


@respx.mock
def test_fred_uses_the_api_when_a_key_is_set(fred_key):
    body = json.loads((FIX / "fred" / "api_DGS2.json").read_text())
    route = respx.get(fred.API_URL).mock(return_value=httpx.Response(200, json=body))

    points = fred.fetch_series("DGS2", dt.date(2026, 6, 1))

    params = route.calls.last.request.url.params
    assert params["series_id"] == "DGS2"
    assert params["api_key"] == fred_key
    assert params["file_type"] == "json"
    assert params["observation_start"] == "2026-06-01"
    assert len(points) == len(body["observations"]) - 4  # four "." observations


@respx.mock
def test_fred_falls_back_to_the_public_csv_without_a_key(no_fred_key):
    text = (FIX / "fred" / "DGS2.csv").read_text()
    route = respx.get(fred.CSV_URL).mock(return_value=httpx.Response(200, text=text))

    points = fred.fetch_series("DGS2", dt.date(2026, 6, 1))

    params = route.calls.last.request.url.params
    assert (params["id"], params["cosd"]) == ("DGS2", "2026-06-01")
    assert "api_key" not in params
    assert points[0] == Point(dt.date(2026, 6, 1), Decimal("4.05"))


@respx.mock
@pytest.mark.parametrize("status", [400, 503])
def test_fred_api_key_does_not_leak_into_errors(fred_key, status):
    respx.get(fred.API_URL).mock(return_value=httpx.Response(status, json={"error_code": status}))
    with pytest.raises(SourceError) as info:
        fred.fetch_series("DGS2", dt.date(2026, 6, 1))
    # job_runs.error stores the formatted traceback, chained causes included.
    assert fred_key not in "".join(traceback.format_exception(info.value))


@respx.mock
def test_ecb_request_asks_for_data_only_csv_from_start():
    route = respx.get(url__startswith=ecb.BASE_URL).mock(return_value=httpx.Response(200, text=""))

    assert ecb.fetch_series("HICP", dt.date(2026, 8, 1)) == []

    req = route.calls.last.request
    assert req.url.path == "/service/data/HICP/M.U2.N.000000.4D0.ANR"
    assert dict(req.url.params) == {
        "format": "csvdata",
        "detail": "dataonly",
        "startPeriod": "2026-08-01",
    }


def test_ecb_keys_cover_every_ecb_series():
    from fxf.constants import ECB_SERIES

    assert set(ecb.SERIES_KEYS) == set(ECB_SERIES)


def test_ingest_macro_keeps_going_when_one_series_fails(clean_db):
    asked: dict[str, dt.date] = {}

    def fetch(series_id: str, start: dt.date) -> list[Point]:
        asked[series_id] = start
        if series_id == "DGS2":
            raise SchemaError("fred: DGS2: unexpected CSV header")
        return [Point(dt.date(2026, 10, 19), Decimal("1.5"))]

    ctx = RunContext(job="fred", run_id=0)
    with pytest.raises(SchemaError, match="DGS2"):
        ingest_macro(
            ctx,
            source="fred",
            series_ids=("DFF", "DGS2", "DCOILBRENTEU"),
            fetch=fetch,
            engine=clean_db,
            now=NOW,
            full=False,
        )

    assert set(asked) == {"DFF", "DGS2", "DCOILBRENTEU"}
    assert set(asked.values()) == {MACRO_HISTORY_START}
    assert ctx.rows_written == 2
    assert "error" in ctx.meta["DGS2"] and ctx.meta["DFF"]["inserted"] == 1
    with Session(clean_db) as s:
        assert set(s.scalars(select(MacroSeries.series_id))) == {"DFF", "DCOILBRENTEU"}


def test_ingest_macro_combines_several_failures(clean_db):
    def fetch(series_id: str, start: dt.date) -> list[Point]:
        raise SourceError(f"{series_id} down")

    with pytest.raises(IngestError, match="DFF: SourceError: DFF down; DGS2: SourceError"):
        ingest_macro(
            RunContext(job="fred", run_id=0),
            source="fred",
            series_ids=("DFF", "DGS2"),
            fetch=fetch,
            engine=clean_db,
            now=NOW,
            full=False,
        )


def test_ingest_macro_windows_and_future_dated_series(clean_db):
    def seed(series_id: str, start: dt.date) -> list[Point]:
        if series_id == "FEDTARMD":
            return [Point(dt.date(2029, 1, 1), Decimal("3.6"))]
        return [Point(dt.date(2026, 10, 19), Decimal("3.88"))]

    run = dict(source="fred", engine=clean_db, now=NOW)
    ingest_macro(
        RunContext("fred", 0), series_ids=("DFF", "FEDTARMD"), fetch=seed, full=False, **run
    )

    asked: dict[str, dt.date] = {}

    def record(series_id: str, start: dt.date) -> list[Point]:
        asked[series_id] = start
        return []

    ingest_macro(
        RunContext("fred", 0), series_ids=("DFF", "FEDTARMD"), fetch=record, full=False, **run
    )
    # 45 days before the last observation, but never in the future (the ECB portal rejects that).
    assert asked == {"DFF": dt.date(2026, 9, 4), "FEDTARMD": NOW.date()}

    # A backfill asks for everything again, and an empty full history is an error.
    with pytest.raises(SourceError, match="no observations"):
        ingest_macro(RunContext("fred", 0), series_ids=("DFF",), fetch=record, full=True, **run)
    assert asked["DFF"] == MACRO_HISTORY_START


def test_ingest_macro_rejects_an_empty_first_load(clean_db):
    with pytest.raises(SourceError, match="no observations"):
        ingest_macro(
            RunContext("ecb_data_portal", 0),
            source="ecb_data_portal",
            series_ids=("HICP",),
            fetch=lambda _sid, _start: [],
            engine=clean_db,
            now=NOW,
            full=False,
        )

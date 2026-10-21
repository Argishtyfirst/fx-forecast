"""Contract: ECB Data Portal CSV responses (recorded 2026-10-21, detail=dataonly).

Recorded with
    GET https://data-api.ecb.europa.eu/service/data/<FLOW>/<KEY>?format=csvdata&startPeriod=<D>&detail=dataonly
for FM/D.U2.EUR.4F.KR.DFR.LEV and EST/B.EU000A2X2A25.WT (from 2026-06-01) and
HICP/M.U2.N.000000.4D0.ANR (from 2024-01-01).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from fxf.http import SchemaError
from fxf.ingest.ecb import SERIES_KEYS, parse_csv, parse_period, series_url

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "ecb"


def text(series_id: str) -> str:
    return (FIX / f"{series_id}.csv").read_text()


@pytest.mark.parametrize("series_id", list(SERIES_KEYS))
def test_recorded_csv_parses(series_id):
    body = text(series_id)
    rows = body.strip().splitlines()[1:]
    points = parse_csv(series_id, body)
    assert len(points) == len(rows) > 0
    assert points == sorted(points)
    flow, key = SERIES_KEYS[series_id]
    assert all(r.startswith(f"{flow}.{key},") for r in rows)


def test_deposit_rate_is_daily_and_shows_the_2026_decisions():
    points = {p.date: p.value for p in parse_csv("ECB_DFR", text("ECB_DFR"))}
    assert points[dt.date(2026, 6, 16)] == Decimal("2")
    assert points[dt.date(2026, 6, 17)] == Decimal("2.25")
    assert points[dt.date(2026, 9, 16)] == Decimal("2.5")
    assert dt.date(2026, 6, 20) in points  # a Saturday: the series covers calendar days


def test_monthly_periods_are_stored_on_the_first_of_the_month():
    points = parse_csv("HICP", text("HICP"))
    assert points[0].date == dt.date(2024, 1, 1)
    assert points[-1] == (dt.date(2026, 9, 1), Decimal("3.8"))


def test_empty_body_means_no_new_observations():
    assert parse_csv("HICP", "") == []
    assert parse_csv("HICP", "\r\n") == []


@pytest.mark.parametrize("drop", ["TIME_PERIOD", "OBS_VALUE"])
def test_missing_columns_raise_schema_error(drop):
    body = text("ESTR").replace(drop, "SOMETHING_ELSE", 1)
    with pytest.raises(SchemaError, match=drop):
        parse_csv("ESTR", body)


@pytest.mark.parametrize(
    "body",
    [
        "<html><body>Your access has been blocked</body></html>",
        "KEY,TIME_PERIOD,OBS_VALUE\nX,2026-Q3,1.0\n",
        "KEY,TIME_PERIOD,OBS_VALUE\nX,2026-10-01,abc\n",
        "KEY,TIME_PERIOD,OBS_VALUE\nX,2026-10-01,1.0\nX,2026-10-01,1.1\n",
    ],
    ids=["html", "quarterly", "text-value", "dupe"],
)
def test_unknown_shape_raises_schema_error(body):
    with pytest.raises(SchemaError):
        parse_csv("ESTR", body)


def test_period_parsing():
    assert parse_period("x", "2026-10-20") == dt.date(2026, 10, 20)
    assert parse_period("x", "2026-09") == dt.date(2026, 9, 1)
    with pytest.raises(SchemaError):
        parse_period("x", "2026-13")


def test_series_urls():
    assert series_url("HICP") == (
        "https://data-api.ecb.europa.eu/service/data/HICP/M.U2.N.000000.4D0.ANR"
    )
    assert series_url("ECB_DFR").endswith("/FM/D.U2.EUR.4F.KR.DFR.LEV")

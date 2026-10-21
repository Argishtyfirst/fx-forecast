"""Contract: FRED responses for both access paths.

fred/<ID>.csv are real fredgraph.csv responses recorded 2026-10-21 with
    GET https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>&cosd=2026-06-01
(FEDTARMD with cosd=2020-01-01). No API key was available, so fred/api_DGS2.json
was built from the recorded DGS2 CSV in the documented series/observations shape
(https://fred.stlouisfed.org/docs/api/fred/series_observations.html), with "." for
the missing days, exactly as the API marks them.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

from fxf.constants import FRED_SERIES
from fxf.http import SchemaError
from fxf.ingest.fred import parse_api, parse_csv

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "fred"


def csv_text(series_id: str) -> str:
    return (FIX / f"{series_id}.csv").read_text()


@pytest.mark.parametrize("series_id", FRED_SERIES)
def test_recorded_csv_parses(series_id):
    text = csv_text(series_id)
    header, *rows = text.splitlines()
    assert header == f"observation_date,{series_id}"
    points = parse_csv(series_id, text)
    missing = sum(1 for r in rows if r.split(",")[1] in ("", "."))
    assert len(points) == len(rows) - missing > 0
    assert points == sorted(points)


def test_csv_skips_missing_values():
    points = {p.date: p.value for p in parse_csv("DGS2", csv_text("DGS2"))}
    assert dt.date(2026, 7, 3) not in points  # observed Independence Day: empty cell
    assert dt.date(2026, 10, 12) not in points  # Columbus Day
    assert points[dt.date(2026, 10, 9)] == Decimal("4.80")


def test_csv_projection_series_has_future_dates():
    points = parse_csv("FEDTARMD", csv_text("FEDTARMD"))
    assert [p.date.year for p in points] == [2026, 2027, 2028, 2029]


def test_api_json_parses_and_skips_dots():
    payload = json.loads((FIX / "api_DGS2.json").read_text())
    points = parse_api("DGS2", payload)
    dots = [o["date"] for o in payload["observations"] if o["value"] == "."]
    assert len(dots) == 4
    assert len(points) == len(payload["observations"]) - len(dots)
    # Both paths give the same observations.
    assert points == parse_csv("DGS2", csv_text("DGS2"))


@pytest.mark.parametrize(
    "text",
    [
        "<!DOCTYPE html>\n<html><body>Not found</body></html>\n",
        "DATE,VALUE\n2026-10-01,3.88\n",
        "observation_date,DFF,EXTRA\n2026-10-01,3.88,1\n",
        "observation_date,DGS2\n2026-10-01,3.88\n",  # another series
        "observation_date,DFF\n01/10/2026,3.88\n",
        "observation_date,DFF\n2026-10-01,high\n",
        "observation_date,DFF\n2026-10-01,3.88\n2026-10-01,3.89\n",
        "",
    ],
    ids=[
        "html",
        "wrong-header",
        "extra-column",
        "other-series",
        "bad-date",
        "text",
        "dupe",
        "empty",
    ],
)
def test_unknown_csv_shape_raises_schema_error(text):
    with pytest.raises(SchemaError):
        parse_csv("DFF", text)


@pytest.mark.parametrize(
    "payload",
    [
        {"error_code": 400, "error_message": "Bad Request.  Variable api_key is not set."},
        {"observations": [{"date": "2026-10-01"}]},
        {"observations": [{"date": "not a date", "value": "3.88"}]},
        {"observations": [{"date": "2026-10-01", "value": "high"}]},
        [],
    ],
    ids=["error-body", "no-value", "bad-date", "text", "list"],
)
def test_unknown_api_shape_raises_schema_error(payload):
    with pytest.raises(SchemaError):
        parse_api("DFF", payload)

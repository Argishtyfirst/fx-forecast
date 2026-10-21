"""Contract: Frankfurter /v2/rates responses (recorded 2026-10-21, trimmed to 2025 onward).

Recorded with:
    GET https://api.frankfurter.dev/v2/rates?base=EUR&quotes=USD&providers=ECB&from=1999-01-01
    GET https://api.frankfurter.dev/v2/rates?base=USD&quotes=AMD,RUB&providers=CBA&from=1990-01-01
    GET https://api.frankfurter.dev/v2/rates?base=EUR&quotes=AMD&providers=CBA&from=1990-01-01
    GET https://api.frankfurter.dev/v2/rates?base=RUB&quotes=AMD&providers=CBA&from=1990-01-01
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

from fxf.http import SchemaError
from fxf.ingest.frankfurter import SERIES, parse_timeseries

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "frankfurter"
(EURUSD,) = SERIES["frankfurter_ecb"]
USDAMD, EURAMD, RUBAMD = SERIES["frankfurter_cba"]


def load(name: str) -> list[dict]:
    return json.loads((FIX / name).read_text())


@pytest.mark.parametrize(
    ("name", "series", "first", "last"),
    [
        ("ecb_EUR_USD.json", EURUSD, ("2025-01-02", "1.0321"), "2026-10-20"),
        ("cba_USD_AMD.json", USDAMD, None, "2026-10-21"),
        ("cba_EUR_AMD.json", EURAMD, ("2025-01-03", "408.17"), "2026-10-21"),
        ("cba_RUB_AMD.json", RUBAMD, None, "2026-10-21"),
    ],
)
def test_recorded_timeseries_parses(name, series, first, last):
    payload = load(name)
    points = parse_timeseries("frankfurter", payload, series)
    assert len(points) == len(payload)
    assert points == sorted(points)
    assert points[-1].date == dt.date.fromisoformat(last)
    assert all(isinstance(p.value, Decimal) and p.value > 0 for p in points)
    if first:
        assert (points[0].date.isoformat(), str(points[0].value)) == first


def test_rubamd_fixes_on_the_same_dates_as_usdamd():
    usd = parse_timeseries("f", load("cba_USD_AMD.json"), USDAMD)
    rub = parse_timeseries("f", load("cba_RUB_AMD.json"), RUBAMD)
    assert [p.date for p in rub] == [p.date for p in usd]


def test_extra_fields_are_tolerated():
    payload = load("ecb_EUR_USD.json")[:3]
    for row in payload:
        row["provider"] = "ECB"
    assert len(parse_timeseries("f", payload, EURUSD)) == 3


@pytest.mark.parametrize(
    "mutate",
    [
        lambda rows: {"rates": rows},  # object instead of list
        lambda rows: [{k: v for k, v in r.items() if k != "rate"} for r in rows],
        lambda rows: [{**r, "rate": "n/a"} for r in rows],
        lambda rows: [{**r, "rate": -1} for r in rows],
        lambda rows: [{**r, "date": "21/10/2026"} for r in rows],
        lambda rows: [{**r, "quote": "GBP"} for r in rows],  # not the pair we asked for
        lambda rows: rows + rows[:1],  # duplicate date
        lambda rows: {"status": 422, "message": "invalid currency: XXX"},
    ],
    ids=["object", "no-rate", "text-rate", "negative", "bad-date", "wrong-quote", "dupe", "error"],
)
def test_unknown_shape_raises_schema_error(mutate):
    rows = copy.deepcopy(load("ecb_EUR_USD.json")[:5])
    with pytest.raises(SchemaError):
        parse_timeseries("frankfurter_ecb", mutate(rows), EURUSD)


def test_empty_window_is_valid():
    assert parse_timeseries("frankfurter_ecb", [], EURUSD) == []

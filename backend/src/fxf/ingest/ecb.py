"""ECB Data Portal series (FR-04): deposit facility rate, €STR, euro area HICP.

Keys were checked against the live API on 2026-10-21. The old HICP key
ICP/M.U2.N.000000.4.ANR stops at 2025-12: from 2026 the ECB publishes HICP
(ECOICOP v2) in the HICP dataflow with a DATA_PROVIDER dimension, so we read
HICP/M.U2.N.000000.4D0.ANR (Eurostat, annual rate, back to 1991).

The CSV has one row per observation with TIME_PERIOD and OBS_VALUE columns. A
window with no observations comes back as 200 with an empty body. Monthly periods
(YYYY-MM) are stored on the first day of the month.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Final

from sqlalchemy import Engine

from fxf import http
from fxf.constants import ECB_SERIES, SOURCE_ECB
from fxf.http import SchemaError
from fxf.ingest.store import Point, ingest_macro, parse_decimal, unique_points
from fxf.jobs import RunContext

BASE_URL: Final = "https://data-api.ecb.europa.eu/service/data"
# series_id -> (dataflow, series key)
SERIES_KEYS: Final[dict[str, tuple[str, str]]] = {
    "ECB_DFR": ("FM", "D.U2.EUR.4F.KR.DFR.LEV"),
    "ESTR": ("EST", "B.EU000A2X2A25.WT"),
    "HICP": ("HICP", "M.U2.N.000000.4D0.ANR"),
}
REQUIRED_COLUMNS: Final = ("TIME_PERIOD", "OBS_VALUE")


def parse_period(where: str, period: str) -> dt.date:
    try:
        if len(period) == 10:
            return dt.date.fromisoformat(period)
        if len(period) == 7:
            return dt.date.fromisoformat(f"{period}-01")
    except ValueError:
        pass
    raise SchemaError(f"{where}: unsupported TIME_PERIOD {period!r}")


def parse_csv(series_id: str, text: str) -> list[Point]:
    where = f"{SOURCE_ECB}: {series_id}"
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise SchemaError(f"{where}: missing columns {missing} in {reader.fieldnames!r:.200}")
    points = []
    for row in reader:
        value = parse_decimal(where, row["OBS_VALUE"] or "")
        if value is not None:
            points.append(Point(parse_period(where, row["TIME_PERIOD"] or ""), value))
    return unique_points(where, points)


def series_url(series_id: str) -> str:
    flow, key = SERIES_KEYS[series_id]
    return f"{BASE_URL}/{flow}/{key}"


def fetch_series(series_id: str, start: dt.date) -> list[Point]:
    # startPeriod must not lie in the future: the portal's firewall answers that with 400.
    params = {"format": "csvdata", "detail": "dataonly", "startPeriod": start.isoformat()}
    text = http.fetch_text(SOURCE_ECB, series_url(series_id), params=params, ext="csv")
    return parse_csv(series_id, text)


def ingest(ctx: RunContext, *, engine: Engine | None, now: dt.datetime, full: bool = False) -> None:
    ingest_macro(
        ctx,
        source=SOURCE_ECB,
        series_ids=ECB_SERIES,
        fetch=fetch_series,
        engine=engine,
        now=now,
        full=full,
    )

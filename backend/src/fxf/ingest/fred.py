"""FRED macro series (FR-04): Fed target range, EFFR, 2-year yield, Brent, broad dollar.

With FRED_API_KEY set, the job uses the documented JSON API. Without it, it reads the
public fredgraph.csv download, which needs no key and has the same observations.
Both mark missing observations ("." in the API, an empty cell in the CSV); those are
skipped, never stored as zero.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Final

from pydantic import BaseModel
from sqlalchemy import Engine

from fxf import http
from fxf.config import get_settings
from fxf.constants import FRED_SERIES, SOURCE_FRED
from fxf.http import SchemaError, SourceError
from fxf.ingest.store import Point, ingest_macro, parse_decimal, unique_points
from fxf.jobs import RunContext

API_URL: Final = "https://api.stlouisfed.org/fred/series/observations"
CSV_URL: Final = "https://fred.stlouisfed.org/graph/fredgraph.csv"
# fredgraph.csv names the date column observation_date (older downloads used DATE).
CSV_DATE_COLUMNS: Final = ("observation_date", "DATE")


class FredObservation(BaseModel):
    date: dt.date
    value: str


class FredObservations(BaseModel):
    observations: list[FredObservation]


def parse_api(series_id: str, payload: object) -> list[Point]:
    return _api_points(series_id, http.validate(SOURCE_FRED, payload, FredObservations))


def _api_points(series_id: str, body: FredObservations) -> list[Point]:
    points = []
    for obs in body.observations:
        value = parse_decimal(f"{SOURCE_FRED}: {series_id}", obs.value)
        if value is not None:
            points.append(Point(obs.date, value))
    return unique_points(f"{SOURCE_FRED}: {series_id}", points)


def parse_csv(series_id: str, text: str) -> list[Point]:
    where = f"{SOURCE_FRED}: {series_id}"
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header is None or len(header) != 2 or header[0] not in CSV_DATE_COLUMNS:
        raise SchemaError(f"{where}: unexpected CSV header {header!r:.200}")
    if header[1] != series_id:
        raise SchemaError(f"{where}: CSV is for {header[1]!r}")
    points = []
    for row in reader:
        if not row:
            continue
        if len(row) != 2:
            raise SchemaError(f"{where}: malformed CSV row {row!r:.200}")
        try:
            day = dt.date.fromisoformat(row[0])
        except ValueError:
            raise SchemaError(f"{where}: bad date {row[0]!r}") from None
        value = parse_decimal(where, row[1])
        if value is not None:
            points.append(Point(day, value))
    return unique_points(where, points)


def fetch_series(series_id: str, start: dt.date) -> list[Point]:
    """Observations from start onward, from the API when a key is configured."""
    api_key = get_settings().fred_api_key
    if api_key:
        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
        }
        try:
            body = http.fetch_json(SOURCE_FRED, API_URL, FredObservations, params=params)
        except SourceError as exc:
            # httpx's own error names the full URL, api_key included, and job_runs.error
            # stores the whole traceback. Re-raise without the chained cause.
            raise type(exc)(str(exc).replace(api_key, "***")) from None
        return _api_points(series_id, body)
    params = {"id": series_id, "cosd": start.isoformat()}
    text = http.fetch_text(SOURCE_FRED, CSV_URL, params=params, ext="csv")
    return parse_csv(series_id, text)


def ingest(ctx: RunContext, *, engine: Engine | None, now: dt.datetime, full: bool = False) -> None:
    ingest_macro(
        ctx,
        source=SOURCE_FRED,
        series_ids=FRED_SERIES,
        fetch=fetch_series,
        engine=engine,
        now=now,
        full=full,
    )

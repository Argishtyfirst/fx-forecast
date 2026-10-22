"""Policy rates of the Bank of England and the Bank of Russia, for the GBP and RUB pairs
(forward rate, carry and the rate difference feature).

- BOE_BANK: Bank Rate, series IUDBEDR from the Bank of England's statistical database,
  one CSV row per day back to 1975 ("01 Sep 2026,3.75").
- CBR_KEY: the Bank of Russia key rate, one table row per day from 17 Sep 2013, when the
  key rate was introduced. Before that the RUB pairs have no policy rate: the forward
  model and the rate features are then unavailable (NaN), as for any missing rate.

Both tables give the rate in force on each day, so a row is public on its own date
(fxf.ingest.pit, like ECB_DFR).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from typing import Final

from sqlalchemy import Engine

from fxf import http
from fxf.constants import POLICY_SERIES, SOURCE_POLICY
from fxf.http import SchemaError
from fxf.ingest.store import Point, ingest_macro, parse_decimal, unique_points
from fxf.jobs import RunContext

BOE_URL: Final = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
CBR_URL: Final = "https://www.cbr.ru/eng/hd_base/KeyRate/"
CBR_START: Final = dt.date(2013, 9, 17)


def parse_boe(text: str) -> list[Point]:
    where = f"{SOURCE_POLICY}: BOE_BANK"
    reader = csv.reader(io.StringIO(text.strip()))
    header = next(reader, None)
    if not header or header[:2] != ["DATE", "IUDBEDR"]:
        raise SchemaError(f"{where}: unexpected header {header!r:.120}")
    points = []
    for row in reader:
        if len(row) < 2 or not row[0].strip():
            continue
        try:
            day = dt.datetime.strptime(row[0].strip(), "%d %b %Y").date()
        except ValueError as exc:
            raise SchemaError(f"{where}: bad date {row[0]!r}") from exc
        value = parse_decimal(where, row[1])
        if value is not None:
            points.append(Point(day, value))
    return unique_points(where, points)


def parse_cbr(html: str) -> list[Point]:
    where = f"{SOURCE_POLICY}: CBR_KEY"
    cells = re.findall(r"<td>\s*([^<]*?)\s*</td>", html)
    points = []
    for i in range(0, len(cells) - 1, 2):
        try:
            day = dt.datetime.strptime(cells[i], "%d.%m.%Y").date()
        except ValueError:
            continue
        value = parse_decimal(where, cells[i + 1])
        if value is not None:
            points.append(Point(day, value))
    if not points and "KeyRate" not in html:
        raise SchemaError(f"{where}: no key rate table in the page")
    return unique_points(where, points)


def fetch_series(series_id: str, start: dt.date) -> list[Point]:
    today = dt.date.today()
    if series_id == "BOE_BANK":
        params = {
            "csv.x": "yes",
            "Datefrom": start.strftime("%d/%b/%Y"),
            "Dateto": "now",
            "SeriesCodes": "IUDBEDR",
            "CSVF": "TN",
            "UsingCodes": "Y",
            "VPD": "Y",
            "VFD": "N",
        }
        return parse_boe(http.fetch_text(SOURCE_POLICY, BOE_URL, params=params, ext="csv"))
    if series_id == "CBR_KEY":
        params = {
            "UniDbQuery.Posted": "True",
            "UniDbQuery.From": max(start, CBR_START).strftime("%d.%m.%Y"),
            "UniDbQuery.To": today.strftime("%d.%m.%Y"),
        }
        return parse_cbr(http.fetch_text(SOURCE_POLICY, CBR_URL, params=params))
    raise ValueError(f"not a policy series: {series_id}")


def ingest(ctx: RunContext, *, engine: Engine | None, now: dt.datetime, full: bool = False) -> None:
    ingest_macro(
        ctx,
        source=SOURCE_POLICY,
        series_ids=POLICY_SERIES,
        fetch=fetch_series,
        engine=engine,
        now=now,
        full=full,
    )

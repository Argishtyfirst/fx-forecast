"""Federal Reserve: FOMC decisions from the monetary policy RSS feed and statement pages.

Live (FR-05): the hourly poll reads https://www.federalreserve.gov/feeds/press_monetary.xml,
picks "... FOMC statement" items, fetches the statement page, extracts its text and parses
"target range for the federal funds rate ... X to Y percent". published_at is the item's
pubDate, so the event exists within one poll interval (< 2 hours) of publication.

History: decisions are derived from FRED DFEDTARU / DFEDTARL (read from macro_series when
the ingest job has stored them, otherwise fetched from fredgraph.csv): rate_before is the
range on the decision date, rate_after the range three days later (FRED records the new
range from the day after the decision). Statements for history come from
newsevents/pressreleases/monetaryYYYYMMDDa.htm.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass
from typing import Any, Final
from zoneinfo import ZoneInfo

import feedparser
import pandas as pd
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from fxf import http
from fxf.constants import SOURCE_FED_RSS
from fxf.events.calendar import Meeting
from fxf.events.decisions import EXPECTED_ATLFED, Decision
from fxf.events.text import normalize_space

NEW_YORK: Final = ZoneInfo("America/New_York")
RSS_URL: Final = "https://www.federalreserve.gov/feeds/press_monetary.xml"
STATEMENT_URL: Final = (
    "https://www.federalreserve.gov/newsevents/pressreleases/monetary{d:%Y%m%d}a.htm"
)
FREDGRAPH_URL: Final = "https://fred.stlouisfed.org/graph/fredgraph.csv"
# Release time used for history when the statement time is not recorded. Later than the
# 14:00/14:15 ET scheduled releases, so point-in-time reads stay conservative.
DEFAULT_RELEASE: Final = dt.time(14, 30)
RELEASE_OVERRIDES: Final = {dt.date(2020, 3, 15): dt.time(17, 0)}
LOOKBACK: Final = dt.timedelta(days=7)


@dataclass(frozen=True)
class RssItem:
    title: str
    link: str
    published_at: dt.datetime  # UTC


class _Feed(BaseModel):
    items: list[dict[str, Any]] = Field(min_length=1)


def parse_rss(source: str, text: str) -> list[RssItem]:
    """RSS 2.0 items with title, link and pubDate. An empty or unknown feed is a SchemaError."""
    feed = feedparser.parse(text)
    items: list[RssItem] = []
    for e in feed.entries:
        tm = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
        title = normalize_space(getattr(e, "title", "") or "")
        link = (getattr(e, "link", "") or "").strip()
        if not title or not link or tm is None:
            continue
        items.append(RssItem(title, link, dt.datetime(*tm[:6], tzinfo=dt.UTC)))
    http.validate(source, {"items": [i.__dict__ for i in items]}, _Feed)
    return items


def is_fomc_statement(title: str) -> bool:
    return bool(re.search(r"\bFOMC statement\b", title, re.I))


@dataclass(frozen=True)
class FedStatement:
    url: str
    date: dt.date
    title: str
    text: str


_SKIP = re.compile(
    r"^(For media inquiries|Implementation Note|Last Update|Board of Governors)", re.I
)


def parse_statement(html: str, url: str) -> FedStatement:
    soup = BeautifulSoup(html, "lxml")
    art = soup.select_one("div#article")
    if art is None:
        raise http.SchemaError(f"{SOURCE_FED_RSS}: no article block in {url}")
    when = art.select_one(".article__time")
    title = art.select_one("h3.title") or art.select_one("h3")
    paras: list[str] = []
    for p in art.find_all("p"):
        cls = p.get("class") or []
        if any(c in cls for c in ("article__time", "releaseTime")):
            continue
        text = normalize_space(p.get_text(" ", strip=True))
        if not text:
            continue
        if _SKIP.match(text):
            break
        paras.append(text)
    if when is None or title is None or not paras:
        raise http.SchemaError(f"{SOURCE_FED_RSS}: unknown statement layout at {url}")
    try:
        day = dt.datetime.strptime(normalize_space(when.get_text()), "%B %d, %Y").date()
    except ValueError as exc:
        raise http.SchemaError(f"{SOURCE_FED_RSS}: bad statement date in {url}") from exc
    return FedStatement(url, day, normalize_space(title.get_text()), "\n".join(paras))


def fetch_statement(url: str) -> FedStatement:
    return parse_statement(http.fetch_text(SOURCE_FED_RSS, url), url)


def statement_url(day: dt.date) -> str:
    return STATEMENT_URL.format(d=day)


def release_time(day: dt.date) -> dt.datetime:
    t = RELEASE_OVERRIDES.get(day, DEFAULT_RELEASE)
    return dt.datetime.combine(day, t, tzinfo=NEW_YORK).astimezone(dt.UTC)


def rates_from_range(lower: float, upper: float) -> dict[str, float | None]:
    return {"upper": upper, "lower": lower, "mid": (upper + lower) / 2.0}


# --- rate series ----------------------------------------------------------------------------


def parse_fredgraph(series_id: str, text: str) -> pd.Series:
    reader = csv.reader(io.StringIO(text))
    header = next(reader, [])
    if len(header) != 2 or header[1] != series_id:
        raise http.SchemaError(f"{SOURCE_FED_RSS}: unexpected fredgraph header {header!r}")
    idx, vals = [], []
    for row in reader:
        if len(row) == 2 and row[1] not in ("", "."):
            idx.append(pd.Timestamp(row[0]))
            vals.append(float(row[1]))
    return pd.Series(vals, index=pd.DatetimeIndex(idx), dtype="float64")


def fetch_fredgraph(series_id: str) -> pd.Series:
    text = http.fetch_text(SOURCE_FED_RSS, FREDGRAPH_URL, params={"id": series_id}, ext="csv")
    return parse_fredgraph(series_id, text)


def asof(series: pd.Series, day: dt.date) -> float | None:
    if series.empty:
        return None
    s = series[series.index <= pd.Timestamp(day)]
    return None if s.empty else float(s.iloc[-1])


def expected_from_tracker(atl: pd.Series, day: dt.date) -> float | None:
    """The tracker's expectation for this meeting: the last observation before the decision
    day, if it is at most 7 days old."""
    if atl.empty:
        return None
    s = atl[(atl.index < pd.Timestamp(day)) & (atl.index >= pd.Timestamp(day - LOOKBACK))]
    return None if s.empty else float(s.iloc[-1])


def history_decisions(
    meetings: list[Meeting],
    upper: pd.Series,
    lower: pd.Series,
    atl: pd.Series,
    today: dt.date,
) -> list[Decision]:
    """One decision per scheduled meeting, plus unscheduled meetings that moved the range."""
    out: list[Decision] = []
    if upper.empty or lower.empty:
        return out
    first = max(upper.index.min(), lower.index.min()).date()
    for m in sorted(meetings, key=lambda m: m.date):
        if m.bank != "FED" or m.date <= first or m.date > today:
            continue
        ub, lb = asof(upper, m.date), asof(lower, m.date)
        later = m.date + dt.timedelta(days=3)
        if later > min(upper.index.max(), lower.index.max()).date():
            continue  # not yet in the series; the live RSS reader records it
        ua, la = asof(upper, later), asof(lower, later)
        if None in (ub, lb, ua, la):
            continue
        assert ub is not None and lb is not None and ua is not None and la is not None
        if not m.scheduled and (ub, lb) == (ua, la):
            continue
        d = Decision(
            "FED",
            m.date,
            before=rates_from_range(lb, ub),
            after=rates_from_range(la, ua),
            source="fred",
            published_at=release_time(m.date),
        )
        exp = expected_from_tracker(atl, m.date)
        if exp is not None:
            d.expected, d.expected_source = exp, EXPECTED_ATLFED
        out.append(d)
    return out


def item_day(item: RssItem) -> dt.date:
    return item.published_at.astimezone(NEW_YORK).date()

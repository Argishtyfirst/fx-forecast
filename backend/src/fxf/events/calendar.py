"""Meeting calendars (table cb_meetings) for the Fed, ECB and CBA.

Sources (all official pages):
- FED: federalreserve.gov/monetarypolicy/fomccalendars.htm (current five years plus the
  published future years) and fomchistoricalYYYY.htm (older years). Two-day meetings are
  stored on the decision (second) day. Unscheduled meetings and conference calls that
  produced a statement are stored on the statement date with scheduled=False (e.g.
  2020-03-03 and 2020-03-15). Notation votes and cancelled meetings are skipped.
- ECB: the Governing Council meeting schedule (ecb.europa.eu/press/calendars/mgcgc) for
  future monetary policy meetings (decision = "Day 2"), and the "Monetary policy
  decisions" listing (press/govcdec/mopo/YYYY) for past ones. Non-monetary meetings are
  not stored.
- CBA: the Board's interest-rate decision timetable PDF (decision-making-process page) for
  future meetings, and the CBA decision history (fxf.events.cba) for past ones.

The checked-in seed events/data/meetings.csv (bank,date,scheduled,source_url) was built from
these pages on 2026-10-21 so the system works offline. Refresh jobs re-read the live pages
and upsert idempotently on (bank, date).
"""

from __future__ import annotations

import csv
import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy import Engine, select

from fxf import http
from fxf.db import session_scope
from fxf.models import CbMeeting, upsert, utcnow

DATA_DIR: Final = Path(__file__).parent / "data"
SEED_MEETINGS: Final = DATA_DIR / "meetings.csv"

FED_BASE: Final = "https://www.federalreserve.gov"
FED_CALENDAR_URL: Final = f"{FED_BASE}/monetarypolicy/fomccalendars.htm"
FED_HISTORICAL_URL: Final = FED_BASE + "/monetarypolicy/fomchistorical{year}.htm"
FED_HISTORY_FROM: Final = 2008

ECB_BASE: Final = "https://www.ecb.europa.eu"
ECB_SCHEDULE_URL: Final = f"{ECB_BASE}/press/calendars/mgcgc/html/index.en.html"
ECB_DECISIONS_URL: Final = ECB_BASE + "/press/govcdec/mopo/{year}/html/index_include.en.html"
ECB_HISTORY_FROM: Final = 2008
# ECB monetary policy decisions taken outside the published schedule.
ECB_UNSCHEDULED: Final = frozenset({dt.date(2008, 10, 8)})

MONTHS: Final = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}


@dataclass(frozen=True)
class Meeting:
    bank: str
    date: dt.date
    scheduled: bool = True
    source_url: str | None = None


class _MeetingModel(BaseModel):
    bank: str
    date: dt.date
    scheduled: bool
    source_url: str | None


class _Page(BaseModel):
    meetings: list[_MeetingModel] = Field(min_length=1)


def _validated(source: str, meetings: list[Meeting]) -> list[Meeting]:
    """Fail loudly (SchemaError) when a page yields no meetings: the layout changed."""
    http.validate(source, {"meetings": [m.__dict__ for m in meetings]}, _Page)
    return meetings


def _month(name: str) -> int:
    key = name.strip().lower()[:3]
    if key not in MONTHS:
        raise ValueError(f"unknown month {name!r}")
    return MONTHS[key]


_STATEMENT_DATE = re.compile(r"(?:monetary|/monetary/)(\d{8})[a-z]?\d*\.htm")


def _statement_date(href: str) -> dt.date | None:
    m = _STATEMENT_DATE.search(href)
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def _decision_day(year: int, months: list[int], d1: int, d2: int | None) -> dt.date:
    """The last day of a meeting: "27-28" in one month, "30-1" across Apr/May."""
    if d2 is None:
        return dt.date(year, months[0], d1)
    month = months[-1] if d2 < d1 else months[0]
    return dt.date(year, month, d2)


# --- FED ------------------------------------------------------------------------------------

_FED_DAYS = re.compile(r"^\s*(\d{1,2})(?:\s*-\s*(\d{1,2}))?\s*\*?\s*(\(([^)]*)\))?", re.I)


def parse_fed_calendar(html: str, url: str = FED_CALENDAR_URL) -> list[Meeting]:
    """Meetings on fomccalendars.htm (one panel per year)."""
    soup = BeautifulSoup(html, "lxml")
    out: list[Meeting] = []
    for panel in soup.select("div.panel"):
        heading = panel.find(["h4", "h5"])
        hm = (
            re.search(r"(\d{4}) FOMC Meetings", heading.get_text(" ", strip=True))
            if heading
            else None
        )
        if not hm:
            continue
        year = int(hm.group(1))
        for row in panel.select("div.fomc-meeting"):
            month_el = row.select_one(".fomc-meeting__month")
            date_el = row.select_one(".fomc-meeting__date")
            if not month_el or not date_el:
                continue
            dm = _FED_DAYS.match(date_el.get_text(" ", strip=True))
            if not dm:
                raise http.SchemaError(f"fed calendar: cannot read {date_el.get_text()!r}")
            tag = (dm.group(4) or "").lower()
            if "notation" in tag or "cancel" in tag:
                continue
            months = [_month(p) for p in month_el.get_text(strip=True).split("/")]
            d1, d2 = int(dm.group(1)), int(dm.group(2)) if dm.group(2) else None
            day = _decision_day(year, months, d1, d2)
            scheduled = "unscheduled" not in tag
            if not scheduled:
                for a in row.find_all("a", href=True):
                    sd = _statement_date(a["href"])
                    if sd and a.get_text(strip=True).lower() in ("html", "statement"):
                        day = sd
                        break
            out.append(Meeting("FED", day, scheduled, url))
    return _validated("fed_calendar", out)


_FED_HIST = re.compile(
    r"^(?P<m1>[A-Za-z]+)(?:/(?P<m2>[A-Za-z]+))?\s+(?P<d1>\d{1,2})"
    r"(?:\s*-\s*(?:(?P<m3>[A-Za-z]+)\s*)?(?P<d2>\d{1,2}))?\s*"
    r"(?:\((?P<tag>[^)]*)\))?\s*(?P<kind>Meeting|Conference Call)?\s*-\s*(?P<year>\d{4})$",
    re.I,
)


def parse_fed_historical(html: str, year: int, url: str | None = None) -> list[Meeting]:
    """Meetings on fomchistoricalYYYY.htm. Conference calls / unscheduled meetings count
    only when they produced a statement, dated on the statement's release date."""
    url = url or FED_HISTORICAL_URL.format(year=year)
    soup = BeautifulSoup(html, "lxml")
    out: list[Meeting] = []
    for h in soup.find_all("h5"):
        title = re.sub(r"\s+", " ", h.get_text(" ", strip=True))
        if not title.endswith(f"- {year}"):
            continue
        m = _FED_HIST.match(title)
        if not m:
            raise http.SchemaError(f"fed historical {year}: cannot read heading {title!r}")
        tag = (m.group("tag") or "").lower()
        if "notation" in tag or "cancel" in tag:
            continue
        kind = (m.group("kind") or "").lower()
        unscheduled = "unscheduled" in tag or "conference" in kind
        panel = h.find_parent("div", class_="panel") or h.parent
        if unscheduled:
            stmt = None
            for a in panel.find_all("a", href=True):
                if a.get_text(strip=True).lower() == "statement":
                    stmt = _statement_date(a["href"])
                    break
            if stmt is None:
                continue
            out.append(Meeting("FED", stmt, False, url))
            continue
        months = [_month(m.group("m1"))]
        if m.group("m2"):
            months.append(_month(m.group("m2")))
        if m.group("m3"):
            months = [months[0], _month(m.group("m3"))]
        d1, d2 = int(m.group("d1")), int(m.group("d2")) if m.group("d2") else None
        day = _decision_day(year, months, d1, d2)
        out.append(Meeting("FED", day, True, url))
    return _validated(f"fed_historical_{year}", out)


# --- ECB ------------------------------------------------------------------------------------


def parse_ecb_schedule(html: str, url: str = ECB_SCHEDULE_URL) -> list[Meeting]:
    """Future monetary policy meetings from the Governing Council schedule (decision day)."""
    soup = BeautifulSoup(html, "lxml")
    out: list[Meeting] = []
    for dl in soup.select("main dl"):
        for dt_el in dl.find_all("dt"):
            dd = dt_el.find_next_sibling("dd")
            if dd is None:
                continue
            text = dd.get_text(" ", strip=True).lower()
            if "monetary policy meeting" not in text or "non-monetary" in text or "day 1" in text:
                continue
            raw = dt_el.get_text(strip=True)
            try:
                day = dt.datetime.strptime(raw, "%d/%m/%Y").date()
            except ValueError as exc:
                raise http.SchemaError(f"ecb schedule: cannot read date {raw!r}") from exc
            out.append(Meeting("ECB", day, True, url))
    # Two-day meetings without a "(Day 1)" label: keep only the decision (second) day.
    days = {m.date for m in out}
    out = [m for m in set(out) if m.date + dt.timedelta(days=1) not in days]
    return _validated("ecb_schedule", sorted(out, key=lambda m: m.date))


def parse_ecb_decisions(html: str) -> list[tuple[Meeting, str]]:
    """(meeting, decision press release URL) for each "Monetary policy decisions" item."""
    soup = BeautifulSoup(html, "lxml")
    out: list[tuple[Meeting, str]] = []
    seen: set[dt.date] = set()
    for dt_el in soup.find_all("dt"):
        iso = dt_el.get("isodate")
        dd = dt_el.find_next_sibling("dd")
        a = dd.select_one("div.title a") if dd else None
        if not iso or a is None:
            continue
        if a.get_text(strip=True).lower() != "monetary policy decisions":
            continue
        day = dt.date.fromisoformat(str(iso))
        if day in seen:
            continue
        seen.add(day)
        link = str(a.get("href", ""))
        link = link if link.startswith("http") else ECB_BASE + link
        out.append((Meeting("ECB", day, day not in ECB_UNSCHEDULED, link), link))
    http.validate("ecb_decisions", {"meetings": [m.__dict__ for m, _ in out]}, _Page)
    return sorted(out, key=lambda x: x[0].date)


# --- storage --------------------------------------------------------------------------------

_SEED_ROWS = TypeAdapter(list[_MeetingModel])


def load_seed(path: Path = SEED_MEETINGS) -> list[Meeting]:
    with path.open(newline="") as fh:
        rows = [
            {
                "bank": r["bank"],
                "date": r["date"],
                "scheduled": r["scheduled"].strip().lower() == "true",
                "source_url": r.get("source_url") or None,
            }
            for r in csv.DictReader(fh)
        ]
    return [Meeting(**m.model_dump()) for m in _SEED_ROWS.validate_python(rows)]


def write_seed(meetings: list[Meeting], path: Path = SEED_MEETINGS) -> None:
    rows = sorted({(m.bank, m.date): m for m in meetings}.values(), key=lambda m: (m.bank, m.date))
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["bank", "date", "scheduled", "source_url"])
        for m in rows:
            w.writerow([m.bank, m.date.isoformat(), str(m.scheduled).lower(), m.source_url or ""])


def store_meetings(engine: Engine | None, meetings: list[Meeting]) -> int:
    """Upsert on (bank, date); scheduled and source_url follow the latest source."""
    uniq = {(m.bank, m.date): m for m in meetings}
    now = utcnow()
    rows = [
        {
            "bank": m.bank,
            "date": m.date,
            "scheduled": m.scheduled,
            "source_url": m.source_url,
            "fetched_at": now,
        }
        for m in uniq.values()
    ]
    with session_scope(engine) as s:
        return upsert(
            s, CbMeeting, rows, ["bank", "date"], ["scheduled", "source_url", "fetched_at"]
        )


def stored_meetings(engine: Engine | None, bank: str | None = None) -> list[Meeting]:
    with session_scope(engine) as s:
        q = select(CbMeeting).order_by(CbMeeting.date)
        if bank:
            q = q.where(CbMeeting.bank == bank)
        return [Meeting(r.bank, r.date, r.scheduled, r.source_url) for r in s.scalars(q)]


def load_seed_into_db(engine: Engine | None) -> int:
    """Insert the seed calendar; existing rows keep what a live refresh wrote."""
    now = utcnow()
    rows = [
        {
            "bank": m.bank,
            "date": m.date,
            "scheduled": m.scheduled,
            "source_url": m.source_url,
            "fetched_at": now,
        }
        for m in load_seed()
    ]
    with session_scope(engine) as s:
        return upsert(s, CbMeeting, rows, ["bank", "date"])


# --- live refresh -----------------------------------------------------------------------------


def fetch_fed_meetings(*, full: bool = False, today: dt.date | None = None) -> list[Meeting]:
    meetings = parse_fed_calendar(http.fetch_text("fed_rss", FED_CALENDAR_URL))
    if full:
        first_current = min(m.date.year for m in meetings)
        for year in range(FED_HISTORY_FROM, first_current):
            url = FED_HISTORICAL_URL.format(year=year)
            meetings += parse_fed_historical(http.fetch_text("fed_rss", url), year, url)
    return meetings


def fetch_ecb_meetings(
    *, full: bool = False, today: dt.date | None = None
) -> list[tuple[Meeting, str | None]]:
    today = today or dt.date.today()
    out: list[tuple[Meeting, str | None]] = [
        (m, None) for m in parse_ecb_schedule(http.fetch_text("ecb_rss", ECB_SCHEDULE_URL))
    ]
    years = (
        range(ECB_HISTORY_FROM, today.year + 1) if full else range(today.year - 1, today.year + 1)
    )
    for year in years:
        html = http.fetch_text("ecb_rss", ECB_DECISIONS_URL.format(year=year))
        try:
            out += [(m, link) for m, link in parse_ecb_decisions(html)]
        except http.SchemaError:
            # A new year's listing is empty until its first decision (January).
            if year < today.year:
                raise
    return out

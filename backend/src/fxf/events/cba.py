"""Central Bank of Armenia: policy rates (CBA_REFI, CBA_LOMBARD, CBA_DEPOSIT), Board
decisions, statements, the meeting calendar and the ARKA / Interfax news fallback.

Sources
- Rates: cba.am statistics "Interest rates of the CBA operations in financial markets",
  JSON export (all three rates by date of setting, 2004 to now).
  The export has known defects, corrected here and in the curated seed:
  * before 2009-10-06 each row carries the rates of the previous decision (verified against
    every 2008-2009 press release), so values are shifted back by one row;
  * 2011 rows appear twice (decision date and the next day) and one duplicate is wrong;
  * a few dates sit one day off the Board meeting (2013-08-12 for 2013-08-13, ...), so dates
    within one day of a known meeting snap to it.
- Decisions: data/cba_decisions.csv (decision_date, effective_date, refinancing, lombard,
  deposit, scheduled, announced_at, source_url) curated from the export and the press
  releases (cba.am/en|hy/press-releases, old.cba.am for 2025-05-06). Holds missing from the
  export come from press releases. Not recoverable: one 2023 hold meeting (probably early
  May) has no press release on either site. Rates take effect the day after the decision
  ("interest rates valid from" in the CBA timetable), so macro_series dates are
  effective dates and published_at is the announcement time.
- Calendar: the Board's timetable PDF linked from cba.am/en/decision-making-process. The
  2026-2028 PDF draws its dates as images of text, decoded through data/cba_calendar_glyphs.json
  (bitmap signature -> text). Unknown glyphs raise SchemaError, so a new layout fails loudly.
- Live decisions: cba.am/en/press-releases on CBA meeting days; fallback ARKA and Interfax.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import feedparser
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, RootModel, TypeAdapter

from fxf import http
from fxf.constants import SOURCE_CBA, SOURCE_CBA_NEWS
from fxf.events import pdf
from fxf.events.calendar import Meeting
from fxf.events.text import normalize_space, parse_cba_rates

DATA_DIR: Final = Path(__file__).parent / "data"
SEED_DECISIONS: Final = DATA_DIR / "cba_decisions.csv"
GLYPHS_FILE: Final = DATA_DIR / "cba_calendar_glyphs.json"

YEREVAN: Final = ZoneInfo("Asia/Yerevan")
CBA_BASE: Final = "https://www.cba.am"
RATES_URL: Final = f"{CBA_BASE}/en/statistics/interest-rates-of-the-cba-operations-in-financial-markets/219/export-all/"
RATES_PARAMS: Final = {"extension": "json"}
PRESS_URL: Final = f"{CBA_BASE}/en/press-releases"
DMP_URL: Final = f"{CBA_BASE}/en/decision-making-process/"
ARKA_RSS_URL: Final = "https://arka.am/en/rss/"
INTERFAX_RSS_URL: Final = "https://www.interfax.ru/rss.asp"

SERIES: Final = {"refinancing": "CBA_REFI", "lombard": "CBA_LOMBARD", "deposit": "CBA_DEPOSIT"}
INDICATORS: Final = {
    "refinancing rate (%)": "refinancing",
    "lombard repo (%)": "lombard",
    "deposits (%)": "deposit",
}
# The export's values lag one row before this date (see module docstring).
LAGGED_BEFORE: Final = dt.date(2009, 10, 6)
# The live export is trusted for decisions from this date (it matches every press release).
LIVE_FROM: Final = dt.date(2016, 1, 1)
# Board decisions outside the regular schedule (extraordinary sessions).
UNSCHEDULED: Final = frozenset(
    dt.date.fromisoformat(d)
    for d in ("2009-03-03", "2009-05-22", "2014-11-24", "2014-12-02", "2015-01-21", "2015-03-12")
)
# Default announcement time when the source has none: 16:00 Yerevan on the decision day.
DEFAULT_ANNOUNCE: Final = dt.time(16, 0)


@dataclass(frozen=True)
class RateSet:
    date: dt.date  # decision (date of setting)
    refinancing: float | None
    lombard: float | None
    deposit: float | None

    def as_dict(self) -> dict[str, float | None]:
        return {"refinancing": self.refinancing, "lombard": self.lombard, "deposit": self.deposit}


@dataclass(frozen=True)
class CbaDecision:
    decision_date: dt.date
    effective_date: dt.date
    refinancing: float
    lombard: float | None
    deposit: float | None
    scheduled: bool
    announced_at: dt.datetime
    source_url: str | None

    def rates(self) -> dict[str, float | None]:
        return {"refinancing": self.refinancing, "lombard": self.lombard, "deposit": self.deposit}


def default_announced_at(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, DEFAULT_ANNOUNCE, tzinfo=YEREVAN).astimezone(dt.UTC)


# --- rate history export ----------------------------------------------------------------------


class _ExportRow(BaseModel):
    model_config = {"extra": "allow"}
    Indicators: str


class _Export(RootModel[dict[str, list[_ExportRow]]]):
    pass


def parse_rates_export(payload: Any) -> list[RateSet]:
    """The JSON export: {"<filter label>": [{"Indicators": name, "YYYY-MM-DD": value, ...}]}."""
    export = http.validate(SOURCE_CBA, payload, _Export)
    if len(export.root) != 1:
        raise http.SchemaError(f"{SOURCE_CBA}: expected one table, got {list(export.root)[:5]}")
    (rows,) = export.root.values()
    by_date: dict[dt.date, dict[str, float | None]] = defaultdict(dict)
    found: set[str] = set()
    for row in rows:
        key = INDICATORS.get(row.Indicators.strip().lower())
        if key is None:
            raise http.SchemaError(f"{SOURCE_CBA}: unknown indicator {row.Indicators!r}")
        found.add(key)
        for k, v in (row.model_extra or {}).items():
            try:
                day = dt.date.fromisoformat(k)
            except ValueError as exc:
                raise http.SchemaError(f"{SOURCE_CBA}: unexpected column {k!r}") from exc
            if v is None or v == "":
                continue
            try:
                by_date[day][key] = float(v)
            except (TypeError, ValueError) as exc:
                raise http.SchemaError(f"{SOURCE_CBA}: bad value {v!r} on {k}") from exc
    if found != set(INDICATORS.values()) or not by_date:
        raise http.SchemaError(f"{SOURCE_CBA}: expected refinancing, lombard and deposit rows")
    return [
        RateSet(d, v.get("refinancing"), v.get("lombard"), v.get("deposit"))
        for d, v in sorted(by_date.items())
    ]


def clean_rate_history(rows: list[RateSet], meeting_dates: set[dt.date]) -> list[RateSet]:
    """Apply the corrections listed in the module docstring."""
    rows = sorted(rows, key=lambda r: r.date)
    fixed: list[RateSet] = []
    for i, r in enumerate(rows):
        if r.date < LAGGED_BEFORE and i + 1 < len(rows):
            nxt = rows[i + 1]
            fixed.append(RateSet(r.date, nxt.refinancing, nxt.lombard, nxt.deposit))
        else:
            fixed.append(r)
    dates = {r.date for r in fixed}
    out: dict[dt.date, RateSet] = {}
    for r in fixed:
        if r.date - dt.timedelta(days=1) in dates:
            continue  # the next-day duplicate of a decision row
        day = r.date
        if day not in meeting_dates:
            for delta in (1, -1):
                cand = day + dt.timedelta(days=delta)
                if cand in meeting_dates:
                    day = cand
                    break
        out[day] = RateSet(day, r.refinancing, r.lombard, r.deposit)
    return [out[d] for d in sorted(out)]


def fetch_rates_export() -> list[RateSet]:
    return parse_rates_export(
        http.fetch_json(SOURCE_CBA, RATES_URL, TypeAdapter(Any), params=RATES_PARAMS)
    )


# --- curated decision history -----------------------------------------------------------------


def load_decisions(path: Path = SEED_DECISIONS) -> list[CbaDecision]:
    out = []
    with path.open(newline="") as fh:
        for r in csv.DictReader(fh):
            out.append(
                CbaDecision(
                    decision_date=dt.date.fromisoformat(r["decision_date"]),
                    effective_date=dt.date.fromisoformat(r["effective_date"]),
                    refinancing=float(r["refinancing"]),
                    lombard=float(r["lombard"]) if r["lombard"] else None,
                    deposit=float(r["deposit"]) if r["deposit"] else None,
                    scheduled=r["scheduled"].strip().lower() == "true",
                    announced_at=dt.datetime.fromisoformat(r["announced_at"]),
                    source_url=r["source_url"] or None,
                )
            )
    return sorted(out, key=lambda d: d.decision_date)


def write_decisions(decisions: list[CbaDecision], path: Path = SEED_DECISIONS) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "decision_date",
                "effective_date",
                "refinancing",
                "lombard",
                "deposit",
                "scheduled",
                "announced_at",
                "source_url",
            ]
        )
        for d in sorted(decisions, key=lambda d: d.decision_date):
            w.writerow(
                [
                    d.decision_date.isoformat(),
                    d.effective_date.isoformat(),
                    f"{d.refinancing:g}",
                    "" if d.lombard is None else f"{d.lombard:g}",
                    "" if d.deposit is None else f"{d.deposit:g}",
                    str(d.scheduled).lower(),
                    d.announced_at.astimezone(dt.UTC).isoformat(),
                    d.source_url or "",
                ]
            )


def decision_meetings(decisions: list[CbaDecision]) -> list[Meeting]:
    return [Meeting("CBA", d.decision_date, d.scheduled, d.source_url) for d in decisions]


def macro_rows(decisions: list[CbaDecision], fetched_at: dt.datetime) -> list[dict[str, Any]]:
    """Step series keyed by effective date; published_at = announcement time."""
    rows = []
    for d in decisions:
        for key, series in SERIES.items():
            v = d.rates()[key]
            if v is None:
                continue
            rows.append(
                {
                    "series_id": series,
                    "date": d.effective_date,
                    "value": v,
                    "source": SOURCE_CBA,
                    "published_at": d.announced_at,
                    "fetched_at": fetched_at,
                }
            )
    return rows


def merge_live(
    decisions: list[CbaDecision], live: list[RateSet], *, since: dt.date = LIVE_FROM
) -> list[CbaDecision]:
    """Decisions from the live export (from `since`) merged onto the curated ones.

    A live row on a known decision date updates its rates; a new date becomes a new decision.
    Announcement times of known decisions are kept.
    """
    by_date = {d.decision_date: d for d in decisions}
    for r in live:
        if r.date < since or r.refinancing is None:
            continue
        old = by_date.get(r.date)
        by_date[r.date] = CbaDecision(
            decision_date=r.date,
            effective_date=r.date + dt.timedelta(days=1),
            refinancing=r.refinancing,
            lombard=r.lombard,
            deposit=r.deposit,
            scheduled=old.scheduled if old else r.date not in UNSCHEDULED,
            announced_at=old.announced_at if old else default_announced_at(r.date),
            source_url=old.source_url if old else RATES_URL,
        )
    return [by_date[d] for d in sorted(by_date)]


# --- press releases -----------------------------------------------------------------------------


@dataclass(frozen=True)
class PressItem:
    id: int
    url: str
    title: str
    published_at: dt.datetime  # UTC


@dataclass(frozen=True)
class PressRelease:
    url: str
    date: dt.date
    title: str
    text: str
    pdf_urls: tuple[str, ...]


class _PressList(BaseModel):
    items: list[dict[str, Any]] = Field(min_length=1)


_RATE_TITLE = re.compile(r"(?i)\b(policy|refinancing) rate\b|տոկոսադրույք")


def is_rate_decision(title: str) -> bool:
    return bool(_RATE_TITLE.search(title))


def parse_press_list(html: str, base: str = CBA_BASE) -> list[PressItem]:
    soup = BeautifulSoup(html, "lxml")
    out: list[PressItem] = []
    for a in soup.find_all("a", href=True):
        m = re.search(r"/press-releases/(\d+)/?$", a["href"])
        span = a.find_next_sibling("span")
        if not m or span is None:
            continue
        try:
            local = dt.datetime.strptime(span.get_text(strip=True), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        out.append(
            PressItem(
                id=int(m.group(1)),
                url=urljoin(base, a["href"]),
                title=normalize_space(a.get_text(" ", strip=True)),
                published_at=local.replace(tzinfo=YEREVAN).astimezone(dt.UTC),
            )
        )
    http.validate(SOURCE_CBA_NEWS, {"items": [i.__dict__ for i in out]}, _PressList)
    return out


def parse_press_release(html: str, url: str) -> PressRelease:
    soup = BeautifulSoup(html, "lxml")
    title = soup.select_one("h2.main-content__title")
    date = soup.select_one("span.main-content__date")
    body = soup.select_one("div.static-content")
    if not (title and date and body):
        raise http.SchemaError(f"{SOURCE_CBA_NEWS}: unknown press release layout at {url}")
    try:
        day = dt.date.fromisoformat(date.get_text(strip=True)[:10])
    except ValueError as exc:
        raise http.SchemaError(f"{SOURCE_CBA_NEWS}: bad date {date.get_text()!r}") from exc
    paras = [normalize_space(p.get_text(" ", strip=True)) for p in body.find_all(["p", "li"])]
    text = "\n".join(p for p in paras if p) or normalize_space(body.get_text(" ", strip=True))
    pdfs = tuple(
        urljoin(url, a["href"])
        for a in body.find_all("a", href=True)
        if a["href"].lower().endswith(".pdf")
    )
    return PressRelease(url, day, normalize_space(title.get_text(" ", strip=True)), text, pdfs)


OLD_BASE: Final = "https://old.cba.am"
_OLD_NEWS = re.compile(r"old\.cba\.am/EN/News/Pages/news_(\d{2})(\d{2})(\d{4})(_01)?\.aspx", re.I)
_FOOTER = re.compile(r"_{10,}|In case of using the Press Release")


def is_old_site(url: str) -> bool:
    return bool(_OLD_NEWS.search(url))


def old_emps_url(url: str) -> str:
    """The "(Executive Monetary Policy Statement)" companion page of an old-site release."""
    return (
        url
        if re.search(r"_01\.aspx$", url, re.I)
        else re.sub(r"\.aspx$", "_01.aspx", url, flags=re.I)
    )


_BLOCKS: Final = ("div", "p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td")


def _block_lines(root: Any) -> list[str]:
    """Text of the innermost block elements, in document order (one paragraph per line)."""
    lines = []
    for el in root.find_all(_BLOCKS):
        if el.find(_BLOCKS):
            continue
        text = normalize_space(el.get_text(" ", strip=True)).replace("\u200b", "").strip()
        if text:
            lines.append(text)
    return lines


def parse_old_press(html: str, url: str) -> PressRelease:
    """A release on old.cba.am (SharePoint): title in h3 > span, body in div.ms-WPBody."""
    m = _OLD_NEWS.search(url)
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("div.ms-WPBody")
    title = next((h.select_one("span") for h in soup.select("h3") if h.select_one("span")), None)
    if m is None or body is None or title is None:
        raise http.SchemaError(f"{SOURCE_CBA_NEWS}: unknown old-site layout at {url}")
    day = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    lines: list[str] = []
    for line in _block_lines(body):
        if _FOOTER.search(line):
            break
        lines.append(line)
    pdfs = tuple(
        urljoin(url, a["href"])
        for a in body.find_all("a", href=True)
        if a["href"].lower().endswith(".pdf")
    )
    return PressRelease(
        url, day, normalize_space(title.get_text(" ", strip=True)), "\n".join(lines), pdfs
    )


def parse_release(html: str, url: str) -> PressRelease:
    return parse_old_press(html, url) if is_old_site(url) else parse_press_release(html, url)


def _emps_from_html(text: str) -> str | None:
    """Section A of an EMPS companion page (the page itself is the statement)."""
    i = text.find("Executive Monetary Policy Statement")
    body = text[i + len("Executive Monetary Policy Statement") :] if 0 <= i < 400 else text
    body = body.lstrip(" .:\n")
    for stop in ("Approved by the Board", "B. Summary of Economic Conditions"):
        j = body.find(stop)
        if j > 0:
            body = body[:j]
    body = body.strip(" \n\u200b")
    return body if len(body) > 400 else None


def emps_text(data: bytes) -> str | None:
    """Section A ("Executive Monetary Policy Statement") of an EMPS PDF, or None."""
    lines = pdf.text_lines(data)
    start = next(
        (
            i
            for i, ln in enumerate(lines)
            if re.match(r"A\.\s*Executive Monetary Policy Statement", ln)
        ),
        None,
    )
    if start is None:
        return None
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("Approved by the Board") or re.match(r"B\.\s", line):
            break
        body.append(line)
    if not body:
        return None
    # Re-flow the PDF lines into paragraphs: a line ending a sentence closes a paragraph.
    paras: list[str] = []
    cur = ""
    for line in body:
        if cur.endswith("-") and not cur.endswith(" -"):
            cur = cur[:-1] + line
        else:
            cur = f"{cur} {line}".strip()
        if re.search(r"[.!?]$", line) and len(line) < 110:
            paras.append(cur)
            cur = ""
    if cur:
        paras.append(cur)
    return "\n".join(paras)


def statement_text(release: PressRelease) -> str:
    """The decision statement: the press release, or the Executive Monetary Policy Statement
    (EMPS) when the release is only a short summary (late 2023 onward). The EMPS is an HTML
    companion page on old.cba.am, or a PDF linked from the release."""
    if len(release.text) >= 1200:
        return release.text
    pdf_urls = list(release.pdf_urls)
    if is_old_site(release.url):
        try:
            emps_page = parse_old_press(
                http.fetch_text(SOURCE_CBA_NEWS, old_emps_url(release.url)),
                old_emps_url(release.url),
            )
            text = _emps_from_html(emps_page.text)
            if text:
                return text
            pdf_urls += list(emps_page.pdf_urls)
        except http.SourceError:
            pass
    if pdf_urls:
        for url in pdf_urls:
            try:
                data = http.fetch(SOURCE_CBA_NEWS, url, ext="pdf").content
            except http.SourceError:
                continue
            text = emps_text(data)
            if text:
                return text
    return release.text


def decision_from_release(release: PressRelease) -> dict[str, float]:
    rates = parse_cba_rates(f"{release.title}. {release.text}")
    if "refinancing" not in rates:
        raise http.SchemaError(f"{SOURCE_CBA_NEWS}: no policy rate in {release.url}")
    return rates


# --- calendar ------------------------------------------------------------------------------------


_DATE_RE = re.compile(r"(\d{1,2})\s*([A-Z][a-z]+)\s*(\d{4})")
_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        1,
    )
}


def _dates_in(text: str) -> list[dt.date]:
    out = []
    for d, mon, y in _DATE_RE.findall(text):
        if mon in _MONTHS:
            out.append(dt.date(int(y), _MONTHS[mon], int(d)))
    return out


def load_glyphs(path: Path = GLYPHS_FILE) -> dict[str, str]:
    return json.loads(path.read_text())


def calendar_cells(data: bytes, glyphs: dict[str, str] | None = None) -> list[list[str]]:
    """Table rows of the timetable PDF, decoding image-drawn text through `glyphs`."""
    glyphs = load_glyphs() if glyphs is None else glyphs
    uses = pdf.image_cells(data)
    if not uses:
        return []
    unknown = {u.signature for u in uses} - set(glyphs)
    if unknown:
        raise http.SchemaError(
            f"{SOURCE_CBA_NEWS}: calendar PDF has {len(unknown)} unknown glyph images"
        )
    # Column boundaries: the clip-rectangle x positions used by many cells.
    counts: dict[float, int] = defaultdict(int)
    for u in uses:
        counts[round(u.cell_x, 1)] += 1
    cols = sorted(x for x, c in counts.items() if c >= 5)
    # Rows by the cell's clip rectangle (a wrapped cell spans two text lines), columns by
    # where the image is drawn (a few images are drawn under a neighbouring cell's clip).
    rows: dict[tuple[int, int], dict[int, list[tuple[float, float, float, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for u in uses:
        col = max(0, bisect_right(cols, u.x + 0.01) - 1)
        rows[(u.page, -round(u.cell_y))][col].append(
            (-round(u.y), u.x, u.width, glyphs[u.signature])
        )
    table = []
    for key in sorted(rows):
        cells = []
        for col in sorted(rows[key]):
            text, end = "", None
            for _, x, w, g in sorted(rows[key][col]):
                if end is not None and x - end > 1.5:
                    text += " "
                text += g
                end = x + w
            cells.append(text)
        table.append(cells)
    return table


def parse_calendar_pdf(
    data: bytes, url: str, glyphs: dict[str, str] | None = None
) -> list[Meeting]:
    """Future Board decision dates from the timetable (first date of each row)."""
    meetings: list[Meeting] = []
    for line in pdf.text_lines(data):
        ds = _dates_in(line)
        if len(ds) >= 2:
            meetings.append(Meeting("CBA", ds[0], True, url))
    if not meetings:
        for cells in calendar_cells(data, glyphs):
            ds = [d for c in cells for d in _dates_in(c)]
            if len(ds) >= 2 and re.fullmatch(r"\d{4}-\d", cells[0].strip()):
                meetings.append(Meeting("CBA", ds[0], True, url))
    if not meetings:
        raise http.SchemaError(f"{SOURCE_CBA_NEWS}: no decision dates in calendar PDF {url}")
    return sorted(set(meetings), key=lambda m: m.date)


def find_calendar_url(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        if re.search(r"(?i)calendar.*\.pdf$", a["href"]):
            return urljoin(CBA_BASE, a["href"])
    raise http.SchemaError(f"{SOURCE_CBA_NEWS}: no calendar PDF link on {DMP_URL}")


def fetch_calendar() -> list[Meeting]:
    url = find_calendar_url(http.fetch_text(SOURCE_CBA_NEWS, DMP_URL))
    return parse_calendar_pdf(http.fetch(SOURCE_CBA_NEWS, url, ext="pdf").content, url)


# --- news fallback (ARKA, Interfax) ----------------------------------------------------------------


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    summary: str
    published_at: dt.datetime


class _Feed(BaseModel):
    items: list[dict[str, Any]] = Field(min_length=1)


def parse_news_feed(source_name: str, text: str) -> list[NewsItem]:
    feed = feedparser.parse(text)
    items = []
    for e in feed.entries:
        if not getattr(e, "title", None) or not getattr(e, "link", None):
            continue
        tm = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
        if tm is None:
            continue
        items.append(
            NewsItem(
                title=normalize_space(e.title),
                link=e.link,
                summary=normalize_space(
                    BeautifulSoup(getattr(e, "summary", "") or "", "lxml").get_text(" ")
                ),
                published_at=dt.datetime(*tm[:6], tzinfo=dt.UTC),
            )
        )
    http.validate(f"{SOURCE_CBA_NEWS}:{source_name}", {"items": [i.__dict__ for i in items]}, _Feed)
    return items


_EN_CBA = re.compile(
    r"(?i)(central bank of armenia|\bcba\b|armenia'?s? central bank|armenian central bank)"
)
_EN_RATE = re.compile(r"(?i)(refinancing|policy|key) rate")
_RU_CBA = re.compile(r"(?i)(ЦБ|Центробанк|Центральный банк) Армении")
_RU_RATE = re.compile(r"(?i)ставк")
_RU_VALUE = re.compile(r"(?:до|на уровне|составила|-)\s*(\d+(?:[.,]\d+)?)\s?%")


def news_decision(item: NewsItem) -> dict[str, float] | None:
    """Rates from a news item about a CBA decision, or None if the item is unrelated."""
    text = f"{item.title}. {item.summary}"
    if _EN_CBA.search(text) and _EN_RATE.search(text):
        rates = parse_cba_rates(text)
        return rates if "refinancing" in rates else None
    if _RU_CBA.search(text) and _RU_RATE.search(text):
        m = _RU_VALUE.search(text)
        return {"refinancing": float(m.group(1).replace(",", "."))} if m else None
    return None

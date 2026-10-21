"""ECB: Governing Council monetary policy decisions.

Live (FR-05): the hourly poll reads the ECB press RSS (https://www.ecb.europa.eu/rss/press.html,
linked from ecb.europa.eu/home/html/rss.en.html), picks "Monetary policy decisions" items,
fetches the press release and parses the deposit facility, MRO and marginal lending rates.

History: decisions are derived from the ECB Data Portal daily FM series DFR, MRR_FR and
MLFR. These record the effective date (about a week after the decision), so rate_before is
the value on the decision date and rate_after the value 14 days later (before any next
meeting: Governing Council monetary meetings are at least four weeks apart).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass
from typing import Final
from zoneinfo import ZoneInfo

import pandas as pd
from bs4 import BeautifulSoup

from fxf import http
from fxf.constants import SOURCE_ECB_RSS
from fxf.events.calendar import Meeting
from fxf.events.decisions import Decision
from fxf.events.fed import RssItem, asof, parse_rss
from fxf.events.text import normalize_space

FRANKFURT: Final = ZoneInfo("Europe/Berlin")
RSS_URL: Final = "https://www.ecb.europa.eu/rss/press.html"
FM_URL: Final = "https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.{key}.LEV"
FM_KEYS: Final = {"deposit": "DFR", "mro": "MRR_FR", "mlf": "MLFR"}
EFFECTIVE_LAG: Final = dt.timedelta(days=14)
# Decision press releases go out at 14:15 CET (13:45 before 2022); history uses the later time.
DEFAULT_RELEASE: Final = dt.time(14, 15)


def is_decision(title: str) -> bool:
    return normalize_space(title).lower() == "monetary policy decisions"


def parse_feed(text: str) -> list[RssItem]:
    return parse_rss(SOURCE_ECB_RSS, text)


def item_day(item: RssItem) -> dt.date:
    return item.published_at.astimezone(FRANKFURT).date()


@dataclass(frozen=True)
class EcbStatement:
    url: str
    date: dt.date
    text: str


_SKIP = re.compile(r"^(For media queries|Media contacts|Reproduction is permitted)", re.I)


def parse_decision_page(html: str, url: str) -> EcbStatement:
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main")
    section = main.select_one("div.section") if main else None
    title = main.select_one("div.title") if main else None
    if (
        section is None
        or title is None
        or "monetary policy decisions" not in title.get_text(" ").lower()
    ):
        raise http.SchemaError(f"{SOURCE_ECB_RSS}: unknown decision page layout at {url}")
    paras: list[str] = []
    day: dt.date | None = None
    for el in section.find_all(["p", "h2", "h3", "li"]):
        text = normalize_space(el.get_text(" ", strip=True))
        if not text or text == "***":
            continue
        if _SKIP.match(text):
            break
        if day is None:
            try:
                day = dt.datetime.strptime(text, "%d %B %Y").date()
                continue
            except ValueError:
                pass
        if el.name in ("h2", "h3"):
            continue
        paras.append(text)
    if day is None:
        pub = main.select_one(".ecb-pressContentPubDate")
        try:
            day = (
                dt.datetime.strptime(normalize_space(pub.get_text(" ")), "%d %B %Y").date()
                if pub
                else None
            )
        except ValueError:
            day = None
    if day is None:
        m = re.search(r"[./](?:mp|pr)(\d{6})", url)
        if m:
            day = dt.datetime.strptime(m.group(1), "%y%m%d").date()
    if day is None or not paras:
        raise http.SchemaError(f"{SOURCE_ECB_RSS}: no date or text in {url}")
    return EcbStatement(url, day, "\n".join(paras))


def fetch_decision_page(url: str) -> EcbStatement:
    return parse_decision_page(http.fetch_text(SOURCE_ECB_RSS, url), url)


def release_time(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, DEFAULT_RELEASE, tzinfo=FRANKFURT).astimezone(dt.UTC)


# --- FM series ----------------------------------------------------------------------------------


def parse_fm_csv(key: str, text: str) -> pd.Series:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not {"TIME_PERIOD", "OBS_VALUE"} <= set(reader.fieldnames):
        raise http.SchemaError(
            f"{SOURCE_ECB_RSS}: FM {key}: unexpected columns {reader.fieldnames!r:.200}"
        )
    idx, vals = [], []
    for row in reader:
        if row.get("OBS_VALUE") in (None, ""):
            continue
        idx.append(pd.Timestamp(row["TIME_PERIOD"]))
        vals.append(float(row["OBS_VALUE"]))
    if not vals:
        raise http.SchemaError(f"{SOURCE_ECB_RSS}: FM {key}: no observations")
    return pd.Series(vals, index=pd.DatetimeIndex(idx), dtype="float64").sort_index()


def fetch_fm(name: str, start: dt.date | None = None) -> pd.Series:
    key = FM_KEYS[name]
    params = {"format": "csvdata", "detail": "dataonly"}
    if start:
        params["startPeriod"] = start.isoformat()
    text = http.fetch_text(SOURCE_ECB_RSS, FM_URL.format(key=key), params=params, ext="csv")
    return parse_fm_csv(key, text)


def history_decisions(
    meetings: list[Meeting], series: dict[str, pd.Series], today: dt.date
) -> list[Decision]:
    out: list[Decision] = []
    dfr = series.get("deposit")
    if dfr is None or dfr.empty:
        return out
    for m in sorted(meetings, key=lambda m: m.date):
        if m.bank != "ECB" or m.date > today or m.date <= dfr.index.min().date():
            continue
        later = m.date + EFFECTIVE_LAG
        if later > dfr.index.max().date():
            continue  # not yet effective in the series; the live RSS reader records it
        before = {k: asof(s, m.date) for k, s in series.items() if not s.empty}
        after = {k: asof(s, later) for k, s in series.items() if not s.empty}
        if before.get("deposit") is None or after.get("deposit") is None:
            continue
        if not m.scheduled and before == after:
            continue
        out.append(
            Decision(
                "ECB",
                m.date,
                before=before,
                after=after,
                source="ecb_data_portal",
                published_at=release_time(m.date),
            )
        )
    return out

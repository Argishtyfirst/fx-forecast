"""Build the frozen real-data set for the backtest regression test (tests/fixtures/frozen/).

    uv run python scripts/make_frozen_dataset.py            # 2019-01-01 .. 2024-12-31

Sources (all free, no key):
- Rates: Frankfurter v2, ECB provider (EUR/USD) and CBA provider (USD/AMD, USD/RUB, and
  EUR/AMD, the CBA's own EUR rate; RUB/AMD = USD/AMD / USD/RUB on the same date).
- Macro: FRED fredgraph.csv (DFEDTARU, DFEDTARL, DGS2, DCOILBRENTEU, DTWEXBGS) and the ECB
  Data Portal (deposit facility rate FM.D.U2.EUR.4F.KR.DFR.LEV -> ECB_DFR).
- Meetings: hand-checked FOMC decision days (federalreserve.gov FOMC calendars) and ECB
  monetary policy meeting days (ecb.europa.eu monetary policy statements), 2019 to Q1 2025.

published_at follows the ingest publication-lag rules (fxf.ingest.pit), copied here so the
frozen files never change when ingest code does:
DFEDTARU/DFEDTARL/ECB_DFR obs date 00:00 UTC; DGS2 next US business day 22:00;
DTWEXBGS and DCOILBRENTEU obs + 7 days 22:00.

The CBA refinancing rate and CBA meetings are not part of the frozen set, so the USD/AMD and
EUR/AMD forward models are skipped there (the regression test also covers that path).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import time
from pathlib import Path

import httpx

from fxf.calendars import CALENDAR_US, add_trading_days

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "frozen"
FRANKFURTER = "https://api.frankfurter.dev/v2/rates"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv"
ECB = "https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV"
FRED_SERIES = ("DFEDTARU", "DFEDTARL", "DGS2", "DCOILBRENTEU", "DTWEXBGS")

# FOMC decision days (second day of each meeting). Source: federalreserve.gov/monetarypolicy
# fomccalendars.htm and fomchistorical2019/2020.htm. 2020-03-03 and 2020-03-15 were
# unscheduled; the 2020-03-17/18 meeting was cancelled and is left out.
FOMC = {
    2019: ["01-30", "03-20", "05-01", "06-19", "07-31", "09-18", "10-30", "12-11"],
    2020: ["01-29", "04-29", "06-10", "07-29", "09-16", "11-05", "12-16"],
    2021: ["01-27", "03-17", "04-28", "06-16", "07-28", "09-22", "11-03", "12-15"],
    2022: ["01-26", "03-16", "05-04", "06-15", "07-27", "09-21", "11-02", "12-14"],
    2023: ["02-01", "03-22", "05-03", "06-14", "07-26", "09-20", "11-01", "12-13"],
    2024: ["01-31", "03-20", "05-01", "06-12", "07-31", "09-18", "11-07", "12-18"],
    2025: ["01-29", "03-19"],
}
FOMC_UNSCHEDULED = ["2020-03-03", "2020-03-15"]
# ECB Governing Council monetary policy meetings. Source: ecb.europa.eu monetary policy
# statements per year (the 2021-07-08 strategy review statement is not a policy meeting).
ECB_MEETINGS = {
    2019: ["01-24", "03-07", "04-10", "06-06", "07-25", "09-12", "10-24", "12-12"],
    2020: ["01-23", "03-12", "04-30", "06-04", "07-16", "09-10", "10-29", "12-10"],
    2021: ["01-21", "03-11", "04-22", "06-10", "07-22", "09-09", "10-28", "12-16"],
    2022: ["02-03", "03-10", "04-14", "06-09", "07-21", "09-08", "10-27", "12-15"],
    2023: ["02-02", "03-16", "05-04", "06-15", "07-27", "09-14", "10-26", "12-14"],
    2024: ["01-25", "03-07", "04-11", "06-06", "07-18", "09-12", "10-17", "12-12"],
    2025: ["01-30", "03-06"],
}


def get(client: httpx.Client, url: str, params: dict[str, str]) -> httpx.Response:
    for attempt in range(4):
        try:
            r = client.get(url, params=params)
            r.raise_for_status()
            if r.content:
                return r
        except httpx.HTTPError:
            if attempt == 3:
                raise
        time.sleep(2**attempt)
    raise RuntimeError(f"empty response from {url}")


def at(d: dt.date, hour: int) -> str:
    return dt.datetime.combine(d, dt.time(hour), tzinfo=dt.UTC).isoformat()


def published_at(series: str, d: dt.date) -> str:
    if series in ("DFEDTARU", "DFEDTARL", "ECB_DFR"):
        return at(d, 0)
    if series == "DGS2":
        return at(add_trading_days(CALENDAR_US, d, 1), 22)
    return at(d + dt.timedelta(days=7), 22)  # DTWEXBGS, DCOILBRENTEU


def fetch_rates(client: httpx.Client, start: dt.date, end: dt.date) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    common = {"from": start.isoformat(), "to": end.isoformat()}
    eur = get(
        client, FRANKFURTER, {"base": "EUR", "quotes": "USD", "providers": "ECB", **common}
    ).json()
    for r in eur:
        if start.isoformat() <= r["date"] <= end.isoformat():
            rows.append(
                {
                    "pair": "EURUSD",
                    "date": r["date"],
                    "rate": str(r["rate"]),
                    "source": "frankfurter_ecb",
                }
            )
    usd = get(
        client, FRANKFURTER, {"base": "USD", "quotes": "AMD,RUB", "providers": "CBA", **common}
    ).json()
    by_date: dict[str, dict[str, float]] = {}
    for r in usd:
        if start.isoformat() <= r["date"] <= end.isoformat():
            by_date.setdefault(r["date"], {})[r["quote"]] = float(r["rate"])
    for d in sorted(by_date):
        q = by_date[d]
        if "AMD" in q:
            rows.append(
                {"pair": "USDAMD", "date": d, "rate": repr(q["AMD"]), "source": "frankfurter_cba"}
            )
            if q.get("RUB"):
                rows.append(
                    {
                        "pair": "RUBAMD",
                        "date": d,
                        "rate": f"{q['AMD'] / q['RUB']:.8f}",
                        "source": "frankfurter_cba",
                    }
                )
    eur_amd = get(
        client, FRANKFURTER, {"base": "EUR", "quotes": "AMD", "providers": "CBA", **common}
    ).json()
    for r in eur_amd:
        if start.isoformat() <= r["date"] <= end.isoformat():
            rows.append(
                {
                    "pair": "EURAMD",
                    "date": r["date"],
                    "rate": str(r["rate"]),
                    "source": "frankfurter_cba",
                }
            )
    return rows


def fetch_macro(client: httpx.Client, start: dt.date, end: dt.date) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for sid in FRED_SERIES:
        text = get(
            client, FRED, {"id": sid, "cosd": start.isoformat(), "coed": end.isoformat()}
        ).text
        for r in csv.DictReader(io.StringIO(text)):
            v = (r.get(sid) or "").strip()
            if v in ("", "."):
                continue
            d = dt.date.fromisoformat(r["observation_date"])
            rows.append(
                {
                    "series_id": sid,
                    "date": d.isoformat(),
                    "value": v,
                    "source": "fred",
                    "published_at": published_at(sid, d),
                }
            )
    text = get(
        client,
        ECB,
        {"format": "csvdata", "startPeriod": start.isoformat(), "endPeriod": end.isoformat()},
    ).text
    for r in csv.DictReader(io.StringIO(text)):
        d = dt.date.fromisoformat(r["TIME_PERIOD"])
        rows.append(
            {
                "series_id": "ECB_DFR",
                "date": d.isoformat(),
                "value": r["OBS_VALUE"],
                "source": "ecb_data_portal",
                "published_at": published_at("ECB_DFR", d),
            }
        )
    return rows


def meetings() -> list[dict[str, str]]:
    rows = [
        {
            "bank": "FED",
            "date": f"{y}-{md}",
            "scheduled": "true",
            "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        }
        for y, mds in FOMC.items()
        for md in mds
    ]
    rows += [
        {
            "bank": "FED",
            "date": d,
            "scheduled": "false",
            "source_url": "https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm",
        }
        for d in FOMC_UNSCHEDULED
    ]
    rows += [
        {
            "bank": "ECB",
            "date": f"{y}-{md}",
            "scheduled": "true",
            "source_url": "https://www.ecb.europa.eu/press/press_conference/monetary-policy-statement/html/index.en.html",
        }
        for y, mds in ECB_MEETINGS.items()
        for md in mds
    ]
    return sorted(rows, key=lambda r: (r["date"], r["bank"]))


def write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2019, 1, 1))
    ap.add_argument("--end", type=dt.date.fromisoformat, default=dt.date(2024, 12, 31))
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    macro_start = args.start - dt.timedelta(days=60)
    with httpx.Client(
        timeout=60, follow_redirects=True, headers={"User-Agent": "fxf/0.1 frozen dataset"}
    ) as c:
        rates = fetch_rates(c, args.start, args.end)
        macro = fetch_macro(c, macro_start, args.end)
    meet = meetings()
    write(args.out / "rates.csv", rates)
    write(args.out / "macro.csv", macro)
    write(args.out / "meetings.csv", meet)
    meta = {
        "window": [args.start.isoformat(), args.end.isoformat()],
        "macro_from": macro_start.isoformat(),
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "counts": {
            "rates": {
                p: sum(r["pair"] == p for r in rates)
                for p in ("EURUSD", "USDAMD", "EURAMD", "RUBAMD")
            },
            "macro": {
                s: sum(r["series_id"] == s for r in macro) for s in (*FRED_SERIES, "ECB_DFR")
            },
            "meetings": {b: sum(r["bank"] == b for r in meet) for b in ("FED", "ECB")},
        },
        "sources": [FRANKFURTER, FRED, ECB],
    }
    (args.out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta["counts"]))


if __name__ == "__main__":
    main()

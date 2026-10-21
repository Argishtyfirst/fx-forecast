"""Test datasets for the forecast and backtest tests.

- seed_synthetic: a deterministic synthetic market (rates, macro, meetings, decisions) with
  larger moves on meeting impact days, for the acceptance and leakage tests.
- load_frozen: the frozen real-data set in tests/fixtures/frozen/ (built by
  scripts/make_frozen_dataset.py), for the backtest regression test.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from fxf.calendars import CALENDAR_AM, CALENDAR_TARGET2, CALENDAR_US, is_trading_day
from fxf.constants import BANK_POLICY_RATE, RUBAMD
from fxf.models import CbEvent, CbMeeting, MacroSeries, Rate, upsert

FROZEN_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "frozen"
UTC = dt.UTC
FETCHED = dt.datetime(2026, 10, 21, 12, 0, tzinfo=UTC)

# Meeting anchors around the default run date 2026-10-21 (a Wednesday); meetings repeat every
# 6 weeks, so the weekday is kept. ECB on 2026-10-29 matches the spec's example response.
ANCHORS = {"FED": dt.date(2026, 10, 28), "ECB": dt.date(2026, 10, 29), "CBA": dt.date(2026, 10, 27)}
UNSCHEDULED = [("FED", dt.date(2020, 3, 15))]


def _days(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(days=k) for k in range((end - start).days + 1)]


def trading_dates(calendar: str, start: dt.date, end: dt.date) -> list[dt.date]:
    return [d for d in _days(start, end) if is_trading_day(calendar, d)]


def synthetic_meetings(start: dt.date, end: dt.date) -> list[tuple[str, dt.date, bool]]:
    out: list[tuple[str, dt.date, bool]] = []
    for bank, anchor in ANCHORS.items():
        d = anchor
        while d - dt.timedelta(days=42) >= start:
            d -= dt.timedelta(days=42)
        while d <= end:
            out.append((bank, d, True))
            d += dt.timedelta(days=42)
    out += [(b, d, False) for b, d in UNSCHEDULED if start <= d <= end]
    return sorted(out, key=lambda m: (m[1], m[0]))


def _simulate(
    dates: list[dt.date], s0: float, vol: float, impact: set[dt.date], mult: float, rng
) -> np.ndarray:
    """GARCH(1,1)-like returns with Student-t(6) shocks; impact days get mult x the shock."""
    n = len(dates)
    omega, alpha, beta = vol**2 * 0.05, 0.06, 0.89
    s2 = vol**2
    out = np.empty(n)
    lr = np.log(s0)
    eps_prev = 0.0
    for k, d in enumerate(dates):
        if k:
            s2 = omega + alpha * eps_prev**2 + beta * s2
            z = rng.standard_t(6) / np.sqrt(1.5)
            eps_prev = np.sqrt(s2) * z
            lr += eps_prev * (mult if d in impact else 1.0)
        out[k] = np.exp(lr)
    return out


def _policy_path(
    meetings: list[dt.date], days: list[dt.date], start_rate: float, lo: float, hi: float, rng
) -> tuple[dict[dt.date, float], list[tuple[dt.date, float, float]]]:
    """Daily policy rate changing by -25/0/+25 bp the day after some meetings."""
    rate = start_rate
    changes: dict[dt.date, float] = {}
    decisions: list[tuple[dt.date, float, float]] = []
    for m in meetings:
        step = float(rng.choice([-0.25, 0.0, 0.0, 0.25]))
        new = min(hi, max(lo, rate + step))
        decisions.append((m, rate, new))
        changes[m + dt.timedelta(days=1)] = new
        rate = new
    path: dict[dt.date, float] = {}
    cur = start_rate
    for d in days:
        cur = changes.get(d, cur)
        path[d] = cur
    return path, decisions


def seed_synthetic(
    session: Session,
    *,
    start: dt.date = dt.date(2019, 1, 1),
    end: dt.date = dt.date(2026, 10, 21),
    seed: int = 11,
    with_macro: bool = True,
    with_meetings: bool = True,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    meetings = synthetic_meetings(start, end + dt.timedelta(days=200))
    past = [m for m in meetings if m[1] <= end]
    eur_dates = trading_dates(CALENDAR_TARGET2, start, end)
    amd_dates = trading_dates(CALENDAR_AM, start, end)

    def impact_days(dates: list[dt.date], banks: tuple[str, ...]) -> set[dt.date]:
        arr = np.array(dates, dtype="datetime64[D]")
        out = set()
        for b, d, sched in past:
            if b in banks and sched:
                pos = int(np.searchsorted(arr, np.datetime64(d), side="right"))
                if pos < len(dates):
                    out.add(dates[pos])
        return out

    eur = _simulate(eur_dates, 1.13, 0.0045, impact_days(eur_dates, ("FED", "ECB")), 2.5, rng)
    amd = _simulate(amd_dates, 485.0, 0.0030, impact_days(amd_dates, ("FED", "CBA")), 2.5, rng)
    rub = _simulate(amd_dates, 7.5, 0.0080, set(), 1.0, rng)
    # EUR/AMD (the CBA's own EUR rate, Armenian calendar) from its own stream, so adding it
    # leaves the other series unchanged.
    eur_amd_impact = impact_days(amd_dates, ("FED", "ECB", "CBA"))
    eur_amd = _simulate(
        amd_dates, 545.0, 0.0040, eur_amd_impact, 2.5, np.random.default_rng(seed + 1)
    )
    series = [
        ("EURUSD", eur_dates, eur, 6, "frankfurter_ecb"),
        ("USDAMD", amd_dates, amd, 4, "frankfurter_cba"),
        ("EURAMD", amd_dates, eur_amd, 4, "frankfurter_cba"),
        (RUBAMD, amd_dates, rub, 6, "frankfurter_cba"),
    ]
    rate_rows = [
        {
            "pair": pair,
            "date": d,
            "rate": round(float(v), digits),
            "source": source,
            "fetched_at": FETCHED,
        }
        for pair, dates, values, digits, source in series
        for d, v in zip(dates, values, strict=True)
    ]
    upsert(session, Rate, rate_rows, ["pair", "date"])

    info: dict[str, Any] = {"meetings": meetings, "end": end}
    if with_meetings:
        upsert(
            session,
            CbMeeting,
            [
                {"bank": b, "date": d, "scheduled": s, "source_url": None, "fetched_at": FETCHED}
                for b, d, s in meetings
            ],
            ["bank", "date"],
        )

    if with_macro:
        cal_days = _days(start - dt.timedelta(days=30), end)
        bank_meetings = {b: [d for bb, d, _ in past if bb == b] for b in ANCHORS}
        fed, fed_dec = _policy_path(bank_meetings["FED"], cal_days, 2.375, 0.125, 5.375, rng)
        ecb, ecb_dec = _policy_path(bank_meetings["ECB"], cal_days, -0.40, -0.50, 4.0, rng)
        cba, cba_dec = _policy_path(bank_meetings["CBA"], cal_days, 5.75, 4.0, 11.0, rng)
        macro_rows: list[dict[str, Any]] = []

        def add(series: str, d: dt.date, v: float, pub: dt.datetime, source: str) -> None:
            macro_rows.append(
                {
                    "series_id": series,
                    "date": d,
                    "value": round(float(v), 6),
                    "source": source,
                    "published_at": pub,
                    "fetched_at": FETCHED,
                }
            )

        for d in cal_days:
            pub = dt.datetime.combine(d, dt.time(0, 0), tzinfo=UTC)
            add("DFEDTARU", d, fed[d] + 0.125, pub, "fred")
            add("DFEDTARL", d, fed[d] - 0.125, pub, "fred")
            add("ECB_DFR", d, ecb[d], pub, "ecb_data_portal")
            add("CBA_REFI", d, cba[d], pub, "cba_rates")
        us_days = [d for d in cal_days if is_trading_day(CALENDAR_US, d)]
        dgs2 = 2.5 + np.cumsum(rng.normal(0, 0.04, len(us_days)))
        usd = 115 * np.exp(np.cumsum(rng.normal(0, 0.003, len(us_days))))
        brent = 65 * np.exp(np.cumsum(rng.normal(0, 0.02, len(us_days))))
        for d, a, b, c in zip(us_days, dgs2, usd, brent, strict=True):
            nxt = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(21, 0), tzinfo=UTC)
            add("DGS2", d, a, nxt, "fred")
            add("DTWEXBGS", d, b, nxt + dt.timedelta(days=6), "fred")
            add("DCOILBRENTEU", d, c, nxt + dt.timedelta(days=4), "fred")
        upsert(session, MacroSeries, macro_rows, ["series_id", "date"])

        ev_rows = []
        for bank, decs in (("FED", fed_dec), ("ECB", ecb_dec), ("CBA", cba_dec)):
            for d, before, after in decs:
                if d >= end:
                    continue
                expected = before
                ev_rows.append(
                    {
                        "bank": bank,
                        "date": d,
                        "rate_type": BANK_POLICY_RATE[bank],
                        "rate_before": before,
                        "rate_after": after,
                        "expected": expected,
                        "expected_source": "no_change",
                        "surprise_bps": round((after - expected) * 100.0, 4),
                        "hawkish_score": round(float(np.clip(rng.normal(0, 0.4), -1, 1)), 3),
                        "scorer_version": "synthetic@v1",
                        "source": "synthetic",
                        "published_at": dt.datetime.combine(d, dt.time(18, 0), tzinfo=UTC),
                    }
                )
        upsert(session, CbEvent, ev_rows, ["bank", "date"])
        info["decisions"] = {"FED": fed_dec, "ECB": ecb_dec, "CBA": cba_dec}
    session.commit()
    return info


# --- frozen real-data set --------------------------------------------------------------------


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def load_frozen(session: Session, root: Path = FROZEN_DIR) -> dict[str, int]:
    """Load rates.csv, macro.csv and meetings.csv into the database."""
    rates = [
        {
            "pair": r["pair"],
            "date": dt.date.fromisoformat(r["date"]),
            "rate": float(r["rate"]),
            "source": r["source"],
            "fetched_at": FETCHED,
        }
        for r in _read_csv(root / "rates.csv")
    ]
    macro = [
        {
            "series_id": r["series_id"],
            "date": dt.date.fromisoformat(r["date"]),
            "value": float(r["value"]),
            "source": r["source"],
            "published_at": dt.datetime.fromisoformat(r["published_at"]),
            "fetched_at": FETCHED,
        }
        for r in _read_csv(root / "macro.csv")
    ]
    meetings = [
        {
            "bank": r["bank"],
            "date": dt.date.fromisoformat(r["date"]),
            "scheduled": r["scheduled"].lower() == "true",
            "source_url": r.get("source_url") or None,
            "fetched_at": FETCHED,
        }
        for r in _read_csv(root / "meetings.csv")
    ]
    upsert(session, Rate, rates, ["pair", "date"])
    upsert(session, MacroSeries, macro, ["series_id", "date"])
    upsert(session, CbMeeting, meetings, ["bank", "date"])
    session.commit()
    return {"rates": len(rates), "macro": len(macro), "meetings": len(meetings)}

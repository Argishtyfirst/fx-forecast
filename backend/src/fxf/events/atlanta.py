"""Atlanta Fed Market Probability Tracker -> ATLFED_EXP_NEXT (expected Fed midpoint after
the next FOMC meeting), the Fed's "expected" value for surprises.

Data: mpt_histdata.xlsx linked from atlantafed.org/research-and-data/data/market-probability-tracker
(sheet DATA: date, reference_start, target_range, field, value). The tracker uses CME 3-month
SOFR options; "Rate: mean" is the market-implied mean of the average SOFR (bps) over each
3-month reference window starting at an IMM date. Coverage starts 2023-03-29, so FOMC
meetings from 2023-05-03 get a market expectation; earlier ones use the previous rate.

Per-meeting expectation: windows are quarterly while meetings are eight a year, so on each
observation date t we fit a path that is flat between scheduled FOMC meetings and steps only
at meetings, starting at today's level L0 = midpoint(t) + basis(t), where basis = SOFR - target
midpoint on the last SOFR fixing before t (NY Fed). The levels after each meeting solve
min sum_w (path average over window w - mean_w)^2 + lambda^2 sum_j (L_j - L_{j-1})^2.
ATLFED_EXP_NEXT(t) = L_1 - basis(t) (back in target-midpoint terms, percent). Results barely
move for lambda in [0.005, 0.3]; lambda = 0.05.

Limitation: the tracker lists windows from the second IMM date on (the front quarter's options
are excluded), so when two meetings fall before the first window only their combined move is
identified and the smoothness term splits it. On the 2023-05 .. 2026-09 meetings the resulting
surprises stay within about +-15 bp (mean absolute ~6 bp), e.g. -12 bp for the 50 bp cut of
2024-09-18, which markets had priced at roughly 35-40 bp.

published_at: the tracker posts each day's estimate the next morning; we use observation
date + 1 day at 13:00 UTC.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Final

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, TypeAdapter

from fxf import http
from fxf.constants import ATLFED_SERIES, SOURCE_ATLFED
from fxf.events.xlsx import XlsxError, iter_rows

MPT_URL: Final = (
    "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/research-and-data/data/"
    "market-probability-tracker/mpt_histdata.xlsx"
)
SOFR_URL: Final = "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json"
HEADER: Final = ["date", "reference_start", "target_range", "field", "value"]
LAMBDA: Final = 0.05
PUBLISH_DELAY: Final = dt.timedelta(days=1, hours=13)
EXCEL_EPOCH: Final = dt.date(1899, 12, 30)


def _ref_date(raw: str) -> dt.date:
    try:
        return EXCEL_EPOCH + dt.timedelta(days=int(float(raw)))
    except ValueError:
        return dt.date.fromisoformat(raw[:10])


def parse_mpt(data: bytes) -> pd.DataFrame:
    """Rows of "Rate: mean": date, ref_start, mid (target midpoint, %), mean (%)."""
    try:
        rows = iter_rows(data, "DATA")
        header = [(c or "").strip().lower() for c in next(rows)]
    except (XlsxError, StopIteration, KeyError) as exc:
        raise http.SchemaError(f"{SOURCE_ATLFED}: unreadable tracker workbook: {exc}") from exc
    if header[:5] != HEADER:
        raise http.SchemaError(f"{SOURCE_ATLFED}: unexpected DATA header {header[:6]!r}")
    out = []
    for r in rows:
        if len(r) < 5 or r[3] != "Rate: mean" or not r[0] or not r[4]:
            continue
        m = re.match(r"\s*(\d+)\s*bps\s*-\s*(\d+)\s*bps", r[2] or "")
        if not m:
            raise http.SchemaError(f"{SOURCE_ATLFED}: unexpected target_range {r[2]!r}")
        try:
            out.append(
                (
                    dt.date.fromisoformat(r[0][:10]),
                    _ref_date(r[1] or ""),
                    (int(m.group(1)) + int(m.group(2))) / 200.0,
                    float(r[4]) / 100.0,
                )
            )
        except ValueError as exc:
            raise http.SchemaError(f"{SOURCE_ATLFED}: bad row {r[:5]!r}") from exc
    if not out:
        raise http.SchemaError(f"{SOURCE_ATLFED}: no 'Rate: mean' rows")
    return pd.DataFrame(out, columns=["date", "ref_start", "mid", "mean"])


class _SofrRate(BaseModel):
    effectiveDate: dt.date
    percentRate: float


class _SofrResponse(BaseModel):
    refRates: list[_SofrRate] = Field(min_length=1)


def parse_sofr(payload: object) -> pd.Series:
    resp = http.validate(SOURCE_ATLFED, payload, _SofrResponse)
    s = pd.Series(
        {pd.Timestamp(r.effectiveDate): r.percentRate for r in resp.refRates}, dtype="float64"
    )
    return s.sort_index()


def fetch_sofr(start: dt.date, end: dt.date) -> pd.Series:
    params = {"startDate": start.isoformat(), "endDate": end.isoformat()}
    return parse_sofr(http.fetch_json(SOURCE_ATLFED, SOFR_URL, TypeAdapter(Any), params=params))


def fetch_mpt() -> pd.DataFrame:
    return parse_mpt(http.fetch(SOURCE_ATLFED, MPT_URL, ext="xlsx").content)


def expected_after_next(
    windows: pd.DataFrame, mid: float, basis: float, obs: dt.date, meetings: list[dt.date]
) -> float | None:
    """Expected target midpoint (%) after the first scheduled meeting after `obs`."""
    w = windows.sort_values("ref_start")
    starts = [pd.Timestamp(d) for d in w["ref_start"]]
    means = list(w["mean"].astype(float))
    if not starts:
        return None
    ends = starts[1:] + [starts[-1] + pd.Timedelta(days=91)]
    t0 = pd.Timestamp(obs)
    ms = [
        pd.Timestamp(m)
        for m in sorted(meetings)
        if pd.Timestamp(m) > t0 and pd.Timestamp(m) < ends[-1]
    ]
    if not ms:
        return None
    k = len(ms)
    bounds = [t0, *ms, ends[-1]]
    level0 = mid + basis
    a_rows, y = [], []
    for s, e, mean in zip(starts, ends, means, strict=True):
        length = (e - s).days
        row = np.zeros(k)
        rhs = mean
        for j in range(k + 1):
            lo, hi = max(s, bounds[j]), min(e, bounds[j + 1])
            ov = max(0, (hi - lo).days) / length
            if j == 0:
                rhs -= level0 * ov
            else:
                row[j - 1] += ov
        a_rows.append(row)
        y.append(rhs)
    for j in range(k):
        row = np.zeros(k)
        row[j] = LAMBDA
        if j:
            row[j - 1] = -LAMBDA
            y.append(0.0)
        else:
            y.append(LAMBDA * level0)
        a_rows.append(row)
    sol, *_ = np.linalg.lstsq(np.array(a_rows), np.array(y), rcond=None)
    return float(sol[0] - basis)


def expected_series(mpt: pd.DataFrame, sofr: pd.Series, meetings: list[dt.date]) -> pd.Series:
    """ATLFED_EXP_NEXT per observation date (percent)."""
    out = {}
    for obs, g in mpt.groupby("date"):
        mid = float(g["mid"].iloc[0])
        prior = sofr[sofr.index < pd.Timestamp(obs)] if not sofr.empty else sofr
        basis = float(prior.iloc[-1]) - mid if len(prior) else 0.0
        if abs(basis) > 0.5:  # a stale or broken fixing: ignore rather than distort
            basis = 0.0
        v = expected_after_next(g, mid, basis, obs, meetings)
        if v is not None:
            out[pd.Timestamp(obs)] = round(v, 6)
    return pd.Series(out, dtype="float64").sort_index()


def macro_rows(series: pd.Series, fetched_at: dt.datetime) -> list[dict[str, object]]:
    return [
        {
            "series_id": ATLFED_SERIES,
            "date": ts.date(),
            "value": float(v),
            "source": SOURCE_ATLFED,
            "published_at": dt.datetime.combine(ts.date(), dt.time(0), tzinfo=dt.UTC)
            + PUBLISH_DELAY,
            "fetched_at": fetched_at,
        }
        for ts, v in series.items()
    ]

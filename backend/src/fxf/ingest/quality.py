"""Rate sanity checks, run after every ingest.

A source can serve a wrong fix: on 26 May 2026 Frankfurter's CBA feed returned that day's
USD/AMD rate (367.74) for EUR/AMD and RUB/AMD too. Real crisis days also jump (the dram on
17 Dec 2014, RUB/AMD in 2014 and 2022), so a jump alone proves nothing. A row is removed
only when it is far from the pair's own recent level (more than SPIKE from the median of
its last BASE_ROWS kept rows) AND the pairs contradict each other:

- duplicate: it equals another pair's value on the same date, although the two pairs'
  usual levels are more than FAR_APART apart. That is the feed bug above.
- cross: EUR/AMD is more than CROSS away from EUR/USD x USD/AMD that day. The ECB and the
  CBA fix at different times, so a small gap is normal; on the 2014 crisis days the cross
  agrees and the rows stay.

Rows are walked in date order and a removed row never becomes part of the recent level, so
the newest row and a bug that lasts several days are caught too. repair_rates checks the
last RECENT_DAYS only: older history was checked once, and the early CBA data from 2000 is
noisy enough to fail the cross test without being a feed bug.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from typing import Any

import pandas as pd
from sqlalchemy import Engine, delete

from fxf.data_access import load_rates
from fxf.db import session_scope
from fxf.logging_setup import get_logger
from fxf.models import Rate, utcnow

log = get_logger(__name__)

SPIKE = 0.03
CROSS = 0.03
FAR_APART = 0.10
MATCH = 1e-4
BASE_ROWS = 10
RECENT_DAYS = 90
PAIRS_CHECKED = ("EURUSD", "USDAMD", "EURAMD", "RUBAMD")


def _jump(a: float, b: float) -> float:
    return abs(math.log(b / a))


def _far_apart(series: dict[str, pd.Series]) -> set[frozenset[str]]:
    """Pairs of series whose usual levels differ by more than FAR_APART."""
    out = set()
    names = list(series)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            j = pd.concat([series[a], series[b]], axis=1, join="inner").dropna()
            j = j[(j.iloc[:, 0] > 0) & (j.iloc[:, 1] > 0)]
            if (
                len(j) >= 30
                and abs(float((j.iloc[:, 0] / j.iloc[:, 1]).apply(math.log).median())) > FAR_APART
            ):
                out.add(frozenset((a, b)))
    return out


def find_bad_rates(
    series: dict[str, pd.Series], *, since: dt.date | None = None
) -> list[dict[str, Any]]:
    series = {p: s.dropna() for p, s in series.items() if len(s)}
    far = _far_apart(series)
    implied = None
    if {"EURAMD", "EURUSD", "USDAMD"} <= series.keys():
        j = pd.concat([series["EURUSD"], series["USDAMD"]], axis=1, join="inner")
        implied = j.iloc[:, 0] * j.iloc[:, 1]
    bad: list[dict[str, Any]] = []
    for pair, s in series.items():
        kept: list[float] = []
        for ts, value in s.items():
            v = float(value)
            day = ts.date()
            reason = None
            if v > 0 and len(kept) >= 3 and (since is None or day >= since):
                base = statistics.median(kept[-BASE_ROWS:])
                if _jump(base, v) > SPIKE:
                    for other, os in series.items():
                        if other == pair or frozenset((pair, other)) not in far:
                            continue
                        ov = os.get(ts)
                        if ov is not None and float(ov) > 0 and abs(v / float(ov) - 1) < MATCH:
                            reason = f"shows {other}'s value on the same day"
                            break
                    if reason is None and pair == "EURAMD" and implied is not None:
                        cross = implied.get(ts)
                        if cross is not None and cross > 0 and _jump(float(cross), v) > CROSS:
                            reason = f"contradicts EUR/USD x USD/AMD ({float(cross):.2f})"
            if reason is None:
                if v > 0:
                    kept.append(v)
                continue
            bad.append({"pair": pair, "date": day, "rate": v, "reason": reason})
    return sorted(bad, key=lambda b: (b["date"], b["pair"]))


def repair_rates(engine: Engine | None = None) -> list[dict[str, Any]]:
    with session_scope(engine) as s:
        series = {p: load_rates(s, p) for p in PAIRS_CHECKED}
        since = utcnow().date() - dt.timedelta(days=RECENT_DAYS)
        bad = find_bad_rates(series, since=since)
        for b in bad:
            s.execute(delete(Rate).where(Rate.pair == b["pair"], Rate.date == b["date"]))
    for b in bad:
        log.warning(
            "bad rate removed",
            extra={
                "pair": b["pair"],
                "date": b["date"].isoformat(),
                "rate": b["rate"],
                "reason": b["reason"],
            },
        )
    return bad

"""Central bank features (spec: Central bank events / Features for the model).

Contract used by the forecast engine and the backtest. Signatures are stable.

Point-in-time rule: a decision dated d is visible to a forecast made on day t only when
d < t. The Fed decides at 20:00 CET (after both fixes); the ECB and CBA decide around the
fixing time, so day-t decisions are treated as unknown on day t. Only scheduled meetings
count for "days until next meeting", because unscheduled ones were not known in advance.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from fxf.constants import BANKS
from fxf.models import CbEvent, CbMeeting


def load_meetings(session: Session) -> pd.DataFrame:
    """Columns: bank, date (Timestamp), scheduled (bool). Sorted by date."""
    rows = session.execute(
        select(CbMeeting.bank, CbMeeting.date, CbMeeting.scheduled).order_by(CbMeeting.date)
    ).all()
    return pd.DataFrame(
        {
            "bank": [r.bank for r in rows],
            "date": pd.to_datetime([r.date for r in rows]),
            "scheduled": [bool(r.scheduled) for r in rows],
        }
    )


def load_events(session: Session) -> pd.DataFrame:
    """Columns: bank, date, surprise_bps, hawkish_score, rate_after. Sorted by date."""
    rows = session.execute(
        select(
            CbEvent.bank,
            CbEvent.date,
            CbEvent.surprise_bps,
            CbEvent.hawkish_score,
            CbEvent.rate_after,
        ).order_by(CbEvent.date)
    ).all()
    return pd.DataFrame(
        {
            "bank": [r.bank for r in rows],
            "date": pd.to_datetime([r.date for r in rows]),
            "surprise_bps": [r.surprise_bps for r in rows],
            "hawkish_score": [r.hawkish_score for r in rows],
            "rate_after": [float(r.rate_after) if r.rate_after is not None else None for r in rows],
        }
    )


def meetings_in_window(
    meetings: pd.DataFrame, banks: tuple[str, ...] | list[str], start: dt.date, end: dt.date
) -> list[dict[str, str]]:
    """Meetings with start < date <= end for the given banks (FR-12).

    Returns [{"bank": "ECB", "date": "YYYY-MM-DD"}] sorted by date.
    """
    if meetings.empty:
        return []
    m = meetings[
        meetings["bank"].isin(list(banks))
        & (meetings["date"] > pd.Timestamp(start))
        & (meetings["date"] <= pd.Timestamp(end))
    ].sort_values(["date", "bank"])
    return [
        {"bank": b, "date": d.date().isoformat()} for b, d in zip(m["bank"], m["date"], strict=True)
    ]


def cb_feature_frame(
    dates: pd.DatetimeIndex, meetings: pd.DataFrame, events: pd.DataFrame
) -> pd.DataFrame:
    """One row per date with, for each bank B in BANKS:

    days_to_next_B   calendar days to the next scheduled meeting after date (NaN if none known)
    last_surprise_B  surprise_bps of the last decision strictly before date (0.0 if none yet)
    last_hawkish_B   hawkish_score of the last decision strictly before date (0.0 if none/unscored)
    days_since_B     calendar days since the last decision strictly before date (NaN if none)
    """
    idx = pd.DatetimeIndex(dates).as_unit("ns")
    out = pd.DataFrame(index=idx)
    for bank in BANKS:
        sched = (
            pd.DatetimeIndex(
                meetings[(meetings["bank"] == bank) & (meetings["scheduled"])]["date"].sort_values()
            )
            .as_unit("ns")
            .values
            if not meetings.empty
            else np.array([], dtype="datetime64[ns]")
        )
        if len(sched):
            pos = np.searchsorted(sched, idx.values, side="right")
            nxt = np.where(
                pos < len(sched), sched[np.minimum(pos, len(sched) - 1)], np.datetime64("NaT", "ns")
            )
            out[f"days_to_next_{bank}"] = (pd.DatetimeIndex(nxt) - idx).days.astype("float64")
        else:
            out[f"days_to_next_{bank}"] = np.nan

        ev = (
            events[events["bank"] == bank].sort_values("date")
            if not events.empty
            else pd.DataFrame(columns=["date", "surprise_bps", "hawkish_score"])
        )
        if len(ev):
            ev_dates = pd.DatetimeIndex(ev["date"]).as_unit("ns").values
            pos = np.searchsorted(ev_dates, idx.values, side="left") - 1  # strictly before
            has = pos >= 0
            safe = np.maximum(pos, 0)
            sur = pd.to_numeric(ev["surprise_bps"], errors="coerce").fillna(0.0).values
            hawk = pd.to_numeric(ev["hawkish_score"], errors="coerce").fillna(0.0).values
            out[f"last_surprise_{bank}"] = np.where(has, sur[safe], 0.0)
            out[f"last_hawkish_{bank}"] = np.where(has, hawk[safe], 0.0)
            last_d = pd.DatetimeIndex(np.where(has, ev_dates[safe], np.datetime64("NaT", "ns")))
            out[f"days_since_{bank}"] = (idx - last_d).days.astype("float64")
        else:
            out[f"last_surprise_{bank}"] = 0.0
            out[f"last_hawkish_{bank}"] = 0.0
            out[f"days_since_{bank}"] = np.nan
    return out


def last_decision(
    events: pd.DataFrame, bank: str, before: dt.date
) -> dict[str, float | None] | None:
    """The last decision of bank strictly before `before`, for the drivers panel."""
    if events.empty:
        return None
    ev = events[(events["bank"] == bank) & (events["date"] < pd.Timestamp(before))]
    if ev.empty:
        return None
    r = ev.iloc[-1]
    return {
        "date": r["date"].date().isoformat(),
        "surprise_bps": None if pd.isna(r["surprise_bps"]) else float(r["surprise_bps"]),
        "hawkish_score": None if pd.isna(r["hawkish_score"]) else float(r["hawkish_score"]),
    }

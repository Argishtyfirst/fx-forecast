"""Point-in-time read helpers shared by the forecast engine, backtest and API.

Everything here returns pandas objects indexed by date (DatetimeIndex, naive, daily).
`cutoff` arguments are tz-aware UTC datetimes: a macro value is visible only when
published_at < cutoff (NFR-03: no feature timestamp at or after the forecast cutoff).
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from fxf.constants import FED_MID
from fxf.models import CbEvent, MacroSeries, Rate


def load_rates(
    session: Session, pair: str, start: dt.date | None = None, end: dt.date | None = None
) -> pd.Series:
    q = select(Rate.date, Rate.rate).where(Rate.pair == pair)
    if start:
        q = q.where(Rate.date >= start)
    if end:
        q = q.where(Rate.date <= end)
    rows = session.execute(q.order_by(Rate.date)).all()
    s = pd.Series(
        [float(r.rate) for r in rows],
        index=pd.DatetimeIndex([pd.Timestamp(r.date) for r in rows], name="date"),
        name=pair,
        dtype="float64",
    )
    return s


def load_macro_frame(session: Session, series_id: str) -> pd.DataFrame:
    """All observations with columns value, published_at (UTC). Index = observation date.

    FED_MID is derived: (DFEDTARU + DFEDTARL) / 2, published when the later of the two is.
    """
    if series_id == FED_MID:
        u = load_macro_frame(session, "DFEDTARU")
        lo = load_macro_frame(session, "DFEDTARL")
        if u.empty or lo.empty:
            return pd.DataFrame(columns=["value", "published_at"])
        j = u.join(lo, how="inner", lsuffix="_u", rsuffix="_l")
        frame = pd.DataFrame(
            {
                "value": (j["value_u"] + j["value_l"]) / 2.0,
                "published_at": j[["published_at_u", "published_at_l"]].max(axis=1),
            }
        )
        return _with_fed_decisions(session, frame)
    rows = session.execute(
        select(MacroSeries.date, MacroSeries.value, MacroSeries.published_at)
        .where(MacroSeries.series_id == series_id)
        .order_by(MacroSeries.date)
    ).all()
    if not rows:
        return pd.DataFrame(columns=["value", "published_at"])
    return pd.DataFrame(
        {
            "value": [float(r.value) for r in rows],
            "published_at": pd.to_datetime([r.published_at for r in rows], utc=True),
        },
        index=pd.DatetimeIndex([pd.Timestamp(r.date) for r in rows], name="date"),
    )


def _with_fed_decisions(session: Session, frame: pd.DataFrame) -> pd.DataFrame:
    """Fill any gap after FRED's last observation with the Fed's own decisions.

    FRED can lag or be unreachable; the Fed decisions in cb_events (parsed from its press
    releases) carry the new target midpoint. A decision on day d takes effect on d + 1, as FRED
    records it, and was public at the statement (d at FED_STATEMENT_UTC_HOUR UTC) unless the
    event's own published_at says otherwise.
    """
    last = frame.index.max() if not frame.empty else None
    rows = session.execute(
        select(CbEvent.date, CbEvent.rate_after, CbEvent.published_at)
        .where(CbEvent.bank == "FED", CbEvent.rate_after.is_not(None))
        .order_by(CbEvent.date)
    ).all()
    extra = []
    for d, rate, published in rows:
        effective = pd.Timestamp(d + dt.timedelta(days=1))
        if last is not None and effective <= last:
            continue
        pub = published or dt.datetime.combine(d, dt.time(FED_STATEMENT_UTC_HOUR), tzinfo=dt.UTC)
        extra.append((effective, float(rate), pd.Timestamp(pub).tz_convert("UTC")))
    if not extra:
        return frame
    add = pd.DataFrame(
        {"value": [v for _, v, _ in extra], "published_at": [p for _, _, p in extra]},
        index=pd.DatetimeIndex([e for e, _, _ in extra], name="date"),
    )
    return pd.concat([frame, add]).sort_index()


# The FOMC statement comes out at 14:00 New York time: 18:00 or 19:00 UTC.
FED_STATEMENT_UTC_HOUR = 19


def asof_value(frame: pd.DataFrame, cutoff: dt.datetime) -> float | None:
    """Latest value published strictly before cutoff (by observation date)."""
    if frame.empty:
        return None
    visible = frame[frame["published_at"] < pd.Timestamp(cutoff)]
    if visible.empty:
        return None
    return float(visible["value"].iloc[-1])


def point_in_time_series(
    frame: pd.DataFrame, dates: pd.DatetimeIndex, cutoff_hour_utc: int = 16
) -> pd.Series:
    """For each date d, the latest value whose published_at < d at cutoff_hour_utc.

    Vectorised as-of join used by backtests and feature builders. The default cutoff
    (16:00 UTC) is the daily forecast cutoff: after both fixes, before the 18:00 CET deadline.
    """
    if frame.empty:
        return pd.Series(index=dates, dtype="float64")
    pub = frame.sort_values("published_at")
    left = pd.DataFrame(
        {
            "cutoff": pd.DatetimeIndex(dates).tz_localize("UTC").as_unit("ns")
            + pd.Timedelta(hours=cutoff_hour_utc)
        }
    )
    left["pos"] = range(len(left))
    right = pd.DataFrame(
        {
            "published_at": pd.to_datetime(pub["published_at"], utc=True).reset_index(drop=True),
            "obs_date": pd.Series(pub.index.values),
            "value": pub["value"].reset_index(drop=True).astype("float64"),
        }
    )
    # Among values published by the cutoff, keep the one with the latest observation date.
    right["published_at"] = right["published_at"].dt.as_unit("ns")
    right = right.sort_values("published_at")
    right["obs_rank"] = right["obs_date"].cummax()
    right = right[right["obs_date"] == right["obs_rank"]]
    merged = pd.merge_asof(
        left.sort_values("cutoff"),
        right[["published_at", "value"]],
        left_on="cutoff",
        right_on="published_at",
        direction="backward",
        allow_exact_matches=False,
    )
    merged = merged.sort_values("pos")
    return pd.Series(merged["value"].values, index=dates, dtype="float64")


def forecast_cutoff(run_date: dt.date, hour_utc: int = 16) -> dt.datetime:
    """The information cutoff for a forecast made on run_date."""
    return dt.datetime.combine(run_date, dt.time(hour_utc, 0), tzinfo=dt.UTC)

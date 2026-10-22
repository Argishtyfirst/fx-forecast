"""Load every input of one pair from Postgres into plain pandas objects (the only DB access
shared by the engine and the backtest; the model code downstream is pure).

Point-in-time: macro frames keep only rows with published_at <= forecast_cutoff(end), so a
value published after the run's cutoff can never reach a feature (NFR-03). The per-date
cutoff inside a backtest is applied later by data_access.point_in_time_series.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy.orm import Session

from fxf.constants import PAIRS, RUBAMD, PairSpec
from fxf.data_access import forecast_cutoff, load_macro_frame, load_rates
from fxf.events.features import load_events, load_meetings

# Macro series used as LightGBM change features (spec: LightGBM features).
MACRO_FEATURE_SERIES: tuple[str, ...] = ("DTWEXBGS", "DCOILBRENTEU", "DGS2")


@dataclass
class PairInputs:
    spec: PairSpec
    end: dt.date
    rates: pd.Series  # pair rates, DatetimeIndex, dates <= end
    macro: dict[str, pd.DataFrame]  # series_id -> (value, published_at), published <= cutoff
    meetings: pd.DataFrame  # bank, date, scheduled (all banks; the calendar is public)
    events: pd.DataFrame  # bank, date, surprise_bps, hawkish_score, rate_after (date < end + 1)
    aux_rates: dict[str, pd.Series] = field(default_factory=dict)  # RUBAMD for AMD pairs

    @property
    def pair(self) -> str:
        return self.spec.id


def macro_series_for(spec: PairSpec) -> tuple[str, ...]:
    return (spec.base_rate_series, spec.quote_rate_series, *MACRO_FEATURE_SERIES)


def _visible(frame: pd.DataFrame, cutoff: dt.datetime) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame[pd.to_datetime(frame["published_at"], utc=True) <= pd.Timestamp(cutoff)]


def load_pair_inputs(session: Session, pair: str, end: dt.date) -> PairInputs:
    spec = PAIRS[pair]
    cutoff = forecast_cutoff(end)
    rates = load_rates(session, pair, end=end)
    macro = {
        sid: _visible(load_macro_frame(session, sid), cutoff) for sid in macro_series_for(spec)
    }
    events = load_events(session)
    if not events.empty:
        events = events[events["date"] <= pd.Timestamp(end)].reset_index(drop=True)
    aux: dict[str, pd.Series] = {}
    if spec.quote == "AMD" and spec.base != "RUB":  # RUB/AMD feature for the other AMD pairs
        aux[RUBAMD.id] = load_rates(session, RUBAMD.id, end=end)
    return PairInputs(
        spec=spec,
        end=end,
        rates=rates,
        macro=macro,
        meetings=load_meetings(session),
        events=events,
        aux_rates=aux,
    )

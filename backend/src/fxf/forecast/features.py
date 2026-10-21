"""Pure feature builders for the forward and LightGBM models (no DB access).

One row per trading date t of the pair. Each value uses rates dated <= t and macro values
with published_at <= forecast_cutoff(t) (data_access.point_in_time_series), so the frame can
be built once and sliced by the walk-forward backtest without look-ahead (NFR-03).

Features (spec: LightGBM):
- ret_1, ret_5, ret_21, ret_63: log returns over 1, 5, 21, 63 trading days
- rv_5, rv_21: std of daily log returns over 5 and 21 days
- rate_diff_bps (quote minus base policy rate) and its 21-day change
- CB features for the pair's banks from events.features.cb_feature_frame
- 5- and 21-day changes of DTWEXBGS and Brent (log) and DGS2 (bps)
- AMD pairs only (USD/AMD, EUR/AMD): 1- and 5-day RUB/AMD log returns
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import pandas as pd

from fxf.constants import RUBAMD, PairSpec
from fxf.data_access import forecast_cutoff, point_in_time_series
from fxf.events.features import cb_feature_frame
from fxf.forecast.inputs import PairInputs

SERIES_BANK: dict[str, str] = {"ECB_DFR": "ECB", "FED_MID": "FED", "CBA_REFI": "CBA"}
CB_FEATURES: tuple[str, ...] = ("days_to_next", "last_surprise", "last_hawkish", "days_since")
# series_id -> (feature prefix, "log" change or "bps" difference)
MACRO_CHANGES: dict[str, tuple[str, str]] = {
    "DTWEXBGS": ("usd_broad", "log"),
    "DCOILBRENTEU": ("brent", "log"),
    "DGS2": ("ust2y", "bps"),
}
CHANGE_WINDOWS: tuple[int, ...] = (5, 21)


def feature_columns(spec: PairSpec) -> list[str]:
    cols = ["ret_1", "ret_5", "ret_21", "ret_63", "rv_5", "rv_21"]
    cols += ["rate_diff_bps", "rate_diff_chg_21d_bps"]
    cols += [f"{f}_{b}" for b in spec.banks for f in CB_FEATURES]
    for prefix, kind in MACRO_CHANGES.values():
        suffix = "_bps" if kind == "bps" else ""
        cols += [f"{prefix}_chg_{w}d{suffix}" for w in CHANGE_WINDOWS]
    if spec.quote == "AMD":
        cols += ["rubamd_ret_1", "rubamd_ret_5"]
    return cols


def policy_rate_frame(inputs: PairInputs, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Point-in-time policy rates in percent: columns i_base, i_quote (NaN if unknown)."""
    spec = inputs.spec
    return pd.DataFrame(
        {
            "i_base": point_in_time_series(inputs.macro[spec.base_rate_series], dates).to_numpy(),
            "i_quote": point_in_time_series(inputs.macro[spec.quote_rate_series], dates).to_numpy(),
        },
        index=dates,
    )


def build_features(inputs: PairInputs) -> pd.DataFrame:
    spec = inputs.spec
    dates = pd.DatetimeIndex(inputs.rates.index)
    lr = pd.Series(np.log(inputs.rates.to_numpy(dtype="float64")), index=dates)
    r1 = lr.diff()
    f = pd.DataFrame(index=dates)
    for w in (1, 5, 21, 63):
        f[f"ret_{w}"] = lr - lr.shift(w)
    for w in (5, 21):
        f[f"rv_{w}"] = r1.rolling(w).std()
    pr = policy_rate_frame(inputs, dates)
    diff = (pr["i_quote"] - pr["i_base"]) * 100.0
    f["rate_diff_bps"] = diff
    f["rate_diff_chg_21d_bps"] = diff - diff.shift(21)
    cb = cb_feature_frame(dates, inputs.meetings, inputs.events)
    for b in spec.banks:
        for name in CB_FEATURES:
            f[f"{name}_{b}"] = cb[f"{name}_{b}"].to_numpy()
    for sid, (prefix, kind) in MACRO_CHANGES.items():
        v = point_in_time_series(inputs.macro[sid], dates)
        base = np.log(v.where(v > 0)) if kind == "log" else v * 100.0
        for w in CHANGE_WINDOWS:
            suffix = "_bps" if kind == "bps" else ""
            f[f"{prefix}_chg_{w}d{suffix}"] = (base - base.shift(w)).to_numpy()
    if spec.quote == "AMD":
        rub = inputs.aux_rates.get(RUBAMD)
        if rub is not None and len(rub):
            aligned = np.log(
                pd.Series(rub.to_numpy(dtype="float64"), index=pd.DatetimeIndex(rub.index))
                .sort_index()
                .reindex(dates, method="ffill")
            )
            f["rubamd_ret_1"] = (aligned - aligned.shift(1)).to_numpy()
            f["rubamd_ret_5"] = (aligned - aligned.shift(5)).to_numpy()
        else:
            f["rubamd_ret_1"] = np.nan
            f["rubamd_ret_5"] = np.nan
    return f[feature_columns(spec)].astype("float64")


def input_timestamps(inputs: PairInputs, spot_date: dt.date) -> dict[str, Any]:
    """The latest timestamp of every input visible to a forecast on spot_date (NFR-03).

    macro_published_at holds the latest published_at used per series; every value must be
    before the cutoff. Rates carry no publication time, so their latest date is reported.
    """
    cutoff = forecast_cutoff(spot_date)
    spot_ts = pd.Timestamp(spot_date)
    macro_pub: dict[str, str | None] = {}
    for sid, fr in inputs.macro.items():
        if fr.empty:
            macro_pub[sid] = None
            continue
        pub = pd.to_datetime(fr["published_at"], utc=True)
        vis = pub[pub <= pd.Timestamp(cutoff)]
        macro_pub[sid] = vis.max().isoformat() if len(vis) else None

    def _last_date(s: pd.Series | None) -> str | None:
        if s is None or not len(s):
            return None
        idx = pd.DatetimeIndex(s.index)
        idx = idx[idx <= spot_ts]
        return idx.max().date().isoformat() if len(idx) else None

    ev = inputs.events
    ev_before = ev[ev["date"] < spot_ts] if not ev.empty else ev
    return {
        "cutoff": cutoff.isoformat(),
        "rates_through": _last_date(inputs.rates),
        "aux_rates_through": {k: _last_date(v) for k, v in inputs.aux_rates.items()},
        "macro_published_at": macro_pub,
        "cb_events_through": (
            ev_before["date"].max().date().isoformat() if len(ev_before) else None
        ),
    }

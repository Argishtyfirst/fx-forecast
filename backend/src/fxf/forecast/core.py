"""Walk-forward core shared by the live engine (one origin) and the backtest (every origin).

For an origin i (a trading date of the pair) every input is restricted to data <= t_i:
rates up to index i, macro values published by forecast_cutoff(t_i), decisions strictly before
t_i, LightGBM labels realised by t_i. The meeting calendar and the trading-day calendar are
public in advance. Refits follow params.GARCH_REFIT_EVERY / LGBM_REFIT_EVERY measured in
origins; the engine passes a single origin, so it always refits.

All center models predict mu, the h-day log return; the bands share one band model per origin
and horizon, built in this order:
  1. sigma_pre^2 = sum of GARCH daily variances + event extra variance (fxf.forecast.widening)
  2. 1M: the empirical quantile check may widen sigma_pre (fxf.forecast.bands)
  3. walk-forward calibration: band L = mu +- c_L * t_unit * sigma_pre, with c_L from the
     trailing outcomes realised by t_i (fxf.forecast.calibration)
sigma_ref is the GARCH-only sigma (no widening, no check, no calibration), the pinball reference.
The engine passes the trailing origins as `history` so its calibration matches the backtest.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from fxf.calendars import PAIR_CALENDAR, add_trading_days
from fxf.constants import CENTER_CANDIDATES, HORIZONS, MODEL_FORWARD, MODEL_LGBM, MODEL_RW
from fxf.forecast import bands, calibration, garch, lgbm, params
from fxf.forecast.features import build_features, feature_columns, policy_rate_frame
from fxf.forecast.forward import forward_log_return, year_fraction
from fxf.forecast.inputs import PairInputs
from fxf.forecast.widening import EventRatios, extra_variance, impact_indices, meeting_steps


class InsufficientData(RuntimeError):
    """Not enough history to fit the band model for this pair."""


@dataclass
class PairData:
    inputs: PairInputs
    calendar: str
    dates: pd.DatetimeIndex
    dates64: np.ndarray  # datetime64[D]
    rates: np.ndarray
    log_rates: np.ndarray
    returns: np.ndarray  # returns[k] = log_rates[k] - log_rates[k-1]; returns[0] = NaN
    features: pd.DataFrame
    X: np.ndarray
    feature_names: list[str]
    i_base: np.ndarray  # policy rates in percent, point in time (NaN if unknown)
    i_quote: np.ndarray
    event_ratios: EventRatios
    widen_dates: np.ndarray  # meetings used for widening, sorted, datetime64[D]
    widen_banks: np.ndarray
    emp_width: dict[int, np.ndarray]
    emp_count: dict[int, np.ndarray]

    @property
    def pair(self) -> str:
        return self.inputs.spec.id

    @property
    def n(self) -> int:
        return len(self.rates)

    def window_start(self, i: int, window: int | None) -> int:
        return 1 if window is None else max(1, i - window + 1)

    def horizon_dates(self, i: int, h: int) -> np.ndarray:
        """The h trading dates after origin i (series dates, then the pair calendar)."""
        have = self.dates64[i + 1 : i + 1 + h]
        if len(have) == h:
            return have
        last = (have[-1] if len(have) else self.dates64[i]).astype("datetime64[D]").astype(object)
        more = [add_trading_days(self.calendar, last, k) for k in range(1, h - len(have) + 1)]
        return np.concatenate([have, np.array(more, dtype="datetime64[D]")])


def prepare_pair_data(inputs: PairInputs, *, widening: str = "all") -> PairData:
    """widening="all" uses every meeting in the calendar (live engine); "scheduled" uses only
    meetings known in advance (backtest: unscheduled ones were not known at forecast time)."""
    spec = inputs.spec
    if len(inputs.rates) < params.GARCH_MIN_OBS + 2:
        raise InsufficientData(
            f"{spec.id}: {len(inputs.rates)} rates, need {params.GARCH_MIN_OBS + 2}"
        )
    dates = pd.DatetimeIndex(inputs.rates.index)
    dates64 = dates.values.astype("datetime64[D]")
    rates = inputs.rates.to_numpy(dtype="float64")
    log_rates = np.log(rates)
    returns = np.concatenate([[np.nan], np.diff(log_rates)])
    features = build_features(inputs)
    pr = policy_rate_frame(inputs, dates)

    m = inputs.meetings
    if not m.empty:
        m = m[m["bank"].isin(list(spec.banks))].sort_values(["date", "bank"])
    m_dates = (
        pd.DatetimeIndex(m["date"]).values.astype("datetime64[D]")
        if not m.empty
        else np.array([], dtype="datetime64[D]")
    )
    m_banks = m["bank"].to_numpy(dtype=object) if not m.empty else np.array([], dtype=object)
    m_sched = m["scheduled"].to_numpy(dtype=bool) if not m.empty else np.array([], dtype=bool)
    impact_by_bank = {
        b: impact_indices(m_dates[(m_banks == b) & m_sched], dates64) for b in spec.banks
    }
    exclude = impact_indices(m_dates, dates64)
    event_ratios = EventRatios(returns, impact_by_bank, exclude)
    if widening == "scheduled":
        widen_dates, widen_banks = m_dates[m_sched], m_banks[m_sched]
    elif widening == "all":
        widen_dates, widen_banks = m_dates, m_banks
    else:
        raise ValueError(f"unknown widening mode {widening!r}")

    emp_width: dict[int, np.ndarray] = {}
    emp_count: dict[int, np.ndarray] = {}
    for h in params.EMPIRICAL_HORIZONS:
        emp_width[h], emp_count[h] = bands.empirical_widths(log_rates, h)

    names = feature_columns(spec)
    return PairData(
        inputs=inputs,
        calendar=PAIR_CALENDAR[spec.id],
        dates=dates,
        dates64=dates64,
        rates=rates,
        log_rates=log_rates,
        returns=returns,
        features=features,
        X=features[names].to_numpy(dtype="float64"),
        feature_names=names,
        i_base=pr["i_base"].to_numpy(dtype="float64"),
        i_quote=pr["i_quote"].to_numpy(dtype="float64"),
        event_ratios=event_ratios,
        widen_dates=widen_dates,
        widen_banks=widen_banks,
        emp_width=emp_width,
        emp_count=emp_count,
    )


@dataclass
class HorizonOutput:
    sigma: np.ndarray  # sigma_pre scaled by the 80% calibration factor (80%-band equivalent)
    sigma_pre: np.ndarray  # after event widening and the empirical check, before calibration
    sigma_ref: np.ndarray  # GARCH only
    nu_h: np.ndarray
    garch_var: np.ndarray
    extra_var: np.ndarray
    mu: dict[str, np.ndarray]
    cal: np.ndarray  # (n, 3) calibration factors for the 50/80/95 bands
    cal_n: np.ndarray
    cal_through: np.ndarray  # index of the latest outcome the calibration used (-1: none)
    detail: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class WalkForward:
    origins: np.ndarray
    nu: np.ndarray
    vol_annual: np.ndarray
    horizons: dict[int, HorizonOutput]
    garch_detail: list[dict[str, Any]] = field(default_factory=list)
    lgbm_detail: dict[int, list[dict[str, Any] | None]] = field(default_factory=dict)


def _lgbm_train_rows(data: PairData, t: int, h: int) -> np.ndarray:
    """Training rows for a fit at origin t: labels log(S[j+h]/S[j]) realised by t."""
    window = params.lgbm_window(data.inputs.spec)
    hi = t - h
    lo = params.FEATURE_WARMUP if window is None else max(params.FEATURE_WARMUP, hi - window + 1)
    if hi < lo:
        return np.array([], dtype=int)
    return np.arange(lo, hi + 1)


def _lgbm_predictions(
    data: PairData, origins: np.ndarray, h: int, seed: int, every: int, detail: bool
) -> tuple[np.ndarray, list[dict[str, Any] | None]]:
    mu = np.full(len(origins), np.nan)
    info: list[dict[str, Any] | None] = [None] * len(origins)
    refits: list[int] = []
    last: int | None = None
    for k, i in enumerate(origins):
        if last is None or i - last >= every:
            refits.append(k)
            last = int(i)
    refits.append(len(origins))
    for a, b in zip(refits[:-1], refits[1:], strict=True):
        t = int(origins[a])
        rows = _lgbm_train_rows(data, t, h)
        if len(rows) < params.LGBM_MIN_TRAIN_ROWS:
            continue
        y = data.log_rates[rows + h] - data.log_rates[rows]
        booster = lgbm.train(data.X[rows], y, seed, data.feature_names)
        block = origins[a:b]
        mu[a:b] = lgbm.predict(booster, data.X[block])
        if detail:
            for k in range(a, b):
                i = int(origins[k])
                info[k] = {
                    "features": {
                        n: (None if not math.isfinite(v) else float(v))
                        for n, v in zip(data.feature_names, data.X[i], strict=True)
                    },
                    "train_rows": int(len(rows)),
                    "train_start": data.dates[rows[0]].date().isoformat(),
                    "train_end": data.dates[rows[-1]].date().isoformat(),
                    "labels_through": data.dates[rows[-1] + h].date().isoformat(),
                    "fit_origin": data.dates[t].date().isoformat(),
                    "num_boost_round": lgbm.NUM_BOOST_ROUND,
                    "params": {k2: v for k2, v in lgbm.lgbm_params(seed).items()},
                }
    return mu, info


def walk_forward(
    data: PairData,
    origins: np.ndarray | list[int],
    *,
    seed: int,
    horizons: tuple[int, ...] = HORIZONS,
    garch_refit_every: int = params.GARCH_REFIT_EVERY,
    lgbm_refit_every: int = params.LGBM_REFIT_EVERY,
    with_lgbm: bool = True,
    detail: bool = False,
    calibrate: bool = True,
    history: WalkForward | None = None,
) -> WalkForward:
    """Forecast every origin. `history` holds earlier origins (all before origins[0]) whose
    pre-calibration bands feed the calibration of these origins: the live engine passes the
    trailing window there; the backtest calibrates from its own earlier origins."""
    origins = np.asarray(origins, dtype=int)
    if len(origins) and (np.any(np.diff(origins) <= 0) or origins[0] < 1 or origins[-1] >= data.n):
        raise ValueError("origins must be increasing indices into the rate series")
    pair = data.pair
    banks = data.inputs.spec.banks
    gwin = params.garch_window(data.inputs.spec)
    ewin = gwin  # the event-variance ratio uses the GARCH window
    steps_max = max(horizons)
    n_o = len(origins)
    r = data.returns

    out = {
        h: HorizonOutput(
            sigma=np.empty(n_o),
            sigma_pre=np.empty(n_o),
            sigma_ref=np.empty(n_o),
            nu_h=np.empty(n_o),
            garch_var=np.empty(n_o),
            extra_var=np.empty(n_o),
            mu={},
            cal=np.ones((n_o, len(bands.CAL_LEVELS))),
            cal_n=np.zeros(n_o, dtype=int),
            cal_through=np.full(n_o, -1, dtype=int),
        )
        for h in horizons
    }
    nu_arr = np.empty(n_o)
    vol_arr = np.empty(n_o)
    garch_detail: list[dict[str, Any]] = []

    state: garch.GarchState | None = None
    last_fit: int | None = None
    fit_window = (0, 0)
    for k, i in enumerate(origins):
        i = int(i)
        if state is None or last_fit is None or i - last_fit >= garch_refit_every:
            lo = data.window_start(i, gwin)
            if i - lo + 1 < params.GARCH_MIN_OBS:
                raise InsufficientData(f"{pair}: {i - lo + 1} returns before origin {i}")
            state = garch.fit_garch(r[lo : i + 1], i, previous=state.fit if state else None)
            last_fit = i
            fit_window = (lo, i)
        else:
            state = garch.advance(state, r, i)
        path = garch.daily_variance_path(state, r, steps_max)
        nu = state.fit.nu
        nu_arr[k] = nu
        vol_arr[k] = garch.annualised_vol(path)

        elo = data.window_start(i, ewin)
        ratio_stats = {
            b: data.event_ratios.combined(
                b,
                elo,
                i,
                recent_days=params.EVENT_RECENT_DAYS,
                prior_meetings=params.EVENT_PRIOR_MEETINGS,
                recent_min_normal=params.EVENT_RECENT_MIN_NORMAL,
            )
            for b in banks
        }
        ratios = {b: ratio_stats[b]["ratio"] for b in banks}
        if detail:
            garch_detail.append(
                {
                    **state.fit.to_json(),
                    "window_start": data.dates[fit_window[0]].date().isoformat(),
                    "window_end": data.dates[fit_window[1]].date().isoformat(),
                    "fit_origin": data.dates[last_fit].date().isoformat(),
                }
            )

        spot_d = data.dates64[i]
        for h in horizons:
            ho = out[h]
            gv = garch.horizon_variance(path, h)
            sig_ref = bands.floor_sigma(math.sqrt(gv), h)
            hd = data.horizon_dates(i, h)
            a = int(np.searchsorted(data.widen_dates, spot_d - np.timedelta64(1, "D"), "right"))
            b = int(np.searchsorted(data.widen_dates, hd[-1], "right"))
            m_dates = data.widen_dates[a:b]
            m_banks = data.widen_banks[a:b]
            steps = meeting_steps(list(m_dates), hd)
            m_ratios = [ratios.get(str(bk)) for bk in m_banks]
            extra = extra_variance(path, steps, m_ratios)
            sig = bands.floor_sigma(math.sqrt(gv + extra), h)
            nu_h = bands.horizon_nu(nu, h)
            emp_info = None
            if h in data.emp_width:
                w = float(data.emp_width[h][i])
                sig, emp_info = bands.empirical_check(
                    sig, nu_h, w if math.isfinite(w) else None, int(data.emp_count[h][i])
                )
            ho.sigma_pre[k] = sig
            ho.sigma_ref[k] = sig_ref
            ho.nu_h[k] = nu_h
            ho.garch_var[k] = gv
            ho.extra_var[k] = extra
            if detail:
                ho.detail.append(
                    {
                        "horizon_dates": [str(d) for d in hd],
                        "empirical_check": emp_info,
                        "event_widening": {
                            "ratios": ratios,
                            # per bank: ratio_recent, n_recent, ratio_long, n_long, K
                            "ratio_detail": ratio_stats,
                            "meetings": [
                                {
                                    "bank": str(bk),
                                    "date": str(md),
                                    "impact_step": int(st),
                                    "impact_date": str(hd[st - 1]),
                                    "ratio": ratios.get(str(bk)),
                                    "extra_variance": (
                                        (max(ratios[str(bk)], 1.0) - 1.0) * float(path[st - 1])
                                        if ratios.get(str(bk)) is not None
                                        else 0.0
                                    ),
                                }
                                for bk, md, st in zip(m_banks, m_dates, steps, strict=True)
                            ],
                        },
                    }
                )

    if history is not None and len(history.origins) and len(origins):
        if history.origins[-1] >= origins[0]:
            raise ValueError("history origins must precede the origins")
    k80 = bands.CAL_LEVELS.index("80")
    for h in horizons:
        ho = out[h]
        if calibrate and n_o:
            if history is not None and h in history.horizons:
                hh = history.horizons[h]
                h_o = np.concatenate([history.origins, origins])
                h_sig = np.concatenate([hh.sigma_pre, ho.sigma_pre])
                h_nu = np.concatenate([hh.nu_h, ho.nu_h])
            else:
                h_o, h_sig, h_nu = origins, ho.sigma_pre, ho.nu_h
            cal = calibration.calibrate(
                data.log_rates,
                h_o,
                h_sig,
                h_nu,
                origins,
                h,
                window=params.CAL_WINDOW,
                min_obs=params.CAL_MIN_OBS,
                clamp=params.CAL_CLAMP,
                per_level=params.CAL_PER_LEVEL,
            )
            ho.cal, ho.cal_n, ho.cal_through = cal.factors, cal.n_obs, cal.outcomes_through
        ho.sigma = ho.sigma_pre * ho.cal[:, k80]
        if detail:
            for k in range(n_o):
                th = int(ho.cal_through[k])
                ho.detail[k]["band_calibration"] = {
                    "factors": {lv: float(ho.cal[k, j]) for j, lv in enumerate(bands.CAL_LEVELS)},
                    "applied": bool(ho.cal_n[k] >= params.CAL_MIN_OBS),
                    "n_obs": int(ho.cal_n[k]),
                    "outcomes_through": data.dates[th].date().isoformat() if th >= 0 else None,
                    "window": params.CAL_WINDOW,
                    "min_obs": params.CAL_MIN_OBS,
                    "clamp": list(params.CAL_CLAMP),
                    "per_level": params.CAL_PER_LEVEL,
                    "center": "random_walk",
                }

    lgbm_detail: dict[int, list[dict[str, Any] | None]] = {}
    for h in horizons:
        ho = out[h]
        cands = CENTER_CANDIDATES.get(h, (MODEL_RW,))
        ho.mu[MODEL_RW] = np.zeros(n_o)
        ho.mu[MODEL_FORWARD] = np.asarray(
            forward_log_return(data.i_base[origins], data.i_quote[origins], h), dtype="float64"
        )
        if with_lgbm and MODEL_LGBM in cands and n_o:
            ho.mu[MODEL_LGBM], lgbm_detail[h] = _lgbm_predictions(
                data, origins, h, seed, lgbm_refit_every, detail
            )
        else:
            ho.mu[MODEL_LGBM] = np.full(n_o, np.nan)
            lgbm_detail[h] = [None] * n_o
        if detail:
            for k, i in enumerate(origins):
                ho.detail[k]["forward"] = {
                    "i_base_pct": _f(data.i_base[i]),
                    "i_quote_pct": _f(data.i_quote[i]),
                    "base_series": data.inputs.spec.base_rate_series,
                    "quote_series": data.inputs.spec.quote_rate_series,
                    "tau": year_fraction(h),
                    "tau_convention": "h trading days / 252",
                }
    return WalkForward(
        origins=origins,
        nu=nu_arr,
        vol_annual=vol_arr,
        horizons=out,
        garch_detail=garch_detail,
        lgbm_detail=lgbm_detail,
    )


def _f(v: float) -> float | None:
    v = float(v)
    return v if math.isfinite(v) else None

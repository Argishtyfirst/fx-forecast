"""Event widening (spec: Event widening, FR-12).

Per bank and pair, the ratio of realised variance (mean squared daily log return) on meeting
impact days to normal days. The impact day is the first trading day of the pair strictly after
the meeting date: the Fed decides after both fixes, and the ECB decision follows the 14:10 CET
concertation, so the move shows up in the next fix. Normal days exclude the impact days of
every meeting (scheduled or not) of the pair's banks; the ratio itself uses scheduled meetings.

For each meeting inside the horizon:

    extra variance += (max(ratio, 1) - 1) * daily variance forecast of its impact day

The ratio is recency-weighted (walk-forward, data <= t only):

    ratio_recent = ratio over the last params.EVENT_RECENT_DAYS trading days (n_recent meetings)
    ratio_long   = ratio over the GARCH window (expanding for EUR/USD, 1000 days for AMD pairs)
    combined     = (n_recent * ratio_recent + K * ratio_long) / (n_recent + K)

with K = params.EVENT_PRIOR_MEETINGS: the long-run ratio acts as a prior worth K meetings, so
a year of ~8 meetings weighs about as much as the whole history. Without a long-run ratio
(too few meetings in the calendar) the prior is 1 (no meeting effect).

A meeting whose impact day falls after the target date (a meeting on the target date) adds
its extra variance on the last day of the horizon. FR-12 widens whenever a meeting is inside
the horizon, and ECB and CBA decisions come out around the fixing time, so they can reach the
target fix. Widening is applied at every horizon, including 1D, and never narrows a band. A
bank with fewer than params.EVENT_MIN_MEETINGS impact days in the window gets ratio None
(no widening).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from fxf.forecast import params


def impact_indices(meeting_dates: np.ndarray, trading_dates: np.ndarray) -> np.ndarray:
    """Index of the first trading date strictly after each meeting date (len if none)."""
    return np.searchsorted(
        np.asarray(trading_dates, dtype="datetime64[D]"),
        np.asarray(meeting_dates, dtype="datetime64[D]"),
        side="right",
    )


def meeting_steps(meeting_dates: Sequence[np.datetime64], horizon_dates: np.ndarray) -> list[int]:
    """Step (1..h) of each meeting's impact day within the horizon trading dates.

    horizon_dates are the h trading dates after the spot date. A meeting whose impact day lies
    beyond the last one maps to step h (see module docstring).
    """
    h = len(horizon_dates)
    hd = np.asarray(horizon_dates, dtype="datetime64[D]")
    pos = np.searchsorted(hd, np.asarray(meeting_dates, dtype="datetime64[D]"), side="right")
    return [int(min(p, h - 1)) + 1 for p in pos]


def extra_variance(
    daily_path: np.ndarray, steps: Sequence[int], ratios: Sequence[float | None]
) -> float:
    """Sum of (max(ratio, 1) - 1) * daily variance at each meeting's impact step."""
    total = 0.0
    for step, ratio in zip(steps, ratios, strict=True):
        if ratio is None or not np.isfinite(ratio):
            continue
        total += (max(float(ratio), 1.0) - 1.0) * float(daily_path[step - 1])
    return total


class EventRatios:
    """Windowed variance ratios in O(1) per query via cumulative sums.

    returns[k] is the log return on trading day k (returns[0] is NaN and never used). A bank's
    window starts no earlier than its first recorded impact day, so the years before the
    meeting calendar begins (meeting days unknown) are not counted as normal days.
    """

    def __init__(
        self,
        returns: np.ndarray,
        impact_by_bank: Mapping[str, np.ndarray],
        exclude: np.ndarray,
        min_meetings: int = params.EVENT_MIN_MEETINGS,
        min_normal: int = params.EVENT_MIN_NORMAL_DAYS,
    ) -> None:
        n = len(returns)
        sq = np.where(np.isfinite(returns), np.asarray(returns, dtype="float64") ** 2, 0.0)
        valid = np.isfinite(returns).astype("float64")
        excl = np.zeros(n, dtype=bool)
        idx = np.asarray(exclude, dtype=int)
        excl[idx[(idx >= 0) & (idx < n)]] = True
        normal = valid * (~excl)
        self._n = n
        self.min_meetings = min_meetings
        self.min_normal = min_normal
        self._normal_sq = np.concatenate([[0.0], np.cumsum(sq * normal)])
        self._normal_n = np.concatenate([[0.0], np.cumsum(normal)])
        self._bank_sq: dict[str, np.ndarray] = {}
        self._bank_n: dict[str, np.ndarray] = {}
        self._bank_first: dict[str, int] = {}
        for bank, imp in impact_by_bank.items():
            ind = np.zeros(n)
            ii = np.asarray(imp, dtype=int)
            ii = ii[(ii >= 0) & (ii < n)]
            ind[ii] = 1.0
            self._bank_first[bank] = int(ii.min()) if len(ii) else n
            ind *= valid
            self._bank_sq[bank] = np.concatenate([[0.0], np.cumsum(sq * ind)])
            self._bank_n[bank] = np.concatenate([[0.0], np.cumsum(ind)])

    def stats(
        self,
        bank: str,
        lo: int,
        hi: int,
        *,
        min_meetings: int | None = None,
        min_normal: int | None = None,
    ) -> dict[str, float | int | None]:
        """Ratio over returns lo..hi inclusive, with its inputs."""
        min_meetings = self.min_meetings if min_meetings is None else min_meetings
        min_normal = self.min_normal if min_normal is None else min_normal
        if bank not in self._bank_n:
            return {"ratio": None, "n_meetings": 0, "n_normal": 0}
        lo = max(lo, min(self._bank_first[bank], hi + 1))
        nn = self._normal_n[hi + 1] - self._normal_n[lo]
        ns = self._normal_sq[hi + 1] - self._normal_sq[lo]
        bn = self._bank_n[bank][hi + 1] - self._bank_n[bank][lo]
        bs = self._bank_sq[bank][hi + 1] - self._bank_sq[bank][lo]
        ratio: float | None = None
        if bn >= max(min_meetings, 1) and nn >= min_normal and ns > 0:
            ratio = float((bs / bn) / (ns / nn))
        return {"ratio": ratio, "n_meetings": int(bn), "n_normal": int(nn)}

    def ratio(self, bank: str, lo: int, hi: int) -> float | None:
        r = self.stats(bank, lo, hi)["ratio"]
        return None if r is None else float(r)

    def combined(
        self,
        bank: str,
        lo_long: int,
        hi: int,
        *,
        recent_days: int = params.EVENT_RECENT_DAYS,
        prior_meetings: float = params.EVENT_PRIOR_MEETINGS,
        recent_min_normal: int = params.EVENT_RECENT_MIN_NORMAL,
    ) -> dict[str, float | int | None]:
        """Recency-weighted ratio at origin hi (returns lo_long..hi), see the module docstring."""
        long = self.stats(bank, lo_long, hi)
        recent = self.stats(
            bank,
            max(lo_long, hi - recent_days + 1),
            hi,
            min_meetings=1,
            min_normal=recent_min_normal,
        )
        r_long = long["ratio"]
        r_recent = recent["ratio"]
        n_recent = int(recent["n_meetings"]) if r_recent is not None else 0
        prior = 1.0 if r_long is None else float(r_long)
        combined = shrink_ratio(r_recent, n_recent, prior, prior_meetings)
        if r_long is None and n_recent == 0:
            combined = None
        return {
            "ratio": combined,
            "ratio_recent": r_recent,
            "n_recent": n_recent,
            "ratio_long": r_long,
            "n_long": int(long["n_meetings"]),
            "prior_meetings": prior_meetings,
        }


def shrink_ratio(
    ratio_recent: float | None, n_recent: int, prior: float, prior_meetings: float
) -> float:
    """(n_recent * ratio_recent + K * prior) / (n_recent + K); the prior alone without data."""
    if ratio_recent is None or n_recent <= 0:
        return float(prior)
    return float((n_recent * ratio_recent + prior_meetings * prior) / (n_recent + prior_meetings))


def variance_ratio(returns: np.ndarray, event_mask: np.ndarray, normal_mask: np.ndarray) -> float:
    """Plain (non-windowed) ratio: mean r^2 on event days / mean r^2 on normal days."""
    r = np.asarray(returns, dtype="float64")
    ev = r[np.asarray(event_mask, dtype=bool) & np.isfinite(r)]
    no = r[np.asarray(normal_mask, dtype=bool) & np.isfinite(r)]
    return float(np.mean(ev**2) / np.mean(no**2))

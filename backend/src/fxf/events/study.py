"""Meeting reaction study: how each pair moved around recent central bank meetings, from daily
fixes. It shows the path (run-up, reaction, follow-through), not only one day's close.

For a meeting on day d:

    pre       the last fix on or before d. The ECB fix (14:10 CET) comes before both the FOMC
              statement (20:00 CET) and the ECB decision (14:15 CET), and the CBA's daily
              average closes before the FOMC, so this is the price before the decision.
    impact    the first fix after d, the same convention as fxf.forecast.widening.
    run_up    log(pre / the fix RUN_DAYS trading days before pre): drift into the meeting.
    reaction  log(impact / pre): the move around the decision.
    follow    log(the fix RUN_DAYS trading days after impact / impact): drift afterwards.

All moves are in percent. The normal-day reference is the median absolute daily move over
the same window, excluding impact days.

Direction: a hawkish surprise (or, with no rate surprise, a hawkish statement) should lift
the bank's currency. That means up for the pair when the bank's currency is the base, down
when it is the quote, and no expected direction when the bank's currency is in neither (the
Fed for EUR/AMD). `consistency` is the share of signed meetings whose reaction went that way.

Point in time: only fixes up to `as_of` are used, so a meeting whose impact fix is not yet
known is left out, and a follow-through that is not complete yet is None.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from fxf.constants import PairSpec
from fxf.data_access import load_rates
from fxf.events.features import load_meetings
from fxf.models import CbEvent

CURRENCY_BANK = {"EUR": "ECB", "USD": "FED", "AMD": "CBA"}
RUN_DAYS = 5
LOOKBACK_DAYS = 365
MIN_SURPRISE_BPS = 1.0
MIN_TONE = 0.15
MIN_CORRELATION_N = 5


@dataclass(frozen=True)
class MeetingReaction:
    bank: str
    date: dt.date
    surprise_bps: float | None
    hawkish_score: float | None
    rate_change_bps: float | None
    run_up_pct: float | None
    reaction_pct: float
    follow_pct: float | None
    expected_sign: int  # +1 the pair should rise on a hawkish signal, -1 fall, 0 no view
    signal: int  # +1 hawkish (surprise, else tone), -1 dovish, 0 neutral
    followed: bool | None  # reaction went the way the signal implies (None when unsigned)


@dataclass(frozen=True)
class BankReactionSummary:
    bank: str
    n: int
    mean_abs_reaction_pct: float | None
    normal_abs_move_pct: float | None
    reaction_ratio: float | None  # mean |reaction| / normal-day |move|
    mean_run_up_pct: float | None
    mean_follow_pct: float | None
    n_signed: int
    consistency: float | None
    correlation: float | None  # of the signed signal with the reaction, n >= MIN_CORRELATION_N


def expected_sign(pair: PairSpec, bank: str) -> int:
    if CURRENCY_BANK.get(pair.base) == bank:
        return 1
    if CURRENCY_BANK.get(pair.quote) == bank:
        return -1
    return 0


def _signal(surprise: float | None, tone: float | None) -> tuple[int, float | None]:
    """(sign, strength): the rate surprise when there was one, else the statement's tone."""
    if surprise is not None and not math.isnan(surprise) and abs(surprise) >= MIN_SURPRISE_BPS:
        return (1 if surprise > 0 else -1), surprise / 25.0
    if tone is not None and not math.isnan(tone) and abs(tone) >= MIN_TONE:
        return (1 if tone > 0 else -1), tone
    return 0, None


def _pct(a: float, b: float) -> float:
    return round(math.log(a / b) * 100.0, 4)


def _mean(xs: list[float]) -> float | None:
    return round(float(np.mean(xs)), 4) if xs else None


def study(
    pair: PairSpec,
    rates: pd.Series,
    meetings: pd.DataFrame,
    events: dict[tuple[str, dt.date], CbEvent],
    as_of: dt.date,
    lookback_days: int = LOOKBACK_DAYS,
) -> tuple[list[BankReactionSummary], list[MeetingReaction]]:
    """Reactions to every meeting of the pair's banks in (as_of - lookback, as_of]."""
    s = rates[rates.index <= pd.Timestamp(as_of)].astype("float64")
    if len(s) < RUN_DAYS + 2 or meetings.empty:
        return [
            BankReactionSummary(b, 0, None, None, None, None, None, 0, None, None)
            for b in pair.banks
        ], []
    dates = s.index.values.astype("datetime64[D]")
    values = s.to_numpy()
    start = pd.Timestamp(as_of - dt.timedelta(days=lookback_days))
    window = meetings[
        meetings["bank"].isin(list(pair.banks))
        & (meetings["date"] > start)
        & (meetings["date"] <= pd.Timestamp(as_of))
    ].sort_values("date")

    reactions: list[MeetingReaction] = []
    impact_idx: set[int] = set()
    for bank, day in zip(window["bank"], window["date"], strict=True):
        d = np.datetime64(day.date(), "D")
        pre = int(np.searchsorted(dates, d, side="right")) - 1
        impact = pre + 1
        if pre < 0 or impact >= len(values):
            continue  # the impact fix is not known yet
        impact_idx.add(impact)
        ev = events.get((bank, day.date()))
        surprise = None if ev is None or ev.surprise_bps is None else float(ev.surprise_bps)
        tone = None if ev is None or ev.hawkish_score is None else float(ev.hawkish_score)
        change = (
            None
            if ev is None or ev.rate_before is None or ev.rate_after is None
            else round((float(ev.rate_after) - float(ev.rate_before)) * 100.0, 1)
        )
        sign, _ = _signal(surprise, tone)
        exp = expected_sign(pair, bank)
        reaction = _pct(values[impact], values[pre])
        followed = (
            None if sign == 0 or exp == 0 or reaction == 0 else (reaction > 0) == (sign * exp > 0)
        )
        reactions.append(
            MeetingReaction(
                bank=bank,
                date=day.date(),
                surprise_bps=surprise,
                hawkish_score=tone,
                rate_change_bps=change,
                run_up_pct=_pct(values[pre], values[pre - RUN_DAYS]) if pre >= RUN_DAYS else None,
                reaction_pct=reaction,
                follow_pct=_pct(values[impact + RUN_DAYS], values[impact])
                if impact + RUN_DAYS < len(values)
                else None,
                expected_sign=exp,
                signal=sign,
                followed=followed,
            )
        )

    in_window = np.nonzero(dates > np.datetime64(start.date(), "D"))[0]
    rets = np.abs(np.diff(np.log(values))) * 100.0  # rets[i-1] is the move into fix i
    normal = [rets[i - 1] for i in in_window if i > 0 and i not in impact_idx]
    normal_move = round(float(np.median(normal)), 4) if normal else None

    summaries = []
    for bank in pair.banks:
        rs = [r for r in reactions if r.bank == bank]
        abs_moves = [abs(r.reaction_pct) for r in rs]
        mean_abs = _mean(abs_moves)
        signed = [r for r in rs if r.followed is not None]
        corr = None
        strengths = [
            (_signal(r.surprise_bps, r.hawkish_score)[1], r.reaction_pct)
            for r in rs
            if r.expected_sign != 0
        ]
        pairs_ = [(st * expected_sign(pair, bank), rc) for st, rc in strengths if st is not None]
        if len(pairs_) >= MIN_CORRELATION_N:
            x, y = np.array([p[0] for p in pairs_]), np.array([p[1] for p in pairs_])
            if x.std() > 0 and y.std() > 0:
                corr = round(float(np.corrcoef(x, y)[0, 1]), 3)
        summaries.append(
            BankReactionSummary(
                bank=bank,
                n=len(rs),
                mean_abs_reaction_pct=mean_abs,
                normal_abs_move_pct=normal_move,
                reaction_ratio=round(mean_abs / normal_move, 2)
                if mean_abs is not None and normal_move
                else None,
                mean_run_up_pct=_mean([r.run_up_pct for r in rs if r.run_up_pct is not None]),
                mean_follow_pct=_mean([r.follow_pct for r in rs if r.follow_pct is not None]),
                n_signed=len(signed),
                consistency=round(sum(r.followed for r in signed) / len(signed), 3)
                if signed
                else None,
                correlation=corr,
            )
        )
    return summaries, reactions


def load_study(
    session: Session, pair: PairSpec, as_of: dt.date, lookback_days: int = LOOKBACK_DAYS
) -> tuple[list[BankReactionSummary], list[MeetingReaction]]:
    rates = load_rates(session, pair.id, end=as_of)
    meetings = load_meetings(session)
    rows = session.scalars(
        select(CbEvent).where(
            CbEvent.bank.in_(list(pair.banks)),
            CbEvent.date > as_of - dt.timedelta(days=lookback_days + 7),
            CbEvent.date <= as_of,
        )
    ).all()
    events = {(e.bank, e.date): e for e in rows}
    return study(pair, rates, meetings, events, as_of, lookback_days)


def as_dicts(
    summaries: list[BankReactionSummary], reactions: list[MeetingReaction]
) -> tuple[list[dict], list[dict]]:
    return [asdict(s) for s in summaries], [
        {**asdict(r), "date": r.date.isoformat()} for r in reactions
    ]

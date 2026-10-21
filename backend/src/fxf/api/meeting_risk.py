"""Meeting risk for the decision panel: for each meeting inside a horizon, what last year's
data says about it, in one plain sentence. Deterministic numbers from the meeting study
(fxf.events.study) and the around-meetings backtest (windows "evt_*"), not AI text.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxf.api import convert
from fxf.api.schemas import MeetingRiskOut
from fxf.constants import PairSpec
from fxf.events.study import load_study
from fxf.models import BacktestMetric, Forecast

BANK_NAME = {"FED": "Fed", "ECB": "ECB", "CBA": "CBA"}
SPAN = {1: "1-day", 5: "1-week", 21: "1-month"}
HIGHER_RATIO = 1.25  # mean meeting move at least this many normal days: a bigger swing
LOWER_RATIO = 0.85
COVERAGE_FLOOR = 0.75  # the 80% range's target band is 75 to 85%


def _level(ratio: float | None, cov: float | None) -> str:
    if (ratio is not None and ratio >= HIGHER_RATIO) or (cov is not None and cov < COVERAGE_FLOOR):
        return "higher"
    if ratio is not None and ratio < LOWER_RATIO:
        return "lower"
    return "normal"


def _summary(
    pair: PairSpec,
    bank: str,
    day: dt.date,
    h: int,
    ratio: float | None,
    n: int,
    cov: float | None,
    level: str,
) -> str:
    name = BANK_NAME.get(bank, bank)
    pair_name = f"{pair.base}/{pair.quote}"
    text = f"{name} meets {day.day} {day:%b}."
    facts = []
    if ratio is not None and n:
        if ratio >= HIGHER_RATIO:
            facts.append(
                f"{name} days moved {pair_name} {ratio:.1f}x a normal day over the last {n} meetings"
            )
        elif ratio < LOWER_RATIO:
            facts.append(
                f"{name} days moved {pair_name} less than a normal day over the last {n} meetings"
            )
        else:
            facts.append(
                f"{name} days moved {pair_name} about as much as a normal day over the last {n} meetings"
            )
    if cov is not None:
        facts.append(
            f"on {name} weeks the {SPAN.get(h, f'{h}-day')} 80% range held {cov:.0%} of outcomes"
        )
    if facts:
        text += " " + ", and ".join(facts)[0].upper() + ", and ".join(facts)[1:] + "."
    if level == "higher":
        text += " Expect a wider swing than the range shows."
    elif level == "lower":
        text += " This meeting has not moved the pair much."
    return text


def meeting_risks(
    session: Session, pair: PairSpec, rows: dict[int, Forecast]
) -> dict[int, list[MeetingRiskOut]]:
    if not rows or not any(r.meetings_in_horizon for r in rows.values()):
        return {}
    first = rows[min(rows)]
    spot_date = convert.iso_date((first.features_json or {}).get("spot_date")) or first.run_date
    summaries, _ = load_study(session, pair, spot_date)
    by_bank = {s.bank: s for s in summaries}
    run_date = session.scalar(
        select(func.max(BacktestMetric.run_date)).where(BacktestMetric.pair == pair.id)
    )
    evt: dict[tuple[int, str, str], BacktestMetric] = {}
    if run_date is not None:
        for m in session.scalars(
            select(BacktestMetric).where(
                BacktestMetric.pair == pair.id,
                BacktestMetric.run_date == run_date,
                BacktestMetric.window.like("evt_%"),
            )
        ):
            evt[(m.horizon_days, m.model, m.window)] = m

    out: dict[int, list[MeetingRiskOut]] = {}
    for h, row in rows.items():
        risks = []
        for ref in convert.meetings(row.meetings_in_horizon):
            s = by_bank.get(ref.bank)
            ratio = s.reaction_ratio if s else None
            n = s.n if s else 0
            meet = evt.get((h, row.model, f"evt_{ref.bank}"))
            other = evt.get((h, row.model, "evt_none"))
            cov = meet.cov80 if meet else None
            level = _level(ratio, cov)
            risks.append(
                MeetingRiskOut(
                    bank=ref.bank,
                    date=ref.date,
                    reaction_vs_normal=ratio,
                    meetings_last_year=n,
                    band80_meeting_weeks=cov,
                    band80_other_weeks=other.cov80 if other else None,
                    n_meeting_weeks=meet.n_obs if meet else None,
                    level=level,
                    summary=_summary(pair, ref.bank, ref.date, h, ratio, n, cov, level),
                )
            )
        out[h] = sorted(risks, key=lambda r: r.date)
    return out

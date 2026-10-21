"""Meeting reaction study: run-up, reaction and follow-through around meetings, from daily fixes."""

import math
from decimal import Decimal

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from fxf.api.main import create_app
from fxf.constants import EURAMD, EURUSD, USDAMD
from fxf.events.study import expected_sign, study
from fxf.models import CbEvent, CbMeeting, Rate, utcnow

DAYS = pd.bdate_range("2026-01-01", periods=40)


def series(jump_on: int, jump: float) -> pd.Series:
    """A flat 1.10 rate with one move of `jump` (fraction) into fix `jump_on`."""
    values = [1.10] * len(DAYS)
    for i in range(jump_on, len(DAYS)):
        values[i] = 1.10 * (1 + jump)
    return pd.Series(values, index=DAYS)


def meetings(*rows):
    return pd.DataFrame(
        {
            "bank": [b for b, _ in rows],
            "date": pd.to_datetime([d for _, d in rows]),
            "scheduled": True,
        }
    )


def test_expected_sign_follows_the_banks_currency():
    assert expected_sign(EURUSD, "ECB") == 1  # hawkish ECB lifts EUR, the base
    assert expected_sign(EURUSD, "FED") == -1  # hawkish Fed lifts USD, the quote
    assert expected_sign(USDAMD, "CBA") == -1
    assert expected_sign(EURAMD, "FED") == 0  # neither currency is the dollar


def test_reaction_runs_from_the_meeting_day_fix_to_the_next_fix():
    meeting_day = DAYS[20]
    rates = series(21, -0.01)  # EUR/USD falls 1% into the first fix after the FOMC
    ev = CbEvent(
        bank="FED",
        date=meeting_day.date(),
        rate_type="target_mid",
        surprise_bps=10.0,
        hawkish_score=0.5,
    )
    summaries, reactions = study(
        EURUSD,
        rates,
        meetings(("FED", meeting_day)),
        {("FED", meeting_day.date()): ev},
        DAYS[-1].date(),
    )
    r = reactions[0]
    assert r.reaction_pct == pytest.approx(math.log(0.99) * 100, abs=1e-3)
    assert r.run_up_pct == 0.0 and r.follow_pct == 0.0
    assert (r.signal, r.expected_sign, r.followed) == (1, -1, True)  # hawkish Fed, EUR/USD down
    fed = next(s for s in summaries if s.bank == "FED")
    assert fed.n == 1 and fed.consistency == 1.0 and fed.normal_abs_move_pct == 0.0


def test_tone_is_the_signal_when_there_was_no_rate_surprise():
    meeting_day = DAYS[20]
    ev = CbEvent(
        bank="ECB",
        date=meeting_day.date(),
        rate_type="deposit",
        surprise_bps=0.0,
        hawkish_score=-0.6,
    )
    _, reactions = study(
        EURUSD,
        series(21, 0.004),
        meetings(("ECB", meeting_day)),
        {("ECB", meeting_day.date()): ev},
        DAYS[-1].date(),
    )
    assert (reactions[0].signal, reactions[0].followed) == (
        -1,
        False,
    )  # dovish ECB, yet EUR/USD rose


def test_a_meeting_whose_next_fix_is_not_known_yet_is_left_out():
    last = DAYS[-1]
    summaries, reactions = study(
        EURUSD, series(30, 0.002), meetings(("FED", last)), {}, last.date()
    )
    assert reactions == [] and next(s for s in summaries if s.bank == "FED").n == 0


def test_meeting_study_endpoint(session):
    for i, d in enumerate(DAYS):
        session.add(
            Rate(
                pair="EURUSD",
                date=d.date(),
                rate=Decimal(str(1.10 + (0.01 if i > 20 else 0))),
                source="t",
                fetched_at=utcnow(),
            )
        )
    session.add(CbMeeting(bank="FED", date=DAYS[20].date(), scheduled=True))
    session.add(
        CbEvent(bank="FED", date=DAYS[20].date(), rate_type="target_mid", surprise_bps=-20.0)
    )
    session.commit()
    body = TestClient(create_app(frontend_dist=None)).get("/api/meetings/EURUSD").json()
    assert body["pair"] == "EURUSD" and body["window_days"] == 5
    assert [b["bank"] for b in body["banks"]] == ["FED", "ECB"]
    m = body["meetings"][0]
    assert (m["bank"], m["signal"], m["expected_sign"], m["followed"]) == ("FED", -1, -1, True)
    assert m["reaction_pct"] > 0.8

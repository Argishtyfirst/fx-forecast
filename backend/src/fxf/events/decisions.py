"""Decision events (table cb_events, FR-05) shared by the Fed, ECB and CBA readers.

One row per (bank, decision date). The headline rate is constants.BANK_POLICY_RATE:
FED target-range midpoint, ECB deposit facility rate, CBA refinancing rate. rates_json holds
every rate of the decision as {name: {"before": x, "after": y}}:
FED upper/lower/mid, ECB deposit/mro/mlf, CBA refinancing/lombard/deposit (percent).

surprise_bps = (rate_after - expected) * 100. expected is the Atlanta Fed market-implied
midpoint for the Fed when available, otherwise the previous rate ("previous_rate").
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.postgresql import insert

from fxf.constants import BANK_POLICY_RATE
from fxf.db import session_scope
from fxf.events.text import statement_diff
from fxf.models import CbEvent

# rates_json key of the headline rate per bank.
HEADLINE_KEY: Final[dict[str, str]] = {"FED": "mid", "ECB": "deposit", "CBA": "refinancing"}
EXPECTED_PREVIOUS: Final = "previous_rate"
EXPECTED_ATLFED: Final = "atlanta_fed_mpt"


@dataclass
class Decision:
    bank: str
    date: dt.date
    before: dict[str, float | None]
    after: dict[str, float | None]
    expected: float | None = None
    expected_source: str | None = None
    source: str | None = None
    published_at: dt.datetime | None = None
    statement_url: str | None = None
    statement_text: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def rate_before(self) -> float | None:
        return self.before.get(HEADLINE_KEY[self.bank])

    @property
    def rate_after(self) -> float | None:
        return self.after.get(HEADLINE_KEY[self.bank])


def surprise_bps(rate_after: float | None, expected: float | None) -> float | None:
    """(actual - expected) in basis points, rounded to 0.01 bp; None if either is missing."""
    if rate_after is None or expected is None:
        return None
    return round((float(rate_after) - float(expected)) * 100.0, 2)


def _num(v: float | None) -> Decimal | None:
    return None if v is None else Decimal(str(round(float(v), 8)))


def rates_json(before: dict[str, float | None], after: dict[str, float | None]) -> dict[str, Any]:
    keys = list(dict.fromkeys([*after.keys(), *before.keys()]))
    return {k: {"before": before.get(k), "after": after.get(k)} for k in keys}


def event_row(d: Decision) -> dict[str, Any]:
    expected = d.expected
    expected_source = d.expected_source
    if expected is None and d.rate_before is not None:
        expected, expected_source = d.rate_before, EXPECTED_PREVIOUS
    row: dict[str, Any] = {
        "bank": d.bank,
        "date": d.date,
        "rate_type": BANK_POLICY_RATE[d.bank],
        "rate_before": _num(d.rate_before),
        "rate_after": _num(d.rate_after),
        "expected": _num(expected),
        "expected_source": expected_source if expected is not None else None,
        "surprise_bps": surprise_bps(d.rate_after, expected),
        "rates_json": rates_json(d.before, d.after),
        "source": d.source,
        "published_at": d.published_at,
    }
    if d.statement_url is not None:
        row["statement_url"] = d.statement_url
    if d.statement_text is not None:
        row["statement_text"] = d.statement_text
    return row


RATE_COLUMNS: Final = (
    "rate_type",
    "rate_before",
    "rate_after",
    "expected",
    "expected_source",
    "surprise_bps",
    "rates_json",
)


def upsert_events(
    engine: Engine | None,
    decisions: list[Decision],
    *,
    keep_existing_source: bool = False,
    created_at: dt.datetime | None = None,
) -> int:
    """Insert or update events on (bank, date).

    Rate columns are always refreshed. source / published_at are only overwritten when
    keep_existing_source is False (live detection); history backfills keep what live
    detection recorded. Statement columns are written only when the decision carries them.
    created_at (live detection) records when the event was first detected (FR-05).
    """
    if not decisions:
        return 0
    n = 0
    with session_scope(engine) as s:
        for d in decisions:
            row = event_row(d)
            if created_at is not None:
                row["created_at"] = (
                    created_at  # insert only; an update keeps the first detection time
                )
            stmt = insert(CbEvent.__table__).values(**row)
            update = {c: stmt.excluded[c] for c in RATE_COLUMNS}
            for c in ("statement_url", "statement_text"):
                if c in row:
                    update[c] = stmt.excluded[c]
            if keep_existing_source:
                update["source"] = func.coalesce(CbEvent.__table__.c.source, stmt.excluded.source)
                update["published_at"] = func.coalesce(
                    CbEvent.__table__.c.published_at, stmt.excluded.published_at
                )
            else:
                update["source"] = stmt.excluded.source
                update["published_at"] = stmt.excluded.published_at
            s.execute(stmt.on_conflict_do_update(index_elements=["bank", "date"], set_=update))
            n += 1
    return n


def set_statement(
    engine: Engine | None, bank: str, date: dt.date, url: str | None, text: str
) -> bool:
    """Store a statement on an existing event. Returns False if the event does not exist."""
    with session_scope(engine) as s:
        ev = s.scalars(select(CbEvent).where(CbEvent.bank == bank, CbEvent.date == date)).first()
        if ev is None:
            return False
        if ev.statement_text != text:
            ev.statement_text = text
            # A changed text invalidates the score.
            ev.hawkish_score = None
            ev.hawkish_reason = None
            ev.scorer_version = None
        if url:
            ev.statement_url = url
        return True


def refresh_diffs(engine: Engine | None, bank: str | None = None) -> int:
    """Recompute statement_diff for every event with text, against the previous statement
    of the same bank (FR-06). Returns the number of diffs that changed."""
    changed = 0
    with session_scope(engine) as s:
        q = (
            select(CbEvent)
            .where(CbEvent.statement_text.is_not(None))
            .order_by(CbEvent.bank, CbEvent.date)
        )
        if bank:
            q = q.where(CbEvent.bank == bank)
        prev: dict[str, CbEvent] = {}
        for ev in s.scalars(q):
            p = prev.get(ev.bank)
            diff = statement_diff(
                p.statement_text if p else None, ev.statement_text or "", p.id if p else None
            )
            if ev.statement_diff != diff:
                ev.statement_diff = diff
                if ev.hawkish_score is not None:
                    # The scorer reads the diff, so a new diff needs a new score.
                    ev.hawkish_score = None
                    ev.hawkish_reason = None
                    ev.scorer_version = None
                changed += 1
            prev[ev.bank] = ev
    return changed


def stored_events(engine: Engine | None, bank: str) -> list[CbEvent]:
    with session_scope(engine) as s:
        return list(s.scalars(select(CbEvent).where(CbEvent.bank == bank).order_by(CbEvent.date)))


def latest_event(engine: Engine | None, bank: str, before: dt.date | None = None) -> CbEvent | None:
    with session_scope(engine) as s:
        q = select(CbEvent).where(CbEvent.bank == bank)
        if before is not None:
            q = q.where(CbEvent.date < before)
        return s.scalars(q.order_by(CbEvent.date.desc()).limit(1)).first()

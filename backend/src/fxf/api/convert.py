"""Defensive conversion of stored values (NUMERIC columns, JSONB) into response fields.

JSONB written by other jobs may miss keys or hold unexpected types; these helpers turn
anything unusable into None instead of failing the request.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from fxf.api.schemas import MeetingRef


def num(value: Any) -> float | None:
    """A finite float, or None. Booleans are not numbers here."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal | str):
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        return f if math.isfinite(f) else None
    return None


def integer(value: Any) -> int | None:
    f = num(value)
    return None if f is None else int(round(f))


def text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def num_map(value: Any, keys: Iterable[str] = ()) -> dict[str, float | None]:
    """{key: float | None}. Each of `keys` is present, None when missing."""
    out: dict[str, float | None] = {k: None for k in keys}
    if isinstance(value, Mapping):
        out.update({str(k): num(v) for k, v in value.items()})
    return out


def int_map(value: Any, keys: Iterable[str] = ()) -> dict[str, int | None]:
    out: dict[str, int | None] = {k: None for k in keys}
    if isinstance(value, Mapping):
        out.update({str(k): integer(v) for k, v in value.items()})
    return out


def iso_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def meetings(value: Any) -> list[MeetingRef]:
    """forecasts.meetings_in_horizon -> [MeetingRef] sorted by date; malformed items are skipped."""
    out: list[MeetingRef] = []
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, Mapping):
                continue
            try:
                out.append(MeetingRef(bank=item.get("bank"), date=item.get("date")))
            except ValidationError:
                continue
    return sorted(out, key=lambda m: (m.date, m.bank))

"""Request dependencies: a read-only DB session, the clock, and path/query validation.

Tests override `get_now` through `app.dependency_overrides` to freeze time.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Path
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session

from fxf.config import get_settings
from fxf.constants import PAIRS, PairSpec
from fxf.db import get_engine, make_sessionmaker
from fxf.models import utcnow


def get_session() -> Iterator[Session]:
    """One session per request, in a READ ONLY transaction (the API never writes)."""
    engine = get_engine().execution_options(postgresql_readonly=True)
    session = make_sessionmaker(engine)()
    try:
        yield session
    finally:
        session.close()


def get_now() -> dt.datetime:
    """The current time, tz-aware UTC."""
    return utcnow()


def get_today(now: Annotated[dt.datetime, Depends(get_now)]) -> dt.date:
    """Today's date in the market timezone (Europe/Berlin by default)."""
    return now.astimezone(ZoneInfo(get_settings().market_tz)).date()


def get_pair(pair: str = Path(description="Pair id, e.g. EURUSD or USDAMD")) -> PairSpec:
    spec = PAIRS.get(pair.upper())
    if spec is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown pair {pair!r}; supported pairs: {', '.join(PAIRS)}",
        )
    return spec


def invalid_query(name: str, value: Any, msg: str) -> RequestValidationError:
    """A 422 in FastAPI's standard validation error format."""
    return RequestValidationError(
        [{"type": "value_error", "loc": ("query", name), "msg": msg, "input": value}]
    )

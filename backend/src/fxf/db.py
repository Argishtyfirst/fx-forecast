"""Engine and session helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from fxf.config import get_settings, normalize_database_url


@lru_cache
def get_engine(url: str | None = None) -> Engine:
    # prepare_threshold=None: no server-side prepared statements, which a transaction-mode
    # connection pooler (Neon's pooled DATABASE_URL) cannot keep across transactions.
    return create_engine(
        normalize_database_url(url) if url else get_settings().database_url,
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=2,
        connect_args={"prepare_threshold": None},
        future=True,
    )


def make_sessionmaker(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine or get_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on error."""
    session = make_sessionmaker(engine)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

"""Shared fixtures.

Each pytest session creates its own throwaway Postgres database (fxf_test_<random>) from
TEST_DATABASE_URL, so parallel test runs never collide. Tests that use `engine` or
`session` are skipped when Postgres is not reachable (docker compose up -d db).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from fxf import alerts
from fxf.models import Base

FIXTURES = Path(__file__).parent / "fixtures"
ADMIN_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://fxf:fxf@localhost:5433/postgres"
)


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    name = f"fxf_test_{uuid.uuid4().hex[:10]}"
    try:
        admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as c:
            c.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres not reachable at {ADMIN_URL}: {exc}")
    url = make_url(ADMIN_URL).set(database=name)
    eng = create_engine(url, future=True)
    Base.metadata.create_all(eng)
    # Code under test that calls fxf.db.get_engine() without arguments must hit this DB.
    from fxf import db as fxf_db

    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    from fxf.config import get_settings

    get_settings.cache_clear()
    fxf_db.get_engine.cache_clear()
    try:
        yield eng
    finally:
        eng.dispose()
        fxf_db.get_engine.cache_clear()
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def clean_db(engine: Engine) -> Iterator[Engine]:
    """The session database, emptied after the test."""
    yield engine
    with engine.begin() as c:
        names = ", ".join(t.name for t in Base.metadata.sorted_tables)
        c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def session(clean_db: Engine) -> Iterator[Session]:
    s = Session(bind=clean_db, expire_on_commit=False, future=True)
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _capture_alerts(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, str]]]:
    """Never send real alerts from tests."""
    sent: list[dict[str, str]] = []
    monkeypatch.setattr(alerts, "SENT", sent)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SMTP_URL", raising=False)
    yield sent


@pytest.fixture(autouse=True)
def _raw_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FXF_RAW_DIR", str(tmp_path / "raw"))
    from fxf.config import get_settings

    get_settings.cache_clear()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("FXF_LIVE_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="live network test; set FXF_LIVE_TESTS=1")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)

"""Shared HTTP layer: retries with backoff, raw store, schema check."""

import datetime as dt
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import BaseModel

from fxf import http
from fxf.config import get_settings


class Body(BaseModel):
    rate: float


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    delays: list[float] = []
    monkeypatch.setattr(http, "sleep", delays.append)
    return delays


@respx.mock
def test_retries_three_times_with_exponential_backoff(no_sleep):
    route = respx.get("https://x.test/r").mock(
        side_effect=[httpx.Response(503)] * 3 + [httpx.Response(200, json={"rate": 1.5})]
    )
    assert http.fetch_json("src", "https://x.test/r", Body).rate == 1.5
    assert route.call_count == 4
    assert no_sleep == [1.0, 2.0, 4.0]


@respx.mock
def test_gives_up_after_retries():
    respx.get("https://x.test/r").mock(return_value=httpx.Response(500))
    with pytest.raises(http.SourceError, match="failed after 4 attempts"):
        http.fetch("src", "https://x.test/r")


@respx.mock
def test_unknown_shape_raises_schema_error():
    respx.get("https://x.test/r").mock(return_value=httpx.Response(200, json={"unexpected": 1}))
    with pytest.raises(http.SchemaError):
        http.fetch_json("src", "https://x.test/r", Body)


@respx.mock
def test_raw_response_is_stored_and_pruned_after_30_days():
    respx.get("https://x.test/r").mock(return_value=httpx.Response(200, json={"rate": 1.0}))
    http.fetch_json("src", "https://x.test/r", Body)
    root = Path(get_settings().fxf_raw_dir)
    assert len(list(root.glob("src/*/*.json.gz"))) == 1
    later = dt.datetime.now(dt.UTC) + dt.timedelta(days=31)
    assert http.prune_raw(now=later) == 1
    assert not list(root.glob("src/*/*.gz"))


@respx.mock
def test_retry_after_header_is_honoured_and_capped(no_sleep):
    respx.get("https://x.test/r").mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "30"}),
            httpx.Response(503, headers={"retry-after": "9999"}),
            httpx.Response(200, json={"rate": 1.0}),
        ]
    )
    assert http.fetch_json("src", "https://x.test/r", Body, retries=3, backoff_base_s=5).rate == 1.0
    assert no_sleep == [30.0, http.MAX_RETRY_AFTER_S]

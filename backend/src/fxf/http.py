"""Shared HTTP layer for every source (spec: Ingestion rules).

- Each request retries 3 times with exponential backoff (1s, 2s, 4s by default).
- Each raw response is stored for 30 days under FXF_RAW_DIR/<source>/<YYYY-MM-DD>/.
- `fetch_json` validates the body against a pydantic model or TypeAdapter; an unknown
  shape raises SchemaError, which fails the job (and the job sends the alert).

    rows = fetch_json("frankfurter_ecb", url, TypeAdapter(list[FrankfurterRate]), params=...)
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import shutil
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from fxf.config import get_settings
from fxf.logging_setup import get_logger

log = get_logger(__name__)

# Patched to a no-op in tests.
sleep = time.sleep


class SourceError(RuntimeError):
    """A source could not be fetched after all retries."""


class SchemaError(SourceError):
    """A source answered with a shape we do not recognise."""


def _client() -> httpx.Client:
    s = get_settings()
    return httpx.Client(
        timeout=s.http_timeout_s,
        follow_redirects=True,
        headers={"User-Agent": s.user_agent},
    )


def fetch(
    source: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    ext: str = "txt",
    method: str = "GET",
    json: Any = None,
    retries: int | None = None,
    backoff_base_s: float | None = None,
) -> httpx.Response:
    """Request with retries (GET unless a POST body is given). Retries transport errors,
    429 and 5xx, waiting backoff_base_s * 2**i, or the server's Retry-After when it is longer
    (capped at MAX_RETRY_AFTER_S). Stores the raw response body; put credentials in headers,
    never the URL. `retries` and `backoff_base_s` override the settings for slow, rate-limited
    APIs such as Gemini's free tier."""
    s = get_settings()
    attempts = 1 + (s.http_retries if retries is None else retries)
    base = s.http_backoff_base_s if backoff_base_s is None else backoff_base_s
    last_exc: Exception | None = None
    retry_after = 0.0
    with _client() as client:
        for i in range(attempts):
            try:
                resp = client.request(method, url, params=params, headers=headers, json=json)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                store_raw(source, str(resp.request.url), resp.content, ext)
                return resp
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                code = exc.response.status_code
                if code != 429 and code < 500:
                    raise SourceError(f"{source}: HTTP {code} for {url}") from exc
                retry_after = _retry_after(exc.response)
            except httpx.TransportError as exc:
                last_exc = exc
                retry_after = 0.0
            if i < attempts - 1:
                delay = max(base * (2**i), retry_after)
                log.warning(
                    "retrying request",
                    extra={"source": source, "url": url, "attempt": i + 1, "delay_s": delay},
                )
                sleep(delay)
    detail = ""
    if isinstance(last_exc, httpx.HTTPStatusError):
        body = " ".join(last_exc.response.text.split())[:240]
        detail = f" ({body})" if body else ""
    raise SourceError(
        f"{source}: failed after {attempts} attempts: {last_exc}{detail}"
    ) from last_exc


def post_json[T](
    source: str,
    url: str,
    body: Any,
    schema: type[BaseModel] | TypeAdapter[T],
    *,
    headers: dict[str, str] | None = None,
    retries: int | None = None,
    backoff_base_s: float | None = None,
) -> Any:
    """POST a JSON body and validate the JSON response (SchemaError on an unknown shape)."""
    return fetch_json(
        source,
        url,
        schema,
        method="POST",
        json=body,
        headers=headers,
        retries=retries,
        backoff_base_s=backoff_base_s,
    )


MAX_RETRY_AFTER_S = 120.0


def _retry_after(resp: httpx.Response) -> float:
    """Seconds from a Retry-After header (numeric form), capped; 0 when absent."""
    try:
        return min(max(float(resp.headers.get("retry-after", 0)), 0.0), MAX_RETRY_AFTER_S)
    except ValueError:
        return 0.0


def fetch_text(source: str, url: str, **kw: Any) -> str:
    kw.setdefault("ext", "html")
    return fetch(source, url, **kw).text


def fetch_json[T](
    source: str, url: str, schema: type[BaseModel] | TypeAdapter[T], **kw: Any
) -> Any:
    kw.setdefault("ext", "json")
    resp = fetch(source, url, **kw)
    try:
        payload = resp.json()
    except ValueError as exc:
        raise SchemaError(f"{source}: response is not JSON ({url})") from exc
    return validate(source, payload, schema)


def validate[T](source: str, payload: Any, schema: type[BaseModel] | TypeAdapter[T]) -> Any:
    try:
        if isinstance(schema, TypeAdapter):
            return schema.validate_python(payload)
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise SchemaError(f"{source}: unknown response shape: {exc.errors()[:3]}") from exc


# --- raw response store --------------------------------------------------------------


def store_raw(source: str, url: str, content: bytes, ext: str = "txt") -> Path:
    s = get_settings()
    now = dt.datetime.now(dt.UTC)
    folder = Path(s.fxf_raw_dir) / source / now.date().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode() + content).hexdigest()[:8]
    path = folder / f"{now:%H%M%S}-{digest}.{ext}.gz"
    with gzip.open(path, "wb") as fh:
        fh.write(content)
    return path


def prune_raw(now: dt.datetime | None = None) -> int:
    """Delete raw responses older than raw_retention_days. Returns the number of day folders removed."""
    s = get_settings()
    root = Path(s.fxf_raw_dir)
    if not root.exists():
        return 0
    today = (now or dt.datetime.now(dt.UTC)).date()
    cutoff = today - dt.timedelta(days=s.raw_retention_days)
    removed = 0
    for day_dir in root.glob("*/*"):
        try:
            day = dt.date.fromisoformat(day_dir.name)
        except ValueError:
            continue
        if day < cutoff:
            shutil.rmtree(day_dir, ignore_errors=True)
            removed += 1
    return removed

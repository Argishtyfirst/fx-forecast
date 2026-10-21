"""Job bookkeeping. Every scheduled job runs inside `job_run`, which writes one job_runs row.

    with job_run("frankfurter_ecb") as run:
        with session_scope() as s:
            run.rows_written += upsert(s, Rate, rows, ["pair", "date"])

On an exception the row is marked failed, an alert is sent, and the exception is
re-raised. `run_job` is the non-raising variant used by the daily pipeline, so one
failed source does not stop the others (NFR-04: the last good forecast stays visible).
The job_runs row is written through its own session, so a failed job transaction
never loses its failed status.
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine

from fxf.alerts import send_alert
from fxf.db import session_scope
from fxf.logging_setup import get_logger
from fxf.models import JobRun, utcnow

log = get_logger(__name__)


@dataclass
class RunContext:
    job: str
    run_id: int
    rows_written: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


@contextmanager
def job_run(
    job: str, engine: Engine | None = None, meta: dict[str, Any] | None = None
) -> Iterator[RunContext]:
    started = utcnow()
    t0 = time.monotonic()
    with session_scope(engine) as s:
        row = JobRun(job=job, started_at=started, status="running", rows_written=0, meta=meta)
        s.add(row)
        s.flush()
        run_id = row.id
    ctx = RunContext(job=job, run_id=run_id, meta=dict(meta or {}))
    log.info("job started", extra={"job": job, "run_id": run_id})
    try:
        yield ctx
    except Exception as exc:
        duration = time.monotonic() - t0
        err = f"{type(exc).__name__}: {exc}"
        with session_scope(engine) as s:
            r = s.get(JobRun, run_id)
            assert r is not None
            r.status = "failed"
            r.finished_at = utcnow()
            r.duration_s = duration
            r.rows_written = ctx.rows_written
            r.error = (err + "\n" + traceback.format_exc())[:8000]
            r.meta = ctx.meta or None
        log.error(
            "job failed",
            extra={"job": job, "run_id": run_id, "duration_s": round(duration, 3), "error": err},
        )
        send_alert(f"Job failed: {job}", err)
        raise
    duration = time.monotonic() - t0
    with session_scope(engine) as s:
        r = s.get(JobRun, run_id)
        assert r is not None
        r.status = "success"
        r.finished_at = utcnow()
        r.duration_s = duration
        r.rows_written = ctx.rows_written
        r.meta = ctx.meta or None
    log.info(
        "job finished",
        extra={
            "job": job,
            "run_id": run_id,
            "status": "success",
            "duration_s": round(duration, 3),
            "rows_written": ctx.rows_written,
        },
    )


def run_job(
    job: str,
    fn: Callable[[RunContext], None],
    engine: Engine | None = None,
    meta: dict[str, Any] | None = None,
) -> bool:
    """Run fn inside job_run. Returns True on success, False on failure (never raises)."""
    try:
        with job_run(job, engine=engine, meta=meta) as ctx:
            fn(ctx)
        return True
    except Exception:
        return False

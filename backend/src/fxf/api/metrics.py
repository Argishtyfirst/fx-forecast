"""Prometheus text exposition of job metrics (NFR-05), served at GET /api/metrics.

Duration, rows and status come from each job's last finished run (success or failure),
since a running job has neither. A job with no such run has no samples.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from fxf.api.health import PIPELINE_JOBS, JobSnapshot, load_snapshots, source_status
from fxf.api.schemas import SourceStatus
from fxf.constants import SOURCES
from fxf.models import JobRun

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@dataclass(frozen=True)
class JobSample:
    job: str
    duration_s: float | None
    rows_written: int | None
    status: str | None  # of the last finished run: success | failed
    last_success: dt.datetime | None


def escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt(value: float | int) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    return repr(float(value))


def _family(
    name: str, help_text: str, label: str, samples: Iterable[tuple[str, float | int | None]]
) -> list[str]:
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
    for key, value in samples:
        if value is not None:
            lines.append(f'{name}{{{label}="{escape_label(key)}"}} {_fmt(value)}')
    return lines


def render_metrics(jobs: Sequence[JobSample], sources: Sequence[SourceStatus]) -> str:
    lines: list[str] = []
    lines += _family(
        "fxf_job_last_duration_seconds",
        "Duration of the last finished run of the job.",
        "job",
        ((j.job, j.duration_s) for j in jobs),
    )
    lines += _family(
        "fxf_job_last_rows_written",
        "Rows written by the last finished run of the job.",
        "job",
        ((j.job, j.rows_written) for j in jobs),
    )
    lines += _family(
        "fxf_job_last_success_timestamp_seconds",
        "Unix time when the last successful run of the job finished.",
        "job",
        ((j.job, j.last_success.timestamp() if j.last_success else None) for j in jobs),
    )
    lines += _family(
        "fxf_job_last_status",
        "Status of the last finished run of the job (1 = success, 0 = failed).",
        "job",
        ((j.job, None if j.status is None else int(j.status == "success")) for j in jobs),
    )
    lines += _family(
        "fxf_source_stale",
        "1 when the source is stale (latest run failed, never succeeded, or too old).",
        "source",
        ((s.source, int(s.stale)) for s in sources),
    )
    return "\n".join(lines) + "\n"


def _sample(snap: JobSnapshot) -> JobSample:
    run = snap.last_finished
    return JobSample(
        job=snap.job,
        duration_s=run.duration_s if run else None,
        rows_written=run.rows_written if run else None,
        status=run.status if run else None,
        last_success=snap.last_success,
    )


def collect_metrics(session: Session, now: dt.datetime) -> str:
    """Known sources and pipeline jobs, plus any other job name found in job_runs."""
    seen = session.scalars(select(JobRun.job).distinct()).all()
    names = list(dict.fromkeys((*SOURCES, *PIPELINE_JOBS, *sorted(seen))))
    snaps = load_snapshots(session, names)
    return render_metrics(
        [_sample(snaps[n]) for n in names],
        [source_status(snaps[s], now) for s in SOURCES],
    )

"""Source freshness and job status (FR-16, NFR-05), shared by /api/health, /latest and /metrics.

Each ingest job is named after its source key (constants.SOURCES), so the health of a
source is the history of job_runs rows with job == source key.

Stale rule: a source is stale when its latest run failed, when it never succeeded, or
when its last success is older than constants.SOURCE_STALE_HOURS[source].
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from fxf.api.schemas import HealthResponse, JobStatus, SourceStatus
from fxf.constants import (
    JOB_AI,
    JOB_AI_ANALYSIS,
    JOB_BACKTEST,
    JOB_FORECAST,
    JOB_SCORE,
    SOURCE_ATLFED,
    SOURCE_CBA,
    SOURCE_CBA_NEWS,
    SOURCE_ECB,
    SOURCE_ECB_RSS,
    SOURCE_FED_RSS,
    SOURCE_FRANKFURTER_CBA,
    SOURCE_FRANKFURTER_ECB,
    SOURCE_FRED,
    SOURCE_STALE_HOURS,
    SOURCES,
    PairSpec,
)
from fxf.models import JobRun

SOURCE_LABELS: Final[dict[str, str]] = {
    SOURCE_FRANKFURTER_ECB: "ECB reference rate (Frankfurter)",
    SOURCE_FRANKFURTER_CBA: "CBA daily rate (Frankfurter)",
    SOURCE_FRED: "FRED",
    SOURCE_ECB: "ECB Data Portal",
    SOURCE_CBA: "CBA policy rates",
    SOURCE_FED_RSS: "Fed press releases",
    SOURCE_ECB_RSS: "ECB press releases",
    SOURCE_CBA_NEWS: "CBA decisions (cba.am, ARKA, Interfax)",
    SOURCE_ATLFED: "Atlanta Fed Market Probability Tracker",
}

# Policy-rate macro source and decision news source of each bank (plus, for the Fed, the
# market-implied expectation its surprise is measured against).
BANK_SOURCES: Final[dict[str, tuple[str, ...]]] = {
    "FED": (SOURCE_FRED, SOURCE_FED_RSS, SOURCE_ATLFED),
    "ECB": (SOURCE_ECB, SOURCE_ECB_RSS),
    "CBA": (SOURCE_CBA, SOURCE_CBA_NEWS),
}

PIPELINE_JOBS: Final[tuple[str, ...]] = (
    JOB_FORECAST,
    JOB_BACKTEST,
    JOB_SCORE,
    JOB_AI,
    JOB_AI_ANALYSIS,
)
DEFAULT_STALE_HOURS: Final = 96


@dataclass(frozen=True)
class JobSnapshot:
    """What job_runs says about one job."""

    job: str
    latest: JobRun | None  # most recent run, any status
    last_finished: JobRun | None  # most recent success or failure
    last_success: dt.datetime | None  # finished_at of the most recent success


def pair_sources(pair: PairSpec) -> tuple[str, ...]:
    """Sources a pair's forecast depends on: its rate source plus, for each of its banks,
    the policy-rate source and the decision news source. In constants.SOURCES order."""
    wanted = {pair.source}
    for bank in pair.banks:
        wanted.update(BANK_SOURCES.get(bank, ()))
    return tuple(s for s in SOURCES if s in wanted)


def is_stale(
    source: str, last_status: str | None, last_success: dt.datetime | None, now: dt.datetime
) -> bool:
    if last_status == "failed" or last_success is None:
        return True
    limit = dt.timedelta(hours=SOURCE_STALE_HOURS.get(source, DEFAULT_STALE_HOURS))
    return now - last_success > limit


def error_first_line(error: str | None) -> str | None:
    if not error:
        return None
    for line in error.splitlines():
        if line.strip():
            return line.strip()
    return None


def _latest_per_job(session: Session, jobs: list[str], *where, order) -> dict[str, JobRun]:
    q = (
        select(JobRun)
        .ext(distinct_on(JobRun.job))
        .where(JobRun.job.in_(jobs), *where)
        .order_by(JobRun.job, *order, JobRun.id.desc())
    )
    return {r.job: r for r in session.scalars(q)}


def load_snapshots(session: Session, jobs: Iterable[str]) -> dict[str, JobSnapshot]:
    """One JobSnapshot per requested job name (three DISTINCT ON queries in total)."""
    names = list(dict.fromkeys(jobs))
    if not names:
        return {}
    latest = _latest_per_job(session, names, order=(JobRun.started_at.desc(),))
    finished = _latest_per_job(
        session,
        names,
        JobRun.status.in_(("success", "failed")),
        order=(JobRun.started_at.desc(),),
    )
    success = _latest_per_job(
        session,
        names,
        JobRun.status == "success",
        order=(JobRun.finished_at.desc().nulls_last(),),
    )
    return {
        j: JobSnapshot(
            job=j,
            latest=latest.get(j),
            last_finished=finished.get(j),
            last_success=success[j].finished_at if j in success else None,
        )
        for j in names
    }


def _error(run: JobRun | None) -> str | None:
    return error_first_line(run.error) if run is not None and run.status == "failed" else None


def source_status(snap: JobSnapshot, now: dt.datetime) -> SourceStatus:
    status = snap.latest.status if snap.latest else None
    return SourceStatus(
        source=snap.job,
        label=SOURCE_LABELS.get(snap.job, snap.job),
        last_success=snap.last_success,
        last_run=snap.latest.started_at if snap.latest else None,
        last_status=status,
        stale=is_stale(snap.job, status, snap.last_success, now),
        error=_error(snap.latest),
    )


def source_statuses(
    session: Session, now: dt.datetime, sources: Iterable[str] = SOURCES
) -> list[SourceStatus]:
    snaps = load_snapshots(session, sources)
    return [source_status(s, now) for s in snaps.values()]


def stale_sources_for_pair(
    session: Session, pair: PairSpec, now: dt.datetime
) -> list[SourceStatus]:
    """The stale-data warning for a pair's forecast (FR-16)."""
    return [s for s in source_statuses(session, now, pair_sources(pair)) if s.stale]


def job_status(snap: JobSnapshot) -> JobStatus:
    """Status, duration and rows are those of the latest run (None while it is running)."""
    run = snap.latest
    return JobStatus(
        job=snap.job,
        last_success=snap.last_success,
        last_run=run.started_at if run else None,
        last_status=run.status if run else None,
        last_duration_s=run.duration_s if run else None,
        last_rows_written=run.rows_written if run else None,
        error=_error(run),
    )


def build_health(session: Session, now: dt.datetime) -> HealthResponse:
    snaps = load_snapshots(session, (*SOURCES, *PIPELINE_JOBS))
    sources = [source_status(snaps[s], now) for s in SOURCES]
    jobs = [job_status(snaps[j]) for j in PIPELINE_JOBS]
    return HealthResponse(
        status="degraded" if any(s.stale for s in sources) else "ok",
        checked_at=now,
        sources=sources,
        jobs=jobs,
    )

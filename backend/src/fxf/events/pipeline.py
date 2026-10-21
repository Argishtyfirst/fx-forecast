"""Central bank events pipeline entry points.

    run_events()       hourly poll (FR-05): Fed and ECB RSS, CBA news on CBA meeting days, the
                       Atlanta Fed tracker and the CBA rates once a day (hourly on CBA meeting
                       days), the meeting calendars at most once a day, then statement scoring.
    backfill_events()  first run: seed + live calendars, CBA rates, Atlanta Fed tracker,
                       historical decisions, statement texts, diffs, scoring.

    uv run python -m fxf.events.pipeline [--backfill]

Every task runs in fxf.jobs.run_job under its source key (job_runs.meta["task"] tells the
tasks of one source apart), so one failing source never stops the others.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections.abc import Callable

from sqlalchemy import Engine, select

from fxf.constants import (
    JOB_SCORE,
    SOURCE_ATLFED,
    SOURCE_CBA,
    SOURCE_CBA_NEWS,
    SOURCE_ECB_RSS,
    SOURCE_FED_RSS,
)
from fxf.db import get_engine, session_scope
from fxf.events import calendar, live
from fxf.events.scorer import score_statements
from fxf.jobs import RunContext, run_job
from fxf.logging_setup import configure_logging
from fxf.models import JobRun, utcnow

Task = Callable[[RunContext], None]


def _ran_today(engine: Engine | None, job: str, task: str, now: dt.datetime) -> bool:
    """True if job/task succeeded since 00:00 UTC of `now`."""
    start = dt.datetime.combine(now.astimezone(dt.UTC).date(), dt.time(0), tzinfo=dt.UTC)
    with session_scope(engine) as s:
        rows = s.scalars(
            select(JobRun).where(
                JobRun.job == job,
                JobRun.status == "success",
                JobRun.started_at >= start,
                JobRun.started_at <= now + dt.timedelta(minutes=5),
            )
        ).all()
    return any((r.meta or {}).get("task") == task for r in rows)


def _run(engine: Engine | None, job: str, task: str, fn: Task) -> bool:
    return run_job(job, fn, engine=engine, meta={"task": task})


def run_events(engine: Engine | None = None, *, now: dt.datetime | None = None) -> dict[str, bool]:
    """The hourly events poll. Returns {task: success}."""
    engine = engine or get_engine()
    now = now or utcnow()
    out: dict[str, bool] = {}
    out["fed_rss"] = _run(engine, SOURCE_FED_RSS, "rss", lambda c: live.poll_fed(c, engine, now))
    out["ecb_rss"] = _run(engine, SOURCE_ECB_RSS, "rss", lambda c: live.poll_ecb(c, engine, now))
    meeting_day = bool(live.cba_meeting_days(engine, now))
    if meeting_day:
        out["cba_news"] = _run(
            engine, SOURCE_CBA_NEWS, "news", lambda c: live.poll_cba(c, engine, now)
        )
    if meeting_day or not _ran_today(engine, SOURCE_CBA, "rates", now):
        out["cba_rates"] = _run(
            engine, SOURCE_CBA, "rates", lambda c: live.cba_rates(c, engine, now)
        )
    if not _ran_today(engine, SOURCE_ATLFED, "tracker", now):
        out["atlanta_fed"] = _run(
            engine, SOURCE_ATLFED, "tracker", lambda c: live.atlanta_fed(c, engine, now)
        )
    for key, job, fn in (
        ("fed_calendar", SOURCE_FED_RSS, live.refresh_fed_calendar),
        ("ecb_calendar", SOURCE_ECB_RSS, live.refresh_ecb_calendar),
        ("cba_calendar", SOURCE_CBA_NEWS, live.refresh_cba_calendar),
    ):
        if not _ran_today(engine, job, "calendar", now):
            out[key] = _run(engine, job, "calendar", lambda c, fn=fn: fn(c, engine, now))
    out["score_statements"] = _run(
        engine, JOB_SCORE, "score", lambda c: score_statements(c, engine)
    )
    return out


def backfill_events(engine: Engine | None = None) -> dict[str, bool]:
    """Load the full events history. Idempotent: safe to run again."""
    engine = engine or get_engine()
    now = utcnow()
    out: dict[str, bool] = {}
    calendar.load_seed_into_db(engine)
    out["fed_calendar"] = _run(
        engine,
        SOURCE_FED_RSS,
        "calendar",
        lambda c: live.refresh_fed_calendar(c, engine, now, full=True),
    )
    out["ecb_calendar"] = _run(
        engine,
        SOURCE_ECB_RSS,
        "calendar",
        lambda c: live.refresh_ecb_calendar(c, engine, now, full=True),
    )
    out["cba_calendar"] = _run(
        engine, SOURCE_CBA_NEWS, "calendar", lambda c: live.refresh_cba_calendar(c, engine, now)
    )
    out["cba_history"] = _run(
        engine, SOURCE_CBA, "history", lambda c: live.cba_history(c, engine, now)
    )
    out["cba_rates"] = _run(engine, SOURCE_CBA, "rates", lambda c: live.cba_rates(c, engine, now))
    out["atlanta_fed"] = _run(
        engine, SOURCE_ATLFED, "tracker", lambda c: live.atlanta_fed(c, engine, now)
    )
    out["fed_history"] = _run(
        engine, SOURCE_FED_RSS, "history", lambda c: live.fed_history(c, engine, now)
    )
    out["ecb_history"] = _run(
        engine, SOURCE_ECB_RSS, "history", lambda c: live.ecb_history(c, engine, now)
    )
    # The tracker's expectations apply to FED events created after it ran.
    out["atlanta_fed_expected"] = _run(
        engine, SOURCE_ATLFED, "expected", lambda c: _apply_expected(c, engine)
    )
    for bank, job in (("FED", SOURCE_FED_RSS), ("ECB", SOURCE_ECB_RSS), ("CBA", SOURCE_CBA_NEWS)):
        out[f"{bank.lower()}_statements"] = _run(
            engine,
            job,
            "statements",
            lambda c, bank=bank: live.backfill_statements(c, engine, now, bank),
        )
    # Live polls last, so a decision published in the past week gets its RSS timestamp.
    out["fed_rss"] = _run(engine, SOURCE_FED_RSS, "rss", lambda c: live.poll_fed(c, engine, now))
    out["ecb_rss"] = _run(engine, SOURCE_ECB_RSS, "rss", lambda c: live.poll_ecb(c, engine, now))
    out["score_statements"] = _run(
        engine, JOB_SCORE, "score", lambda c: score_statements(c, engine)
    )
    return out


def _apply_expected(ctx: RunContext, engine: Engine | None) -> None:
    from fxf.constants import ATLFED_SERIES

    ctx.rows_written += live.apply_fed_expectations(
        engine, live.macro_series(engine, ATLFED_SERIES)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Central bank events pipeline")
    parser.add_argument("--backfill", action="store_true", help="load the full history first")
    args = parser.parse_args(argv)
    configure_logging()
    result = backfill_events() if args.backfill else run_events()
    print(json.dumps(result, indent=2))
    return 0 if all(result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

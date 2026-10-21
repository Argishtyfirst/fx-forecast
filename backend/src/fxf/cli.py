"""Command line entry point: `uv run fxf <command>`.

Scheduled entry points (no job calls another job directly; each reads and writes Postgres):
    fxf daily    working days after 17:00 CET: ingest -> events -> forecast -> AI view
                 (NFR-01: done by 18:00)
    fxf hourly   central bank RSS / news poll and statement scoring          (FR-05: within 2 hours)
    fxf weekly   walk-forward backtest, then re-run today's forecast so the served model updates
"""

from __future__ import annotations

import datetime as dt
import sys
from typing import Annotated

import typer

from fxf.calendars import CET, is_working_day
from fxf.constants import SOURCE_FRANKFURTER_CBA, SOURCE_FRANKFURTER_ECB
from fxf.logging_setup import configure_logging, get_logger

app = typer.Typer(add_completion=False, no_args_is_help=True, help="FX Forecast Tool")
log = get_logger("fxf.cli")

DAILY_EARLIEST = dt.time(17, 0)


def _date(value: str | None) -> dt.date | None:
    return dt.date.fromisoformat(value) if value else None


def _report(name: str, results: dict[str, bool]) -> bool:
    ok = all(results.values()) if results else True
    for job, success in results.items():
        typer.echo(f"  {'ok  ' if success else 'FAIL'} {job}")
    log.info(f"{name} finished", extra={"results": results, "ok": ok})
    return ok


@app.callback()
def _main() -> None:
    configure_logging()


@app.command("init-db")
def init_db() -> None:
    """Apply database migrations (alembic upgrade head)."""
    from alembic.config import Config

    from alembic import command
    from fxf.config import BACKEND_DIR

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")
    typer.echo("database is at head")


@app.command()
def backfill() -> None:
    """Load full history for every source (first run, FR-02)."""
    from fxf.events.pipeline import backfill_events
    from fxf.ingest.pipeline import backfill as backfill_ingest

    ok = _report("ingest backfill", backfill_ingest())
    ok = _report("events backfill", backfill_events()) and ok
    raise typer.Exit(0 if ok else 1)


@app.command()
def ingest(
    source: Annotated[list[str] | None, typer.Option(help="Limit to these source keys")] = None,
) -> None:
    """Fetch the latest rates and macro series."""
    from fxf.ingest.pipeline import run_ingest

    raise typer.Exit(0 if _report("ingest", run_ingest(sources=source or None)) else 1)


@app.command()
def events(
    backfill: Annotated[bool, typer.Option(help="Load the full event history")] = False,
) -> None:
    """Poll central bank sources (or backfill them)."""
    from fxf.events.pipeline import backfill_events, run_events

    results = backfill_events() if backfill else run_events()
    raise typer.Exit(0 if _report("events", results) else 1)


@app.command()
def forecast(
    date: Annotated[str | None, typer.Option(help="Run date (YYYY-MM-DD), default today")] = None,
) -> None:
    """Produce forecasts for every pair and horizon (FR-08)."""
    from fxf.forecast.engine import run_forecast_job

    raise typer.Exit(0 if run_forecast_job(run_date=_date(date)) else 1)


@app.command()
def backtest(
    date: Annotated[str | None, typer.Option(help="Run date (YYYY-MM-DD), default today")] = None,
) -> None:
    """Run the walk-forward backtest (FR-13)."""
    from fxf.backtest.runner import run_backtest_job

    raise typer.Exit(0 if run_backtest_job(run_date=_date(date)) else 1)


@app.command()
def ai(
    date: Annotated[str | None, typer.Option(help="Run date (YYYY-MM-DD), default latest")] = None,
) -> None:
    """Experimental AI view (Gemini). Off unless GEMINI_API_KEY is set."""
    from fxf.ai.view import run_ai_view_job

    raise typer.Exit(0 if run_ai_view_job(run_date=_date(date)) else 1)


@app.command()
def daily(
    force: Annotated[
        bool, typer.Option(help="Run even outside a working day after 17:00 CET")
    ] = False,
) -> None:
    """The daily pipeline: ingest, events, forecast. Safe to run twice (idempotent)."""
    now = dt.datetime.now(CET)
    if not force:
        if not is_working_day(now.date()):
            typer.echo(f"{now.date()} is not a working day; nothing to do")
            raise typer.Exit(0)
        if now.time() < DAILY_EARLIEST:
            typer.echo(f"it is {now:%H:%M} CET; the daily run starts after 17:00 CET")
            raise typer.Exit(0)

    from fxf.events.pipeline import run_events
    from fxf.forecast.engine import run_forecast_job
    from fxf.ingest.pipeline import run_ingest

    ingest_results = run_ingest()
    _report("ingest", ingest_results)
    _report("events", run_events())
    # Only the exchange rates and the forecast fail the run (and so email the owner). A macro
    # or news source that is down (FRED maintenance, a slow press page) shows as stale on the
    # dashboard instead, and the forecast keeps its last known value or its fallback.
    rates_ok = all(
        ingest_results.get(s, False) for s in (SOURCE_FRANKFURTER_ECB, SOURCE_FRANKFURTER_CBA)
    )
    # Forecast even when a source failed: it uses the last good data, and the API flags
    # the stale source (FR-16). A failed forecast keeps the previous one visible (NFR-04).
    forecast_ok = run_forecast_job(run_date=now.date())
    typer.echo(f"  {'ok  ' if forecast_ok else 'FAIL'} forecast")
    if forecast_ok:
        from fxf.ai.view import run_ai_view_job

        # Experimental and optional: a failure is recorded and alerted, but never fails the
        # pipeline, because the served forecast does not depend on it.
        ai_ok = run_ai_view_job(run_date=now.date())
        typer.echo(f"  {'ok  ' if ai_ok else 'FAIL'} ai view")
    raise typer.Exit(0 if (rates_ok and forecast_ok) else 1)


@app.command()
def hourly() -> None:
    """Hourly central bank poll (FR-05)."""
    from fxf.events.pipeline import run_events

    raise typer.Exit(0 if _report("events", run_events()) else 1)


@app.command()
def weekly() -> None:
    """Weekly backtest, then refresh today's served forecast with the new metrics (FR-11, FR-13)."""
    from fxf.backtest.runner import run_backtest_job
    from fxf.forecast.engine import run_forecast_job

    today = dt.datetime.now(CET).date()
    bt_ok = run_backtest_job(run_date=today)
    typer.echo(f"  {'ok  ' if bt_ok else 'FAIL'} backtest")
    fc_ok = run_forecast_job(run_date=today)
    typer.echo(f"  {'ok  ' if fc_ok else 'FAIL'} forecast")
    raise typer.Exit(0 if (bt_ok and fc_ok) else 1)


@app.command()
def report(
    out: Annotated[str | None, typer.Option(help="Output folder, default docs/reports")] = None,
) -> None:
    """Write the weekly Markdown report (models, AI track record, pipeline health)."""
    from pathlib import Path

    from fxf.config import REPO_DIR
    from fxf.db import session_scope
    from fxf.report import write_report

    with session_scope() as s:
        paths = write_report(s, Path(out) if out else REPO_DIR / "docs" / "reports")
    for path in paths:
        typer.echo(f"  wrote {path}")


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: Annotated[bool, typer.Option()] = False,
) -> None:
    """Serve the API (and the built frontend, if frontend/dist exists)."""
    import uvicorn

    uvicorn.run("fxf.api.main:app", host=host, port=port, reload=reload, log_config=None)


@app.command()
def worker() -> None:
    """Long-running scheduler (APScheduler), the alternative to GitHub Actions cron."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    def call(*args: str) -> None:
        try:
            app(args=list(args), standalone_mode=False)
        except SystemExit:
            pass
        except Exception:
            log.exception("scheduled command failed", extra={"command": args})

    sched = BlockingScheduler(timezone=CET)
    # Two daily attempts: the second catches a late CBA or ECB fix. Both finish before 18:00.
    sched.add_job(call, CronTrigger(day_of_week="mon-fri", hour=17, minute=10), args=["daily"])
    sched.add_job(call, CronTrigger(day_of_week="mon-fri", hour=17, minute=40), args=["daily"])
    sched.add_job(call, CronTrigger(minute=5), args=["hourly"])
    sched.add_job(call, CronTrigger(day_of_week="sat", hour=6, minute=0), args=["weekly"])
    typer.echo("scheduler started (Europe/Berlin)")
    sched.start()


@app.command()
def status(limit: int = 20) -> None:
    """Show the most recent job runs."""
    from sqlalchemy import select

    from fxf.db import session_scope
    from fxf.models import JobRun

    with session_scope() as s:
        rows = s.execute(select(JobRun).order_by(JobRun.id.desc()).limit(limit)).scalars().all()
        for r in rows:
            dur = f"{r.duration_s:.1f}s" if r.duration_s is not None else "-"
            err = (r.error or "").splitlines()[0][:70] if r.error else ""
            typer.echo(
                f"{r.started_at:%Y-%m-%d %H:%M} {r.job:<18} {r.status:<8} {r.rows_written:>7} {dur:>8} {err}"
            )


if __name__ == "__main__":
    sys.exit(app())

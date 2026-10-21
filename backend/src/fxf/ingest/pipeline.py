"""Ingest entry points: the daily run and the one-off full backfill.

Each source runs in its own job (job_runs.job = source key), so /api/health can show
the last success per source and one failing source never stops the others (NFR-04).
A table that is empty for a pair or series is backfilled automatically, so the first
daily run is also the initial load.

    uv run python -m fxf.ingest.pipeline              # daily run
    uv run python -m fxf.ingest.pipeline --backfill   # reload every full history
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections.abc import Callable, Sequence
from functools import partial
from typing import Final

from sqlalchemy import Engine

from fxf.constants import SOURCE_ECB, SOURCE_FRANKFURTER_CBA, SOURCE_FRANKFURTER_ECB, SOURCE_FRED
from fxf.http import prune_raw
from fxf.ingest import ecb, frankfurter, fred
from fxf.ingest.quality import repair_rates
from fxf.jobs import RunContext, run_job
from fxf.logging_setup import configure_logging, get_logger
from fxf.models import utcnow

log = get_logger(__name__)

Runner = Callable[..., None]

# In run order. CBA policy rates and the central bank feeds are separate jobs.
RUNNERS: Final[dict[str, Runner]] = {
    SOURCE_FRANKFURTER_ECB: partial(frankfurter.ingest, SOURCE_FRANKFURTER_ECB),
    SOURCE_FRANKFURTER_CBA: partial(frankfurter.ingest, SOURCE_FRANKFURTER_CBA),
    SOURCE_FRED: fred.ingest,
    SOURCE_ECB: ecb.ingest,
}
INGEST_SOURCES: Final[tuple[str, ...]] = tuple(RUNNERS)


def run_ingest(
    engine: Engine | None = None,
    *,
    now: dt.datetime | None = None,
    sources: Sequence[str] | None = None,
) -> dict[str, bool]:
    """Daily ingest. Returns success per source. `now` (tz-aware) is injectable for tests."""
    return _run(engine, now=now, sources=sources, full=False)


def backfill(engine: Engine | None = None) -> dict[str, bool]:
    """Refetch the full history of every pair and series.

    Rates are upserted, so source corrections anywhere in history are applied. Macro
    rows already stored are kept as they are (no vintages, see fxf.ingest.pit).
    """
    return _run(engine, now=None, sources=None, full=True)


def _run(
    engine: Engine | None,
    *,
    now: dt.datetime | None,
    sources: Sequence[str] | None,
    full: bool,
) -> dict[str, bool]:
    now = now or utcnow()
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    selected = list(sources) if sources is not None else list(INGEST_SOURCES)
    unknown = [s for s in selected if s not in RUNNERS]
    if unknown:
        raise ValueError(f"not an ingest source: {', '.join(unknown)} (known: {INGEST_SOURCES})")

    mode = "backfill" if full else "daily"
    results: dict[str, bool] = {}
    for source in selected:
        runner = RUNNERS[source]

        def job(ctx: RunContext, runner: Runner = runner) -> None:
            runner(ctx, engine=engine, now=now, full=full)

        results[source] = run_job(source, job, engine=engine, meta={"mode": mode})
    try:
        bad = repair_rates(engine)
    except Exception as exc:  # a failed check must not fail the ingest
        log.warning("rate check failed", extra={"error": str(exc)})
    else:
        log.info("rate check finished", extra={"bad_rows_removed": len(bad)})
    try:
        removed = prune_raw()
    except OSError as exc:
        log.warning("raw prune failed", extra={"error": str(exc)})
    else:
        log.info("raw responses pruned", extra={"day_folders_removed": removed})
    log.info("ingest finished", extra={"mode": mode, "results": results})
    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fxf.ingest.pipeline", description=__doc__)
    parser.add_argument("--backfill", action="store_true", help="reload every full history")
    parser.add_argument(
        "--source",
        action="append",
        choices=INGEST_SOURCES,
        help="run only this source (repeatable); daily mode only",
    )
    args = parser.parse_args(argv)
    configure_logging()
    results = backfill() if args.backfill else run_ingest(sources=args.source)
    print(json.dumps(results))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

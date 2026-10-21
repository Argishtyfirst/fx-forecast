"""API acceptance tests (FR-09, FR-12, FR-15, FR-16, NFR-04, NFR-05).

The database is seeded the way the pipeline writes it: job_runs rows from fxf.jobs,
forecast rows with features_json per fxf.forecast.types.FEATURES_JSON_KEYS.
"""

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fxf.api.deps import get_now
from fxf.api.main import create_app
from fxf.constants import HORIZONS, SOURCES
from fxf.models import Forecast, JobRun

pytestmark = pytest.mark.db

NOW = dt.datetime(2026, 10, 21, 17, 0, tzinfo=dt.UTC)
TODAY = dt.date(2026, 10, 21)
YESTERDAY = dt.date(2026, 10, 20)

FEATURES = {
    "spot_date": "2026-10-21",
    "rate_diff_bps": 162.5,
    "rate_diff_change_21d_bps": -25.0,
    "policy_rates": {"FED": 3.625, "ECB": 2.0},
    "forward_rate": 1.1631,
    "garch_vol_annual": 0.071,
    "horizon_sigma": 0.0205,
    "garch_sigma": 0.019,
    "event_extra_variance": 4e-05,
    "student_t_nu": 6.1,
    "last_surprise_bps": {"FED": 0.0, "ECB": -10.0},
    "hawkish_score": {"FED": 0.25, "ECB": -0.4},
    "days_to_next_meeting": {"FED": 7, "ECB": 8},
    "served_reason": "forward beats random walk on the last 250 days",
    "model_inputs": {"spot": 1.16},
    "seed": 7,
}
MEETINGS = {
    1: [],
    5: [{"bank": "FED", "date": "2026-10-28"}],
    21: [{"bank": "FED", "date": "2026-10-28"}, {"bank": "ECB", "date": "2026-10-29"}],
}


@pytest.fixture
def client(clean_db) -> Iterator[TestClient]:
    app = create_app(frontend_dist=None)
    app.dependency_overrides[get_now] = lambda: NOW
    with TestClient(app) as c:
        yield c


def add_run(
    session: Session,
    run_date: dt.date = TODAY,
    pair: str = "EURUSD",
    served: str | None = "forward",
    models: tuple[str, ...] = ("random_walk", "forward"),
) -> None:
    spot = 1.16 if pair == "EURUSD" else 385.0
    for h in HORIZONS:
        w = 0.004 * h**0.5
        for m in models:
            session.add(
                Forecast(
                    run_date=run_date,
                    pair=pair,
                    horizon_days=h,
                    target_date=run_date + dt.timedelta(days=h),
                    model=m,
                    model_version=f"{m}@1",
                    spot=Decimal(str(spot)),
                    center=Decimal(str(round(spot * (1 + 0.1 * w), 6))),
                    q025=Decimal(str(round(spot * (1 - 2.0 * w), 6))),
                    q10=Decimal(str(round(spot * (1 - 1.3 * w), 6))),
                    q25=Decimal(str(round(spot * (1 - 0.7 * w), 6))),
                    q75=Decimal(str(round(spot * (1 + 0.7 * w), 6))),
                    q90=Decimal(str(round(spot * (1 + 1.3 * w), 6))),
                    q975=Decimal(str(round(spot * (1 + 2.0 * w), 6))),
                    served=m == served,
                    meetings_in_horizon=MEETINGS[h],
                    git_sha="abc123",
                    features_json=FEATURES,
                )
            )


def job(
    session: Session,
    name: str,
    status: str,
    finished_at: dt.datetime,
    error: str | None = None,
    duration: float = 3.0,
    rows: int = 6,
) -> None:
    session.add(
        JobRun(
            job=name,
            started_at=finished_at - dt.timedelta(seconds=duration),
            finished_at=finished_at,
            status=status,
            rows_written=rows,
            duration_s=duration,
            error=error,
        )
    )


def all_sources_fresh(session: Session, except_: tuple[str, ...] = ()) -> None:
    for s in SOURCES:
        if s not in except_:
            job(session, s, "success", NOW - dt.timedelta(hours=1))


def at(value: str | None) -> dt.datetime | None:
    return None if value is None else dt.datetime.fromisoformat(value)


def test_fr16_failed_source_shows_stale_warning_with_last_success_time(client, session):
    last_ok = NOW - dt.timedelta(hours=25)
    all_sources_fresh(session, except_=("frankfurter_ecb",))
    job(session, "frankfurter_ecb", "success", last_ok)
    job(
        session,
        "frankfurter_ecb",
        "failed",
        NOW - dt.timedelta(hours=1),
        error="ConnectError: api.frankfurter.dev unreachable\nTraceback (most recent call last):\n ...",
    )
    add_run(session)
    session.commit()

    health = client.get("/api/health").json()
    assert health["status"] == "degraded"
    sources = {s["source"]: s for s in health["sources"]}
    ecb = sources["frankfurter_ecb"]
    assert ecb["stale"] is True
    assert ecb["label"] == "ECB reference rate (Frankfurter)"
    assert ecb["last_status"] == "failed"
    assert at(ecb["last_success"]) == last_ok
    assert ecb["error"] == "ConnectError: api.frankfurter.dev unreachable"
    assert [k for k, s in sources.items() if s["stale"]] == ["frankfurter_ecb"]

    latest = client.get("/api/forecasts/EURUSD/latest").json()
    assert [s["source"] for s in latest["stale_sources"]] == ["frankfurter_ecb"]
    warning = latest["stale_sources"][0]
    assert warning["stale"] is True
    assert at(warning["last_success"]) == last_ok
    assert warning["label"] == "ECB reference rate (Frankfurter)"


def test_fr16_stale_warning_lists_only_sources_that_feed_the_pair(client, session):
    all_sources_fresh(session, except_=("cba_news", "fed_rss"))
    job(session, "cba_news", "failed", NOW - dt.timedelta(hours=1), error="ParseError: layout")
    job(session, "fed_rss", "success", NOW - dt.timedelta(hours=7))  # older than its 6 h limit
    add_run(session, pair="EURUSD")
    add_run(session, pair="USDAMD")
    session.commit()

    eur = client.get("/api/forecasts/EURUSD/latest").json()["stale_sources"]
    amd = client.get("/api/forecasts/USDAMD/latest").json()["stale_sources"]
    assert [s["source"] for s in eur] == ["fed_rss"]
    assert [s["source"] for s in amd] == ["fed_rss", "cba_news"]
    assert at(eur[0]["last_success"]) == NOW - dt.timedelta(hours=7)
    assert amd[1]["last_success"] is None  # never succeeded
    assert amd[1]["error"] == "ParseError: layout"


def test_fr15_drivers_panel_fields(client, session):
    add_run(session)
    session.commit()
    body = client.get("/api/forecasts/EURUSD/latest").json()
    for h in body["horizons"]:
        d = h["drivers"]
        assert d["rate_diff_bps"] == 162.5
        assert d["forward_rate"] == 1.1631
        assert d["last_surprise_bps"] == {"FED": 0.0, "ECB": -10.0}
        assert d["hawkish_score"] == {"FED": 0.25, "ECB": -0.4}
        assert d["garch_vol_annual"] == 0.071
        assert d["horizon_sigma"] == 0.0205
        assert d["policy_rates"] == {"FED": 3.625, "ECB": 2.0}
        assert d["days_to_next_meeting"] == {"FED": 7, "ECB": 8}
        assert d["served_reason"] == "forward beats random walk on the last 250 days"
        assert h["model"] == "forward"


def test_fr12_forecast_lists_meetings_in_horizon(client, session):
    add_run(session)
    session.commit()
    latest = client.get("/api/forecasts/EURUSD/latest").json()
    assert {h["days"]: h["meetings"] for h in latest["horizons"]} == MEETINGS
    run = client.get("/api/forecasts/EURUSD").json()
    for row in run["rows"]:
        assert row["meetings"] == MEETINGS[row["horizon_days"]]


def test_fr09_bands_ascending_in_response(client, session):
    add_run(session)
    session.commit()
    for h in client.get("/api/forecasts/EURUSD/latest").json()["horizons"]:
        b = h["bands"]
        edges = [b["95"][0], b["80"][0], b["50"][0], b["50"][1], b["80"][1], b["95"][1]]
        assert edges == sorted(edges)
        assert len(set(edges)) == 6
        assert b["50"][0] <= h["center"] <= b["50"][1]


def test_nfr04_last_good_forecast_stays_visible_after_failed_job(client, session):
    all_sources_fresh(session)
    add_run(session, run_date=YESTERDAY)
    job(session, "forecast", "success", NOW - dt.timedelta(days=1))
    # Today's forecast job died after writing only unserved random walk rows.
    add_run(session, run_date=TODAY, served=None, models=("random_walk",))
    job(
        session,
        "forecast",
        "failed",
        NOW - dt.timedelta(minutes=50),
        error="LinAlgError: GARCH fit did not converge",
    )
    session.commit()

    latest = client.get("/api/forecasts/EURUSD/latest")
    assert latest.status_code == 200
    body = latest.json()
    assert body["as_of"] == "2026-10-20"
    assert [h["days"] for h in body["horizons"]] == [1, 5, 21]
    assert all(h["model"] == "forward" for h in body["horizons"])

    run = client.get("/api/forecasts/EURUSD").json()
    assert run["run_date"] == "2026-10-20"  # the default run is the last good one
    assert run["available_run_dates"] == ["2026-10-21", "2026-10-20"]

    forecast_job = client.get("/api/health").json()["jobs"][0]
    assert forecast_job["job"] == "forecast"
    assert forecast_job["last_status"] == "failed"
    assert forecast_job["error"] == "LinAlgError: GARCH fit did not converge"
    assert at(forecast_job["last_success"]) == NOW - dt.timedelta(days=1)


def test_nfr05_metrics_expose_duration_rows_and_status(client, session):
    job(session, "forecast", "success", NOW - dt.timedelta(hours=2), duration=41.5, rows=18)
    job(session, "fred", "success", NOW - dt.timedelta(hours=3), duration=2.25, rows=7)
    job(session, "fred", "failed", NOW - dt.timedelta(hours=1), duration=0.5, rows=0, error="x")
    session.commit()
    r = client.get("/api/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    lines = set(r.text.splitlines())
    assert 'fxf_job_last_duration_seconds{job="forecast"} 41.5' in lines
    assert 'fxf_job_last_rows_written{job="forecast"} 18' in lines
    assert 'fxf_job_last_status{job="forecast"} 1' in lines
    assert 'fxf_job_last_duration_seconds{job="fred"} 0.5' in lines
    assert 'fxf_job_last_status{job="fred"} 0' in lines
    ok_ts = (NOW - dt.timedelta(hours=3)).timestamp()
    assert f'fxf_job_last_success_timestamp_seconds{{job="fred"}} {ok_ts:.1f}' in lines
    assert 'fxf_source_stale{source="fred"} 1' in lines
    for name in (
        "fxf_job_last_duration_seconds",
        "fxf_job_last_rows_written",
        "fxf_job_last_success_timestamp_seconds",
        "fxf_job_last_status",
    ):
        assert f"# TYPE {name} gauge" in lines

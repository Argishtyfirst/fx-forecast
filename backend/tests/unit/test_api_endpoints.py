"""Every API endpoint: happy path, defaults, 404 and 422 cases, against the test database."""

import datetime as dt
from collections.abc import Iterable, Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from fxf.api.deps import get_now, get_session
from fxf.api.main import create_app
from fxf.constants import DISCLAIMER, HORIZONS, SOURCES
from fxf.models import BacktestMetric, CbEvent, CbMeeting, Forecast, JobRun, Rate

pytestmark = pytest.mark.db

NOW = dt.datetime(2026, 10, 21, 17, 0, tzinfo=dt.UTC)
TODAY = dt.date(2026, 10, 21)
OFFSETS = {"q025": -2.0, "q10": -1.3, "q25": -0.7, "q75": 0.7, "q90": 1.3, "q975": 2.0}


@pytest.fixture
def client(clean_db) -> Iterator[TestClient]:
    app = create_app(frontend_dist=None)
    app.dependency_overrides[get_now] = lambda: NOW
    with TestClient(app) as c:
        yield c


def forecast(
    pair: str,
    run_date: dt.date,
    horizon: int,
    model: str,
    *,
    served: bool = False,
    spot: float = 1.16,
    meetings: list[dict[str, str]] | None = None,
    features: dict | None = None,
) -> Forecast:
    w = 0.004 * horizon**0.5
    q = {col: Decimal(str(round(spot * (1 + k * w), 6))) for col, k in OFFSETS.items()}
    return Forecast(
        run_date=run_date,
        pair=pair,
        horizon_days=horizon,
        target_date=run_date + dt.timedelta(days=horizon),
        model=model,
        model_version=f"{model}@1",
        spot=Decimal(str(spot)),
        center=Decimal(str(spot)),
        served=served,
        meetings_in_horizon=meetings or [],
        git_sha="abc123",
        features_json=features if features is not None else {"spot_date": "2026-10-20"},
        **q,
    )


def add_run(
    session: Session,
    pair: str = "EURUSD",
    run_date: dt.date = TODAY,
    models: Iterable[str] = ("random_walk", "forward"),
    served_model: str | None = "random_walk",
    **kw,
) -> None:
    for h in HORIZONS:
        for m in models:
            session.add(forecast(pair, run_date, h, m, served=m == served_model, **kw))


def job(
    session: Session,
    name: str,
    status: str,
    finished_at: dt.datetime,
    *,
    duration: float = 2.0,
    rows: int = 10,
    error: str | None = None,
) -> None:
    session.add(
        JobRun(
            job=name,
            started_at=finished_at - dt.timedelta(seconds=duration),
            finished_at=None if status == "running" else finished_at,
            status=status,
            rows_written=rows,
            duration_s=None if status == "running" else duration,
            error=error,
        )
    )


# --- pairs / unknown pair ------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/api/rates/GBPUSD",
        "/api/forecasts/GBPUSD/latest",
        "/api/forecasts/GBPUSD",
        "/api/backtests/GBPUSD",
        "/api/rates/RUBAMD",  # stored as a feature series, never served
    ],
)
def test_unknown_pair_returns_404(client, path):
    r = client.get(path)
    assert r.status_code == 404
    assert "unknown pair" in r.json()["detail"]
    assert "EURUSD" in r.json()["detail"]


def test_pair_id_is_case_insensitive(client, session):
    session.add(Rate(pair="EURUSD", date=TODAY, rate=Decimal("1.16"), source="x", fetched_at=NOW))
    session.commit()
    body = client.get("/api/rates/eurusd").json()
    assert body["pair"] == "EURUSD"
    assert len(body["rates"]) == 1


# --- rates -----------------------------------------------------------------------------------


@pytest.fixture
def rates(session: Session) -> None:
    d = dt.date(2025, 9, 1)
    while d <= TODAY:
        session.add(
            Rate(
                pair="EURUSD",
                date=d,
                rate=Decimal("1.1") + Decimal(d.toordinal() % 100) / 1000,
                source="frankfurter_ecb",
                fetched_at=NOW,
            )
        )
        d += dt.timedelta(days=1)
    session.add(Rate(pair="USDAMD", date=TODAY, rate=Decimal("385.5"), source="x", fetched_at=NOW))
    session.commit()


def test_rates_default_to_one_year_ending_at_latest_stored_date(client, rates):
    body = client.get("/api/rates/EURUSD").json()
    assert body["pair"] == "EURUSD"
    assert body["source"] == "frankfurter_ecb"
    dates = [p["date"] for p in body["rates"]]
    assert dates[0] == "2025-10-21"  # to - 365 days
    assert dates[-1] == "2026-10-21"
    assert dates == sorted(dates)
    assert len(dates) == 366
    assert isinstance(body["rates"][0]["rate"], float)


def test_rates_explicit_range(client, rates):
    body = client.get("/api/rates/EURUSD", params={"from": "2026-10-01", "to": "2026-10-10"})
    assert [p["date"] for p in body.json()["rates"]] == [f"2026-10-{d:02d}" for d in range(1, 11)]


def test_rates_from_only_runs_to_latest(client, rates):
    body = client.get("/api/rates/EURUSD", params={"from": "2026-10-15"}).json()
    assert [p["date"] for p in body["rates"]][-1] == "2026-10-21"
    assert len(body["rates"]) == 7


def test_rates_to_only_starts_one_year_earlier(client, rates):
    body = client.get("/api/rates/EURUSD", params={"to": "2025-09-10"}).json()
    assert [p["date"] for p in body["rates"]][0] == "2025-09-01"  # history starts here
    assert body["rates"][-1]["date"] == "2025-09-10"


def test_rates_are_per_pair(client, rates):
    body = client.get("/api/rates/USDAMD").json()
    assert body["rates"] == [{"date": "2026-10-21", "rate": 385.5}]
    assert body["source"] == "frankfurter_cba"


def test_rates_empty_history(client):
    assert client.get("/api/rates/EURUSD").json()["rates"] == []


@pytest.mark.parametrize(
    "params",
    [{"from": "2026-13-01"}, {"to": "yesterday"}, {"from": "2026-10-10", "to": "2026-10-01"}],
)
def test_rates_bad_params_return_422(client, params):
    assert client.get("/api/rates/EURUSD", params=params).status_code == 422


# --- latest forecast -------------------------------------------------------------------------


def test_latest_without_forecasts_returns_404(client):
    r = client.get("/api/forecasts/EURUSD/latest")
    assert r.status_code == 404
    assert r.json()["detail"] == "no forecast yet"


def test_latest_serves_one_model_per_horizon(client, session):
    add_run(session, models=("random_walk", "forward", "lightgbm"), served_model="forward")
    add_run(session, pair="USDAMD", spot=385.0, served_model="random_walk")
    session.commit()
    body = client.get("/api/forecasts/EURUSD/latest").json()
    assert body["pair"] == "EURUSD"
    assert body["as_of"] == "2026-10-21"
    assert body["spot"] == 1.16
    assert body["spot_date"] == "2026-10-20"
    assert body["disclaimer"] == DISCLAIMER
    assert [h["days"] for h in body["horizons"]] == [1, 5, 21]
    assert [h["label"] for h in body["horizons"]] == ["1D", "1W", "1M"]
    assert {h["model"] for h in body["horizons"]} == {"forward"}
    h1 = body["horizons"][0]
    assert h1["model_version"] == "forward@1"
    assert h1["target_date"] == "2026-10-22"
    assert set(h1["bands"]) == {"50", "80", "95"}
    assert h1["bands"]["80"] == [
        pytest.approx(1.16 * (1 - 1.3 * 0.004)),
        pytest.approx(1.16 * (1 + 1.3 * 0.004)),
    ]
    assert body["stale_sources"]  # nothing ever ran in this test, so every source is stale


def test_latest_picks_most_recent_run_with_served_rows(client, session):
    add_run(session, run_date=dt.date(2026, 10, 19))
    add_run(session, run_date=dt.date(2026, 10, 20))
    # A newer run whose rows are not served (e.g. a job that died before model selection).
    add_run(session, run_date=TODAY, served_model=None)
    session.commit()
    assert client.get("/api/forecasts/EURUSD/latest").json()["as_of"] == "2026-10-20"


def test_latest_spot_date_falls_back_to_rates_table(client, session):
    add_run(session, features={})
    session.add(
        Rate(
            pair="EURUSD",
            date=dt.date(2026, 10, 19),
            rate=Decimal("1.16"),
            source="x",
            fetched_at=NOW,
        )
    )
    session.add(
        Rate(
            pair="EURUSD",
            date=dt.date(2026, 10, 22),
            rate=Decimal("1.17"),
            source="x",
            fetched_at=NOW,
        )
    )
    session.commit()
    body = client.get("/api/forecasts/EURUSD/latest").json()
    assert body["spot_date"] == "2026-10-19"  # latest rate on or before the run date
    assert body["spot"] == 1.16


def test_latest_stale_sources_empty_when_all_fresh(client, session):
    add_run(session)
    for s in SOURCES:
        job(session, s, "success", NOW - dt.timedelta(hours=1))
    session.commit()
    assert client.get("/api/forecasts/EURUSD/latest").json()["stale_sources"] == []


# --- forecast run ----------------------------------------------------------------------------


def test_forecast_run_defaults_to_latest(client, session):
    add_run(session, run_date=dt.date(2026, 10, 20))
    add_run(
        session,
        run_date=TODAY,
        models=("random_walk", "forward", "lightgbm"),
        served_model="lightgbm",
    )
    session.commit()
    body = client.get("/api/forecasts/EURUSD").json()
    assert body["pair"] == "EURUSD"
    assert body["run_date"] == "2026-10-21"
    assert body["available_run_dates"] == ["2026-10-21", "2026-10-20"]
    assert len(body["rows"]) == 9
    assert [(r["horizon_days"], r["model"]) for r in body["rows"][:3]] == [
        (1, "random_walk"),
        (1, "forward"),
        (1, "lightgbm"),
    ]
    served = [(r["horizon_days"], r["model"]) for r in body["rows"] if r["served"]]
    assert served == [(1, "lightgbm"), (5, "lightgbm"), (21, "lightgbm")]
    row = body["rows"][0]
    assert row["git_sha"] == "abc123"
    assert row["q025"] < row["q10"] < row["q25"] < row["q75"] < row["q90"] < row["q975"]


def test_forecast_run_by_date(client, session):
    add_run(session, run_date=dt.date(2026, 10, 20))
    add_run(session, run_date=TODAY)
    session.commit()
    body = client.get("/api/forecasts/EURUSD", params={"run_date": "2026-10-20"}).json()
    assert body["run_date"] == "2026-10-20"
    assert len(body["rows"]) == 6


def test_forecast_run_lists_at_most_60_dates(client, session):
    for i in range(65):
        session.add(forecast("EURUSD", TODAY - dt.timedelta(days=i), 1, "random_walk", served=True))
    session.commit()
    dates = client.get("/api/forecasts/EURUSD").json()["available_run_dates"]
    assert len(dates) == 60
    assert dates[0] == "2026-10-21"
    assert dates == sorted(dates, reverse=True)


def test_forecast_run_unknown_date_returns_404(client, session):
    add_run(session)
    session.commit()
    r = client.get("/api/forecasts/EURUSD", params={"run_date": "2020-01-01"})
    assert r.status_code == 404
    assert "2020-01-01" in r.json()["detail"]


def test_forecast_run_without_forecasts_returns_404(client):
    r = client.get("/api/forecasts/EURUSD")
    assert r.status_code == 404
    assert r.json()["detail"] == "no forecast yet"


def test_forecast_run_bad_date_returns_422(client):
    assert client.get("/api/forecasts/EURUSD", params={"run_date": "21/10/2026"}).status_code == 422


# --- backtests -------------------------------------------------------------------------------


def metric(run_date: dt.date, h: int, model: str, window: str, **kw) -> BacktestMetric:
    values = dict(
        n_obs=250,
        start_date=dt.date(2025, 10, 1),
        end_date=run_date,
        mae=0.004,
        mae_ratio_rw=1.0,
        hit_rate=0.5,
        cov50=0.5,
        cov80=0.8,
        cov95=0.95,
        pinball=0.001,
        pinball_ref=0.0011,
        dm_pvalue=None,
    )
    values.update(kw)
    return BacktestMetric(
        run_date=run_date, pair="EURUSD", horizon_days=h, model=model, window=window, **values
    )


@pytest.fixture
def backtests(session: Session) -> None:
    old = dt.date(2026, 10, 11)
    new = dt.date(2026, 10, 18)
    session.add(metric(old, 5, "forward", "250d", mae_ratio_rw=0.5, dm_pvalue=0.01))
    for h in HORIZONS:
        for window in ("250d", "full"):
            session.add(metric(new, h, "random_walk", window))
    session.add(metric(new, 5, "forward", "250d", mae_ratio_rw=0.95, dm_pvalue=0.04))
    session.add(metric(new, 5, "forward", "full", mae_ratio_rw=0.95, dm_pvalue=0.04))
    session.add(metric(new, 21, "forward", "250d", mae_ratio_rw=0.97, dm_pvalue=0.2))
    session.add(metric(new, 21, "lightgbm", "250d", mae_ratio_rw=0.99, dm_pvalue=0.01))
    # The latest forecast run serves forward at 5D and random walk elsewhere.
    for h in HORIZONS:
        session.add(forecast("EURUSD", TODAY, h, "random_walk", served=h != 5))
    session.add(forecast("EURUSD", TODAY, 5, "forward", served=True))
    session.commit()


def test_backtests_use_latest_run_and_both_windows(client, backtests):
    body = client.get("/api/backtests/EURUSD").json()
    assert body["pair"] == "EURUSD"
    assert body["run_date"] == "2026-10-18"
    assert body["targets"] == {
        "mae_ratio": 1.0,
        "hit_rate": 0.5,
        "coverage_tolerance": 0.05,
        "dm_pvalue": 0.1,
        "promotion_mae_ratio": 0.98,
    }
    keys = [(m["horizon_days"], m["model"], m["window"]) for m in body["metrics"]]
    assert len(keys) == 10
    assert keys[:2] == [(1, "random_walk", "250d"), (1, "random_walk", "full")]
    assert {w for _, _, w in keys} == {"250d", "full"}


def test_backtests_promoted_and_served_flags(client, backtests):
    rows = {
        (m["horizon_days"], m["model"], m["window"]): m
        for m in client.get("/api/backtests/EURUSD").json()["metrics"]
    }
    assert rows[(5, "forward", "250d")]["promoted"] is True
    assert rows[(5, "forward", "full")]["promoted"] is False  # the rule uses the 250d window
    assert rows[(21, "forward", "250d")]["promoted"] is False  # DM p-value too high
    assert rows[(21, "lightgbm", "250d")]["promoted"] is False  # MAE ratio too high
    assert rows[(1, "random_walk", "250d")]["promoted"] is False
    assert rows[(5, "forward", "250d")]["served"] is True
    assert rows[(5, "random_walk", "250d")]["served"] is False
    assert rows[(21, "random_walk", "full")]["served"] is True


def test_backtests_filter_by_horizon(client, backtests):
    body = client.get("/api/backtests/EURUSD", params={"horizon": 5}).json()
    assert {m["horizon_days"] for m in body["metrics"]} == {5}
    assert len(body["metrics"]) == 4


def test_backtests_empty(client):
    body = client.get("/api/backtests/USDAMD").json()
    assert body == {
        "pair": "USDAMD",
        "run_date": None,
        "targets": body["targets"],
        "metrics": [],
    }


@pytest.mark.parametrize("horizon", ["2", "abc", "0"])
def test_backtests_bad_horizon_returns_422(client, horizon):
    assert client.get("/api/backtests/EURUSD", params={"horizon": horizon}).status_code == 422


# --- events ----------------------------------------------------------------------------------


@pytest.fixture
def events(session: Session) -> None:
    session.add_all(
        [
            CbEvent(
                bank="ECB",
                date=dt.date(2026, 9, 10),
                rate_type="deposit",
                rate_before=Decimal("2.0"),
                rate_after=Decimal("2.0"),
                expected=Decimal("2.0"),
                expected_source="previous_rate",
                surprise_bps=0.0,
                statement_url="https://ecb.example/2026-09-10",
                statement_text="Rates unchanged.",
                statement_diff={"added": ["New."], "removed": ["Old."], "previous_event_id": None},
                hawkish_score=-0.2,
                hawkish_reason="Mild easing bias.",
                scorer_version="lexicon@v1",
            ),
            CbEvent(
                bank="CBA",
                date=dt.date(2026, 9, 16),
                rate_type="refinancing",
                rate_before=Decimal("7.0"),
                rate_after=Decimal("6.75"),
                expected=Decimal("7.0"),
                surprise_bps=-25.0,
                rates_json={
                    "refinancing": {"before": 7.0, "after": 6.75},
                    "lombard": {"before": 8.0, "after": 7.75},
                    "deposit": {"before": 6.0, "after": None},
                },
            ),
            CbEvent(
                bank="FED", date=dt.date(2026, 9, 17), rate_type="target_mid", surprise_bps=0.0
            ),
            CbEvent(bank="FED", date=dt.date(2022, 9, 21), rate_type="target_mid"),  # > 3 years ago
            CbMeeting(bank="FED", date=dt.date(2026, 10, 28), scheduled=True),
            CbMeeting(bank="ECB", date=dt.date(2026, 10, 29), scheduled=True),
            CbMeeting(bank="CBA", date=TODAY, scheduled=False),
            CbMeeting(bank="ECB", date=dt.date(2026, 9, 10), scheduled=True),  # past
        ]
    )
    session.commit()


def test_events_decisions_most_recent_first_within_three_years(client, events):
    body = client.get("/api/events").json()
    assert [(d["bank"], d["date"]) for d in body["decisions"]] == [
        ("FED", "2026-09-17"),
        ("CBA", "2026-09-16"),
        ("ECB", "2026-09-10"),
    ]
    ecb = body["decisions"][2]
    assert ecb["statement_diff"] == {
        "added": ["New."],
        "removed": ["Old."],
        "previous_event_id": None,
    }
    assert ecb["rate_after"] == 2.0
    assert ecb["hawkish_score"] == -0.2
    assert ecb["scorer_version"] == "lexicon@v1"
    assert ecb["rates"] is None
    cba = body["decisions"][1]
    assert cba["rates"]["lombard"] == {"before": 8.0, "after": 7.75}
    assert cba["rates"]["deposit"] == {"before": 6.0, "after": None}
    assert cba["statement_diff"] is None
    assert cba["surprise_bps"] == -25.0


def test_events_upcoming_meetings_soonest_first(client, events):
    assert client.get("/api/events").json()["upcoming"] == [
        {"bank": "CBA", "date": "2026-10-21", "scheduled": False, "days_until": 0},
        {"bank": "FED", "date": "2026-10-28", "scheduled": True, "days_until": 7},
        {"bank": "ECB", "date": "2026-10-29", "scheduled": True, "days_until": 8},
    ]


def test_events_filter_by_bank_case_insensitive(client, events):
    body = client.get("/api/events", params={"bank": "ecb"}).json()
    assert [(d["bank"], d["date"]) for d in body["decisions"]] == [("ECB", "2026-09-10")]
    assert [m["bank"] for m in body["upcoming"]] == ["ECB"]


def test_events_from_param(client, events):
    body = client.get("/api/events", params={"from": "2020-01-01", "bank": "FED"}).json()
    assert [d["date"] for d in body["decisions"]] == ["2026-09-17", "2022-09-21"]
    body = client.get("/api/events", params={"from": "2026-09-16"}).json()
    assert [d["bank"] for d in body["decisions"]] == ["FED", "CBA"]


@pytest.mark.parametrize("params", [{"bank": "BOE"}, {"from": "not-a-date"}])
def test_events_bad_params_return_422(client, params):
    assert client.get("/api/events", params=params).status_code == 422


def test_events_empty(client):
    assert client.get("/api/events").json() == {"decisions": [], "upcoming": []}


# --- health ----------------------------------------------------------------------------------


def test_health_ok_when_all_sources_fresh(client, session):
    for s in SOURCES:
        job(session, s, "success", NOW - dt.timedelta(hours=1))
    job(session, "forecast", "success", NOW - dt.timedelta(minutes=30), duration=42.0, rows=18)
    session.commit()
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert dt.datetime.fromisoformat(body["checked_at"]) == NOW
    assert [s["source"] for s in body["sources"]] == list(SOURCES)
    assert all(not s["stale"] and s["last_status"] == "success" for s in body["sources"])
    assert {s["label"] for s in body["sources"]} >= {"FRED", "ECB Data Portal", "CBA policy rates"}
    jobs = {j["job"]: j for j in body["jobs"]}
    assert list(jobs) == ["forecast", "backtest", "score_statements", "ai_view"]
    assert jobs["forecast"]["last_duration_s"] == 42.0
    assert jobs["forecast"]["last_rows_written"] == 18
    assert jobs["forecast"]["last_status"] == "success"
    assert jobs["backtest"] == {
        "job": "backtest",
        "last_success": None,
        "last_run": None,
        "last_status": None,
        "last_duration_s": None,
        "last_rows_written": None,
        "error": None,
    }


def test_health_degraded_when_nothing_ran(client):
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert all(s["stale"] and s["last_status"] is None for s in body["sources"])


def test_health_reports_latest_run_and_first_error_line(client, session):
    ok = NOW - dt.timedelta(hours=30)
    job(session, "fred", "success", ok)
    job(
        session,
        "fred",
        "failed",
        NOW - dt.timedelta(hours=2),
        error="ReadTimeout: fred\nTraceback ...",
    )
    job(session, "forecast", "success", ok)
    job(session, "forecast", "running", NOW - dt.timedelta(minutes=1))
    session.commit()
    body = client.get("/api/health").json()
    fred = next(s for s in body["sources"] if s["source"] == "fred")
    assert fred["stale"] is True
    assert fred["last_status"] == "failed"
    assert fred["error"] == "ReadTimeout: fred"
    assert dt.datetime.fromisoformat(fred["last_success"]) == ok
    assert dt.datetime.fromisoformat(fred["last_run"]) == NOW - dt.timedelta(hours=2, seconds=2)
    forecast_job = body["jobs"][0]
    assert forecast_job["last_status"] == "running"
    assert forecast_job["error"] is None
    assert dt.datetime.fromisoformat(forecast_job["last_success"]) == ok


# --- metrics ---------------------------------------------------------------------------------


def test_metrics_is_prometheus_text(client, session):
    job(session, "forecast", "success", NOW - dt.timedelta(hours=1), duration=12.5, rows=18)
    job(session, "frankfurter_ecb", "failed", NOW - dt.timedelta(hours=1), rows=0)
    session.commit()
    r = client.get("/api/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert 'fxf_job_last_duration_seconds{job="forecast"} 12.5' in r.text
    assert 'fxf_job_last_status{job="frankfurter_ecb"} 0' in r.text
    assert 'fxf_source_stale{source="frankfurter_ecb"} 1' in r.text


# --- read-only session / database down -------------------------------------------------------


def test_api_session_is_read_only(clean_db):
    gen = get_session()
    s = next(gen)
    try:
        with pytest.raises(DBAPIError, match="read-only transaction"):
            s.execute(text("DELETE FROM job_runs"))
    finally:
        gen.close()


def test_database_down_returns_503(client):
    def broken_session():
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        yield  # pragma: no cover

    client.app.dependency_overrides[get_session] = broken_session
    r = client.get("/api/health")
    assert r.status_code == 503
    assert r.json() == {"detail": "database unavailable"}

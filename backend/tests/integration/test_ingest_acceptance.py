"""Acceptance tests for milestone 1 ingest (FR-01 to FR-04) on recorded fixtures.

The fake sources serve the recorded responses in tests/fixtures and honour the
window parameters (from/to, cosd, startPeriod) the way the real APIs do, so a daily
run only sees its window and a first run sees the whole recorded history.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from fxf import http
from fxf.calendars import CET
from fxf.config import get_settings
from fxf.constants import (
    ECB_SERIES,
    FRED_SERIES,
    RUBAMD,
    SOURCE_ECB,
    SOURCE_FRANKFURTER_CBA,
    SOURCE_FRANKFURTER_ECB,
    SOURCE_FRED,
)
from fxf.ingest.pipeline import backfill, run_ingest
from fxf.models import JobRun, MacroSeries, Rate

FIX = Path(__file__).resolve().parents[1] / "fixtures"

FRANKFURTER_FILES = {
    ("EUR", "USD", "ECB"): "ecb_EUR_USD.json",
    ("USD", "AMD", "CBA"): "cba_USD_AMD.json",
    ("EUR", "AMD", "CBA"): "cba_EUR_AMD.json",
    ("RUB", "AMD", "CBA"): "cba_RUB_AMD.json",
}
ECB_FILES = {
    "FM/D.U2.EUR.4F.KR.DFR.LEV": "ECB_DFR.csv",
    "EST/B.EU000A2X2A25.WT": "ESTR.csv",
    "HICP/M.U2.N.000000.4D0.ANR": "HICP.csv",
}
RATE_SOURCES = [SOURCE_FRANKFURTER_ECB, SOURCE_FRANKFURTER_CBA]
MACRO_SOURCES = [SOURCE_FRED, SOURCE_ECB]


def cet(y: int, m: int, d: int, hh: int, mm: int = 0) -> dt.datetime:
    return dt.datetime(y, m, d, hh, mm, tzinfo=CET)


@dataclass
class FakeSources:
    """In-memory stand-ins for Frankfurter, FRED and the ECB Data Portal."""

    frankfurter: dict[tuple[str, str, str], list[dict[str, Any]]]
    fred_csv: dict[str, str]
    ecb_csv: dict[str, str]
    calls: list[dict[str, str]] = field(default_factory=list)
    served: dict[tuple[str, str, str], int] = field(default_factory=dict)
    # Optional per-host hook: return a response to short-circuit the recorded data.
    override: dict[str, Callable[[httpx.Request], httpx.Response | None]] = field(
        default_factory=dict
    )

    def _overridden(self, host: str, request: httpx.Request) -> httpx.Response | None:
        hook = self.override.get(host)
        return hook(request) if hook else None

    def frankfurter_handler(self, request: httpx.Request) -> httpx.Response:
        p = dict(request.url.params)
        self.calls.append({"host": "frankfurter", **p})
        if (resp := self._overridden("frankfurter", request)) is not None:
            return resp
        key = (p["base"], p["quotes"], p["providers"])
        rows = [
            r for r in self.frankfurter[key] if p["from"] <= r["date"] <= p.get("to", "9999-12-31")
        ]
        self.served[key] = len(rows)
        return httpx.Response(200, json=rows)

    def fred_handler(self, request: httpx.Request) -> httpx.Response:
        p = dict(request.url.params)
        self.calls.append({"host": "fred", **p})
        header, *lines = self.fred_csv[p["id"]].splitlines()
        keep = [ln for ln in lines if ln.split(",")[0] >= p.get("cosd", "")]
        return httpx.Response(200, text="\n".join([header, *keep]) + "\n")

    def ecb_handler(self, request: httpx.Request) -> httpx.Response:
        p = dict(request.url.params)
        key = request.url.path.removeprefix("/service/data/")
        self.calls.append({"host": "ecb", "key": key, **p})
        reader = csv.DictReader(io.StringIO(self.ecb_csv[key]))
        start = p["startPeriod"]
        rows = [r for r in reader if r["TIME_PERIOD"] >= start[: len(r["TIME_PERIOD"])]]
        if not rows:
            return httpx.Response(200, text="")
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\r\n")
        w.writeheader()
        w.writerows(rows)
        return httpx.Response(200, text=out.getvalue())

    def install(self, router: respx.Router) -> None:
        router.get(url__startswith="https://api.frankfurter.dev/v2/rates").mock(
            side_effect=self.frankfurter_handler
        )
        router.get(url__startswith="https://fred.stlouisfed.org/graph/fredgraph.csv").mock(
            side_effect=self.fred_handler
        )
        router.get(url__startswith="https://data-api.ecb.europa.eu/service/data/").mock(
            side_effect=self.ecb_handler
        )


@pytest.fixture
def fake() -> Iterator[FakeSources]:
    sources = FakeSources(
        frankfurter={
            k: json.loads((FIX / "frankfurter" / f).read_text())
            for k, f in FRANKFURTER_FILES.items()
        },
        fred_csv={s: (FIX / "fred" / f"{s}.csv").read_text() for s in FRED_SERIES},
        ecb_csv={k: (FIX / "ecb" / f).read_text() for k, f in ECB_FILES.items()},
    )
    with respx.mock(assert_all_called=False) as router:
        sources.install(router)
        yield sources


@pytest.fixture(autouse=True)
def _no_sleep_no_fred_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http, "sleep", lambda _s: None)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    get_settings.cache_clear()


def rate_count(engine: Engine, pair: str) -> int:
    with Session(engine) as s:
        return s.scalar(select(func.count()).select_from(Rate).where(Rate.pair == pair)) or 0


def job_rows(engine: Engine) -> list[JobRun]:
    with Session(engine) as s:
        return list(s.scalars(select(JobRun).order_by(JobRun.id)))


def last_job(engine: Engine, source: str) -> JobRun:
    rows = [r for r in job_rows(engine) if r.job == source]
    assert rows, f"no job_runs row for {source}"
    return rows[-1]


def requests_for(fake: FakeSources, pred: Callable[[dict[str, str]], bool]) -> list[dict[str, str]]:
    return [c for c in fake.calls if pred(c)]


# --- FR-01 -----------------------------------------------------------------------------


def test_fr01_after_1700_cet_on_a_working_day_both_pairs_hold_todays_rate(clean_db, fake):
    now = cet(2026, 10, 20, 17, 30)  # Tuesday, TARGET2 and Armenian trading day

    result = run_ingest(clean_db, now=now, sources=RATE_SOURCES)

    assert result == {SOURCE_FRANKFURTER_ECB: True, SOURCE_FRANKFURTER_CBA: True}
    with Session(clean_db) as s:
        for pair in ("EURUSD", "USDAMD"):
            assert s.get(Rate, (pair, dt.date(2026, 10, 20))) is not None


def test_fr01_missing_todays_rate_after_1700_cet_fails_the_job_and_alerts(
    clean_db, fake, _capture_alerts
):
    # The recorded EUR/USD history ends on 2026-10-20; USD/AMD already has 2026-10-21.
    now = cet(2026, 10, 21, 17, 30)

    result = run_ingest(clean_db, now=now, sources=RATE_SOURCES)

    assert result == {SOURCE_FRANKFURTER_ECB: False, SOURCE_FRANKFURTER_CBA: True}
    job = last_job(clean_db, SOURCE_FRANKFURTER_ECB)
    assert job.status == "failed"
    assert "today's EURUSD rate is not published yet" in (job.error or "")
    assert any(a["title"] == f"Job failed: {SOURCE_FRANKFURTER_ECB}" for a in _capture_alerts)
    # What was published is still stored, so a rerun only needs the missing day.
    assert rate_count(clean_db, "EURUSD") == fake.served[("EUR", "USD", "ECB")]
    with Session(clean_db) as s:
        assert s.get(Rate, ("USDAMD", dt.date(2026, 10, 21))) is not None


def test_fr01_rerun_after_publication_succeeds(clean_db, fake):
    now = cet(2026, 10, 21, 17, 30)
    assert run_ingest(clean_db, now=now, sources=[SOURCE_FRANKFURTER_ECB]) == {
        SOURCE_FRANKFURTER_ECB: False
    }
    fake.frankfurter[("EUR", "USD", "ECB")].append(
        {"date": "2026-10-21", "base": "EUR", "quote": "USD", "rate": 1.1222}
    )

    later = cet(2026, 10, 21, 18, 15)
    assert run_ingest(clean_db, now=later, sources=[SOURCE_FRANKFURTER_ECB]) == {
        SOURCE_FRANKFURTER_ECB: True
    }
    with Session(clean_db) as s:
        assert float(s.get(Rate, ("EURUSD", dt.date(2026, 10, 21))).rate) == pytest.approx(1.1222)


def test_fr01_before_1700_cet_an_unpublished_rate_is_not_an_error(clean_db, fake):
    now = cet(2026, 10, 21, 16, 30)

    assert run_ingest(clean_db, now=now, sources=RATE_SOURCES) == {
        SOURCE_FRANKFURTER_ECB: True,
        SOURCE_FRANKFURTER_CBA: True,
    }


# --- FR-02 -----------------------------------------------------------------------------


def test_fr02_first_run_loads_full_history_for_all_pairs(clean_db, fake):
    now = cet(2026, 10, 21, 12, 0)

    assert run_ingest(clean_db, now=now, sources=RATE_SOURCES) == {
        SOURCE_FRANKFURTER_ECB: True,
        SOURCE_FRANKFURTER_CBA: True,
    }

    full = requests_for(fake, lambda c: c["host"] == "frankfurter")
    starts = {(c["base"], c["quotes"]): c["from"] for c in full}
    assert starts == {
        ("EUR", "USD"): "1999-01-01",
        ("USD", "AMD"): "1990-01-01",
        ("EUR", "AMD"): "1990-01-01",
        ("RUB", "AMD"): "1990-01-01",
    }
    for (base, quote, provider), pair in {
        ("EUR", "USD", "ECB"): "EURUSD",
        ("USD", "AMD", "CBA"): "USDAMD",
        ("EUR", "AMD", "CBA"): "EURAMD",
        ("RUB", "AMD", "CBA"): RUBAMD,
    }.items():
        served = fake.served[(base, quote, provider)]
        assert served > 400
        assert rate_count(clean_db, pair) == served


def test_fr02_rows_keep_source_and_fetched_at(clean_db, fake):
    now = cet(2026, 10, 21, 12, 0)
    run_ingest(clean_db, now=now, sources=RATE_SOURCES)

    with Session(clean_db) as s:
        eur = s.get(Rate, ("EURUSD", dt.date(2025, 1, 2)))
        rub = s.get(Rate, (RUBAMD, dt.date(2026, 10, 21)))
    assert eur is not None and eur.source == SOURCE_FRANKFURTER_ECB
    assert float(eur.rate) == pytest.approx(1.0321)
    assert eur.fetched_at == now
    assert rub is not None and rub.source == SOURCE_FRANKFURTER_CBA


# --- FR-03 -----------------------------------------------------------------------------


def test_fr03_ingest_is_idempotent(clean_db, fake):
    now = cet(2026, 10, 20, 18, 0)
    run_ingest(clean_db, now=now, sources=RATE_SOURCES)
    before = {p: rate_count(clean_db, p) for p in ("EURUSD", "USDAMD", "EURAMD", RUBAMD)}

    run_ingest(clean_db, now=now, sources=RATE_SOURCES)

    assert {p: rate_count(clean_db, p) for p in before} == before
    with Session(clean_db) as s:
        dupes = s.execute(
            select(Rate.pair, Rate.date).group_by(Rate.pair, Rate.date).having(func.count() > 1)
        ).all()
    assert dupes == []


def test_fr03_daily_run_refetches_a_10_day_window_and_applies_late_fixes(clean_db, fake):
    run_ingest(clean_db, now=cet(2026, 10, 19, 18, 0), sources=[SOURCE_FRANKFURTER_ECB])
    # The source corrects an already-stored fixing.
    for r in fake.frankfurter[("EUR", "USD", "ECB")]:
        if r["date"] == "2026-10-15":
            r["rate"] = 1.2000
    fake.calls.clear()

    run_ingest(clean_db, now=cet(2026, 10, 20, 18, 0), sources=[SOURCE_FRANKFURTER_ECB])

    (call,) = requests_for(fake, lambda c: c["host"] == "frankfurter")
    assert (call["from"], call["to"]) == ("2026-10-09", "2026-10-20")
    with Session(clean_db) as s:
        assert float(s.get(Rate, ("EURUSD", dt.date(2026, 10, 15))).rate) == pytest.approx(1.2)
        assert s.get(Rate, ("EURUSD", dt.date(2026, 10, 20))) is not None
    assert rate_count(clean_db, "EURUSD") == len(
        [r for r in fake.frankfurter[("EUR", "USD", "ECB")] if r["date"] <= "2026-10-20"]
    )


# --- FR-04 -----------------------------------------------------------------------------


def test_fr04_each_macro_series_stores_value_and_publication_date(clean_db, fake):
    now = dt.datetime(2026, 10, 21, 12, 0, tzinfo=dt.UTC)

    assert run_ingest(clean_db, now=now, sources=MACRO_SOURCES) == {
        SOURCE_FRED: True,
        SOURCE_ECB: True,
    }

    with Session(clean_db) as s:
        for series_id in (*FRED_SERIES, *ECB_SERIES):
            rows = s.scalars(select(MacroSeries).where(MacroSeries.series_id == series_id)).all()
            assert rows, series_id
            for r in rows:
                assert r.value is not None
                assert r.published_at <= r.fetched_at == now

        def get(series_id: str, d: dt.date) -> MacroSeries:
            return s.get(MacroSeries, (series_id, d))

        assert get("DFEDTARU", dt.date(2026, 9, 17)).published_at == dt.datetime(
            2026, 9, 17, tzinfo=dt.UTC
        )
        assert float(get("DFEDTARU", dt.date(2026, 9, 17)).value) == 4.0
        # 2026-10-12 is Columbus Day, so the next US business day after Friday 10-09 is 10-13.
        assert get("DGS2", dt.date(2026, 10, 9)).published_at == dt.datetime(
            2026, 10, 13, 22, tzinfo=dt.UTC
        )
        assert get("DGS2", dt.date(2026, 7, 3)) is None  # missing value in the source
        assert get("HICP", dt.date(2026, 9, 1)).published_at == dt.datetime(
            2026, 10, 18, 9, tzinfo=dt.UTC
        )
        assert get("ESTR", dt.date(2026, 10, 20)).published_at == dt.datetime(
            2026, 10, 21, 7, tzinfo=dt.UTC
        )
        # Rule says 2026-10-23 22:00, but we already saw it, so it was public by fetch time.
        assert get("DTWEXBGS", dt.date(2026, 10, 16)).published_at == now
        assert get("FEDTARMD", dt.date(2027, 1, 1)).published_at == now
        assert get("ECB_DFR", dt.date(2026, 9, 16)).source == SOURCE_ECB
        assert get("DFF", dt.date(2026, 10, 19)).source == SOURCE_FRED


def test_fr04_existing_macro_rows_are_never_overwritten(clean_db, fake):
    first = dt.datetime(2026, 10, 21, 12, 0, tzinfo=dt.UTC)
    run_ingest(clean_db, now=first, sources=MACRO_SOURCES)
    fake.fred_csv["DFF"] = fake.fred_csv["DFF"].replace("2026-10-19,3.88", "2026-10-19,9.99")
    fake.calls.clear()

    later = first + dt.timedelta(days=1)
    assert run_ingest(clean_db, now=later, sources=[SOURCE_FRED]) == {SOURCE_FRED: True}

    with Session(clean_db) as s:
        row = s.get(MacroSeries, ("DFF", dt.date(2026, 10, 19)))
    assert float(row.value) == pytest.approx(3.88)
    assert row.fetched_at == first
    # Daily runs ask for a window, not the whole history.
    dff = requests_for(fake, lambda c: c["host"] == "fred" and c["id"] == "DFF")
    assert dff and dff[0]["cosd"] > "2026-08-01"


def test_fr04_first_run_requests_full_macro_history(clean_db, fake):
    run_ingest(clean_db, now=dt.datetime(2026, 10, 21, 12, tzinfo=dt.UTC), sources=MACRO_SOURCES)
    fred = requests_for(fake, lambda c: c["host"] == "fred")
    ecb = requests_for(fake, lambda c: c["host"] == "ecb")
    assert {c["id"] for c in fred} == set(FRED_SERIES)
    assert {c["cosd"] for c in fred} == {"1990-01-01"}
    assert {c["key"] for c in ecb} == set(ECB_FILES)
    assert {c["startPeriod"] for c in ecb} == {"1990-01-01"}


# --- Schema check, retries, isolation, housekeeping ------------------------------------


def test_unknown_frankfurter_shape_fails_the_job_and_alerts(clean_db, fake, _capture_alerts):
    fake.override["frankfurter"] = lambda _r: httpx.Response(200, json={"unexpected": 1})

    result = run_ingest(clean_db, now=dt.datetime(2026, 10, 21, 12, tzinfo=dt.UTC))

    # One broken source does not stop the others.
    assert result == {
        SOURCE_FRANKFURTER_ECB: False,
        SOURCE_FRANKFURTER_CBA: False,
        SOURCE_FRED: True,
        SOURCE_ECB: True,
    }
    job = last_job(clean_db, SOURCE_FRANKFURTER_ECB)
    assert job.status == "failed"
    assert "SchemaError" in (job.error or "")
    titles = {a["title"] for a in _capture_alerts}
    assert {
        f"Job failed: {SOURCE_FRANKFURTER_ECB}",
        f"Job failed: {SOURCE_FRANKFURTER_CBA}",
    } <= titles
    assert rate_count(clean_db, "EURUSD") == 0


def test_ecb_csv_without_obs_value_fails_the_job(clean_db, fake, _capture_alerts):
    key = "EST/B.EU000A2X2A25.WT"
    fake.ecb_csv[key] = fake.ecb_csv[key].replace("OBS_VALUE", "VALUE")

    result = run_ingest(
        clean_db, now=dt.datetime(2026, 10, 21, 12, tzinfo=dt.UTC), sources=[SOURCE_ECB]
    )

    assert result == {SOURCE_ECB: False}
    job = last_job(clean_db, SOURCE_ECB)
    assert job.status == "failed" and "OBS_VALUE" in (job.error or "")
    assert any(a["title"] == f"Job failed: {SOURCE_ECB}" for a in _capture_alerts)
    # The other ECB series of the same job still land.
    with Session(clean_db) as s:
        ids = set(s.scalars(select(MacroSeries.series_id).distinct()))
    assert ids == {"ECB_DFR", "HICP"}


def test_transient_frankfurter_errors_are_retried_within_the_job(clean_db, fake):
    flaky = iter([httpx.Response(503), httpx.Response(429)])
    fake.override["frankfurter"] = lambda _r: next(flaky, None)

    result = run_ingest(clean_db, now=cet(2026, 10, 20, 18, 0), sources=[SOURCE_FRANKFURTER_ECB])

    assert result == {SOURCE_FRANKFURTER_ECB: True}
    assert len(requests_for(fake, lambda c: c["host"] == "frankfurter")) == 3
    assert last_job(clean_db, SOURCE_FRANKFURTER_ECB).status == "success"


def test_client_errors_are_not_retried_and_fail_the_job(clean_db, fake, _capture_alerts):
    fake.override["frankfurter"] = lambda _r: httpx.Response(
        422, json={"status": 422, "message": "invalid currency: XXX"}
    )

    result = run_ingest(clean_db, now=cet(2026, 10, 20, 18, 0), sources=[SOURCE_FRANKFURTER_ECB])

    assert result == {SOURCE_FRANKFURTER_ECB: False}
    assert len(requests_for(fake, lambda c: c["host"] == "frankfurter")) == 1
    assert "HTTP 422" in (last_job(clean_db, SOURCE_FRANKFURTER_ECB).error or "")


def test_run_ingest_writes_one_job_run_per_source(clean_db, fake):
    result = run_ingest(clean_db, now=cet(2026, 10, 20, 18, 0))

    assert result == dict.fromkeys(
        [SOURCE_FRANKFURTER_ECB, SOURCE_FRANKFURTER_CBA, SOURCE_FRED, SOURCE_ECB], True
    )
    rows = job_rows(clean_db)
    assert [r.job for r in rows] == list(result)
    assert all(r.status == "success" and r.rows_written > 0 for r in rows)


def test_run_ingest_rejects_unknown_sources(clean_db):
    with pytest.raises(ValueError, match="cba_rates"):
        run_ingest(clean_db, sources=["cba_rates"])


def test_run_ingest_prunes_old_raw_responses(clean_db, fake):
    root = Path(get_settings().fxf_raw_dir)
    old = root / SOURCE_FRED / "2026-08-01"
    old.mkdir(parents=True)
    (old / "x.csv.gz").write_bytes(b"")

    run_ingest(clean_db, now=cet(2026, 10, 20, 18, 0), sources=[SOURCE_FRED])

    assert not old.exists()
    assert list(root.glob(f"{SOURCE_FRED}/*/*.csv.gz"))  # today's responses are kept


def test_backfill_reloads_full_history_even_when_tables_have_rows(clean_db, fake, monkeypatch):
    run_ingest(clean_db, now=cet(2026, 10, 20, 12, 0))
    fake.calls.clear()
    fixed = cet(2026, 10, 20, 12, 0)
    monkeypatch.setattr("fxf.ingest.pipeline.utcnow", lambda: fixed.astimezone(dt.UTC))

    result = backfill(clean_db)

    assert all(result.values()), result
    frank = {(c["base"], c["quotes"]): c["from"] for c in fake.calls if c["host"] == "frankfurter"}
    assert frank[("EUR", "USD")] == "1999-01-01"
    assert {c["cosd"] for c in fake.calls if c["host"] == "fred"} == {"1990-01-01"}
    assert [r.meta.get("mode") for r in job_rows(clean_db)[-4:]] == ["backfill"] * 4

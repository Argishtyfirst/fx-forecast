"""Pure API rules: the stale rule, driver mapping, Prometheus text, and route methods."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from fxf.api.forecasts import drivers_from_features
from fxf.api.health import SOURCE_LABELS, error_first_line, is_stale, pair_sources
from fxf.api.main import create_app
from fxf.api.metrics import JobSample, escape_label, render_metrics
from fxf.api.schemas import SourceStatus
from fxf.constants import PAIRS, SOURCE_STALE_HOURS, SOURCES

NOW = dt.datetime(2026, 10, 21, 17, 0, tzinfo=dt.UTC)
HOUR = dt.timedelta(hours=1)


def test_every_source_has_a_human_label():
    assert set(SOURCE_LABELS) == set(SOURCES)
    assert SOURCE_LABELS["frankfurter_ecb"] == "ECB reference rate (Frankfurter)"
    assert SOURCE_LABELS["cba_news"] == "CBA decisions (cba.am, ARKA, Interfax)"


@pytest.mark.parametrize(
    ("last_status", "success_age_h", "stale"),
    [
        (None, None, True),  # never ran
        ("running", None, True),  # never succeeded
        ("success", 1, False),
        ("success", SOURCE_STALE_HOURS["fred"], False),  # exactly at the limit
        ("success", SOURCE_STALE_HOURS["fred"] + 1, True),  # too old
        ("failed", 1, True),  # the latest run failed, even with a recent success
        ("running", 1, False),  # a new run in progress keeps the last success
    ],
)
def test_stale_rule(last_status, success_age_h, stale):
    last_success = None if success_age_h is None else NOW - success_age_h * HOUR
    assert is_stale("fred", last_status, last_success, NOW) is stale


def test_stale_rule_uses_the_per_source_limit():
    seven_hours_ago = NOW - 7 * HOUR
    assert is_stale("fed_rss", "success", seven_hours_ago, NOW) is True  # 6 h limit
    assert is_stale("frankfurter_ecb", "success", seven_hours_ago, NOW) is False  # 96 h limit


def test_error_first_line():
    assert error_first_line("HTTPError: 503\nTraceback (most recent call last):\n  x") == (
        "HTTPError: 503"
    )
    assert error_first_line("\n  ValueError: bad shape  \nmore") == "ValueError: bad shape"
    assert error_first_line(None) is None
    assert error_first_line("  \n") is None


def test_pair_sources_cover_rate_macro_and_bank_news():
    assert pair_sources(PAIRS["EURUSD"]) == (
        "frankfurter_ecb",
        "fred",
        "ecb_data_portal",
        "fed_rss",
        "ecb_rss",
        "atlanta_fed",
    )
    assert pair_sources(PAIRS["USDAMD"]) == (
        "frankfurter_cba",
        "fred",
        "cba_rates",
        "fed_rss",
        "cba_news",
        "atlanta_fed",
    )
    assert pair_sources(PAIRS["EURAMD"]) == (
        "frankfurter_cba",
        "fred",
        "ecb_data_portal",
        "cba_rates",
        "fed_rss",
        "ecb_rss",
        "cba_news",
        "atlanta_fed",
    )


def test_drivers_missing_keys_map_to_none():
    d = drivers_from_features({}, banks=("FED", "ECB"))
    assert d.rate_diff_bps is None
    assert d.forward_rate is None
    assert d.garch_vol_annual is None
    assert d.served_reason is None
    # Per-bank panels always list the pair's banks, with None when unknown.
    assert d.last_surprise_bps == {"FED": None, "ECB": None}
    assert d.hawkish_score == {"FED": None, "ECB": None}
    assert d.days_to_next_meeting == {"FED": None, "ECB": None}
    assert d.policy_rates == {"FED": None, "ECB": None}


def test_drivers_map_every_features_json_key():
    d = drivers_from_features(
        {
            "rate_diff_bps": 162.5,
            "rate_diff_change_21d_bps": -25,
            "policy_rates": {"FED": 3.875, "ECB": 2.0},
            "forward_rate": "1.1631",
            "garch_vol_annual": 0.071,
            "horizon_sigma": 0.0205,
            "event_extra_variance": 4e-05,
            "last_surprise_bps": {"FED": 0.0, "ECB": None},
            "hawkish_score": {"FED": 0.25, "ECB": -0.4},
            "days_to_next_meeting": {"FED": 7.0, "ECB": None},
            "served_reason": "forward beats random walk",
            "model_inputs": {"ignored": True},
        },
        banks=("FED", "ECB"),
    )
    assert d.rate_diff_bps == 162.5
    assert d.rate_diff_change_21d_bps == -25.0
    assert d.policy_rates == {"FED": 3.875, "ECB": 2.0}
    assert d.forward_rate == pytest.approx(1.1631)
    assert d.garch_vol_annual == 0.071
    assert d.horizon_sigma == 0.0205
    assert d.event_extra_variance == 4e-05
    assert d.last_surprise_bps == {"FED": 0.0, "ECB": None}
    assert d.hawkish_score == {"FED": 0.25, "ECB": -0.4}
    assert d.days_to_next_meeting == {"FED": 7, "ECB": None}
    assert d.served_reason == "forward beats random walk"


def test_drivers_tolerate_malformed_values():
    d = drivers_from_features(
        {
            "rate_diff_bps": "n/a",
            "forward_rate": True,
            "garch_vol_annual": float("inf"),
            "hawkish_score": [0.1],
            "last_surprise_bps": {"FED": "x"},
        }
    )
    assert d.rate_diff_bps is None
    assert d.forward_rate is None
    assert d.garch_vol_annual is None
    assert d.hawkish_score == {}
    assert d.last_surprise_bps == {"FED": None}


def test_prometheus_label_escaping():
    assert escape_label('a"b\\c\nd') == 'a\\"b\\\\c\\nd'


def test_render_metrics_text_format():
    text = render_metrics(
        [
            JobSample(
                job="forecast",
                duration_s=12.5,
                rows_written=6,
                status="success",
                last_success=dt.datetime(2026, 10, 21, 16, 0, tzinfo=dt.UTC),
            ),
            JobSample(
                job="fred", duration_s=None, rows_written=None, status=None, last_success=None
            ),
        ],
        [
            SourceStatus(
                source="fred",
                label="FRED",
                last_success=None,
                last_run=None,
                last_status=None,
                stale=True,
            )
        ],
    )
    assert "# TYPE fxf_job_last_duration_seconds gauge" in text
    assert 'fxf_job_last_duration_seconds{job="forecast"} 12.5' in text
    assert 'fxf_job_last_rows_written{job="forecast"} 6' in text
    assert 'fxf_job_last_status{job="forecast"} 1' in text
    ts = dt.datetime(2026, 10, 21, 16, 0, tzinfo=dt.UTC).timestamp()
    assert f'fxf_job_last_success_timestamp_seconds{{job="forecast"}} {ts:.1f}' in text
    assert 'fxf_source_stale{source="fred"} 1' in text
    # A job that never finished has no samples (absent, not zero).
    assert 'job="fred"' not in text
    assert text.endswith("\n")


def _routes(app):
    """Flattened routes; FastAPI >= 0.150 nests included routers instead of copying them."""
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # pragma: no cover - older FastAPI
        return list(app.routes)
    return list(iter_route_contexts(app.routes))


def test_api_exposes_only_get_routes(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html>")
    app = create_app(frontend_dist=tmp_path)  # include the SPA fallback route too
    paths = set()
    for route in _routes(app):
        assert route.methods is not None and route.methods <= {"GET", "HEAD"}, route.path
        paths.add(route.path)
    assert all(p.startswith("/api/") for p in paths - {"/{full_path:path}"}), paths
    assert {
        "/api/pairs",
        "/api/rates/{pair}",
        "/api/forecasts/{pair}/latest",
        "/api/forecasts/{pair}",
        "/api/backtests/{pair}",
        "/api/events",
        "/api/health",
        "/api/metrics",
    } <= paths


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_write_methods_are_rejected(method):
    client = TestClient(create_app(frontend_dist=None))
    assert getattr(client, method)("/api/pairs").status_code == 405


def test_pairs_lists_pairs_and_horizons():
    # /api/pairs reads only constants, so it needs no database.
    body = TestClient(create_app(frontend_dist=None)).get("/api/pairs").json()
    assert body["horizons"] == [
        {"days": 1, "label": "1D"},
        {"days": 5, "label": "1W"},
        {"days": 21, "label": "1M"},
    ]
    assert body["pairs"] == [
        {
            "id": "EURUSD",
            "base": "EUR",
            "quote": "USD",
            "source": "frankfurter_ecb",
            "source_label": "ECB reference rate",
            "banks": ["FED", "ECB"],
        },
        {
            "id": "USDAMD",
            "base": "USD",
            "quote": "AMD",
            "source": "frankfurter_cba",
            "source_label": "CBA daily average rate",
            "banks": ["FED", "CBA"],
        },
        {
            "id": "EURAMD",
            "base": "EUR",
            "quote": "AMD",
            "source": "frankfurter_cba",
            "source_label": "CBA daily average rate",
            "banks": ["FED", "ECB", "CBA"],
        },
    ]

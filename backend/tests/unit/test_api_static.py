"""Middleware and the single-page app mount: CORS, GZip, static files, SPA fallback."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fxf.api.main import create_app


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><div id=root></div>")
    (d / "assets" / "app-1234.js").write_text("console.log('fxf')")
    (d / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("outside dist")
    return d


@pytest.fixture
def spa(dist: Path) -> TestClient:
    return TestClient(create_app(frontend_dist=dist))


def test_index_served_at_root(spa):
    r = spa.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "id=root" in r.text
    assert r.headers["cache-control"] == "no-cache"


def test_static_files_served(spa):
    r = spa.get("/assets/app-1234.js")
    assert r.status_code == 200
    assert r.text == "console.log('fxf')"
    assert "immutable" in r.headers["cache-control"]
    assert spa.get("/favicon.svg").text == "<svg/>"


def test_client_side_routes_fall_back_to_index(spa):
    for path in ("/pair/EURUSD", "/events", "/backtest/USDAMD/21"):
        r = spa.get(path)
        assert r.status_code == 200, path
        assert "id=root" in r.text


def test_missing_asset_is_404_not_index(spa):
    assert spa.get("/assets/missing-999.js").status_code == 404


def test_api_routes_take_precedence(spa):
    assert spa.get("/api/pairs").json()["pairs"][0]["id"] == "EURUSD"
    r = spa.get("/api/does-not-exist")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert spa.get("/api").status_code == 404


def test_files_outside_dist_are_never_served(spa):
    r = spa.get("/..%2Fsecret.txt")
    assert "outside dist" not in r.text


def test_without_dist_root_is_404():
    client = TestClient(create_app(frontend_dist=None))
    assert client.get("/").status_code == 404
    assert client.get("/api/pairs").status_code == 200


def test_missing_dist_directory_is_ignored(tmp_path: Path):
    client = TestClient(create_app(frontend_dist=tmp_path / "nope"))
    assert client.get("/").status_code == 404


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_cors_allows_the_vite_dev_server(origin):
    client = TestClient(create_app(frontend_dist=None))
    r = client.get("/api/pairs", headers={"Origin": origin})
    assert r.headers["access-control-allow-origin"] == origin
    pre = client.options(
        "/api/pairs", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
    )
    assert pre.status_code == 200
    assert pre.headers["access-control-allow-origin"] == origin


def test_cors_rejects_other_origins():
    client = TestClient(create_app(frontend_dist=None))
    r = client.get("/api/pairs", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_gzip_for_large_responses():
    client = TestClient(create_app(frontend_dist=None))
    r = client.get("/api/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    assert r.json()["info"]["title"]

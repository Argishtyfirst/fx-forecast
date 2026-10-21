"""FR-17 AI view: Gemini client, daily job, point-in-time context, live track record."""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from fxf import http
from fxf.ai import gemini
from fxf.ai.context import build_context
from fxf.ai.track import track_record
from fxf.ai.view import ai_view_for_pair, run_ai_view, run_ai_view_job
from fxf.api.main import create_app
from fxf.constants import EURAMD, HORIZONS, MODEL_LLM, PAIRS
from fxf.models import Forecast, JobRun, Rate, utcnow

RUN = dt.date(2026, 10, 21)
TARGET = {1: dt.date(2026, 10, 22), 5: dt.date(2026, 10, 28), 21: dt.date(2026, 11, 19)}
URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(http, "sleep", lambda _s: None)


def gemini_reply(horizons: list[dict]) -> httpx.Response:
    text = json.dumps({"horizons": horizons})
    return httpx.Response(
        200, json={"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}
    )


def answer(prob: float = 0.58, change: float = 0.3, confidence: str = "medium") -> list[dict]:
    return [
        {
            "days": h,
            "prob_higher": prob,
            "expected_change_pct": change,
            "confidence": confidence,
            "reasoning": "CBA meets on 3 Nov and the policy-rate gap is stable.",
        }
        for h in HORIZONS
    ]


def served_row(
    pair: str, h: int, spot: float, run: dt.date = RUN, target: dt.date | None = None
) -> Forecast:
    w = {1: 0.005, 5: 0.013, 21: 0.03}[h] * spot
    return Forecast(
        run_date=run,
        pair=pair,
        horizon_days=h,
        target_date=target or TARGET[h],
        model="random_walk",
        model_version="rw1",
        spot=Decimal(str(spot)),
        center=Decimal(str(spot)),
        q025=Decimal(str(spot - 2 * w)),
        q10=Decimal(str(spot - w)),
        q25=Decimal(str(spot - w / 2)),
        q75=Decimal(str(spot + w / 2)),
        q90=Decimal(str(spot + w)),
        q975=Decimal(str(spot + 2 * w)),
        served=True,
        meetings_in_horizon=[{"bank": "CBA", "date": "2026-11-03"}],
        git_sha="t",
        features_json={
            "spot_date": RUN.isoformat(),
            "policy_rates": {"CBA": 6.75, "ECB": 2.5, "FED": 3.875},
            "served_reason": "no model beats the random walk",
        },
    )


def seed(session: Session, pairs=tuple(PAIRS)) -> None:
    spots = {"EURUSD": 1.1215, "USDAMD": 361.4, "EURAMD": 405.92}
    for pair in pairs:
        for i in range(120):
            d = RUN - dt.timedelta(days=119 - i)
            session.add(
                Rate(
                    pair=pair,
                    date=d,
                    rate=Decimal(str(spots[pair])),
                    source="t",
                    fetched_at=utcnow(),
                )
            )
        for h in HORIZONS:
            session.add(served_row(pair, h, spots[pair]))
    session.commit()


@respx.mock
def test_gemini_sends_key_in_header_not_url_and_parses_json():
    route = respx.post(URL).mock(return_value=gemini_reply(answer()))
    out = gemini.generate_json("ctx", {"type": "OBJECT"}, model="gemini-test", api_key="k-123")
    assert out["horizons"][0]["prob_higher"] == 0.58
    req = route.calls.last.request
    assert req.headers["x-goog-api-key"] == "k-123"
    assert "k-123" not in str(req.url)
    body = json.loads(req.content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["temperature"] == 0


@respx.mock
def test_gemini_unknown_shape_and_non_json_answers_fail_loudly():
    respx.post(URL).mock(
        side_effect=[
            httpx.Response(200, json={"promptFeedback": {"blockReason": "OTHER"}}),
            httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "sure!"}]}}]}),
        ]
    )
    with pytest.raises(http.SchemaError):
        gemini.generate_json("ctx", {}, model="gemini-test", api_key="k")
    with pytest.raises(http.SchemaError, match="not JSON"):
        gemini.generate_json("ctx", {}, model="gemini-test", api_key="k")


@respx.mock
def test_fr17_ai_view_is_stored_as_unserved_llm_rows(session):
    seed(session)
    respx.post(URL).mock(return_value=gemini_reply(answer()))
    assert run_ai_view(session, RUN, api_key="k", model="gemini-test") == 9

    rows = session.scalars(select(Forecast).where(Forecast.model == MODEL_LLM)).all()
    assert len(rows) == 9 and not any(r.served for r in rows)
    served = session.scalars(select(Forecast).where(Forecast.served.is_(True))).all()
    assert len(served) == 9  # the statistical forecast is untouched
    for r in rows:
        qs = [float(getattr(r, c)) for c in ("q025", "q10", "q25", "center", "q75", "q90", "q975")]
        assert qs == sorted(qs)
        llm = r.features_json["llm"]
        assert (llm["provider"], llm["model"], llm["prompt_version"]) == (
            "gemini",
            "gemini-test",
            "ai-p3",
        )
        assert r.model_version == "gemini-test@ai-p3"
        assert len(llm["context_sha256"]) == 64

    # Idempotent: a rerun replaces the rows instead of adding more.
    run_ai_view(session, RUN, api_key="k", model="gemini-test")
    assert len(session.scalars(select(Forecast).where(Forecast.model == MODEL_LLM)).all()) == 9


@respx.mock
def test_fr17_ai_answer_is_kept_consistent_and_inside_the_band(session):
    seed(session, ("EURAMD",))
    respx.post(URL).mock(return_value=gemini_reply(answer(prob=0.99, change=-9.0)))
    rows = ai_view_for_pair(session, EURAMD, RUN, api_key="k", model="gemini-test")
    for r in rows:
        llm = r["features_json"]["llm"]
        assert llm["prob_higher"] == 0.95  # clamped
        assert llm["expected_change_pct"] == 0.0  # sign disagreed with the probability
        assert llm["adjusted"] is True


@respx.mock
def test_fr17_ai_answer_missing_a_horizon_is_rejected(session):
    seed(session, ("EURAMD",))
    respx.post(URL).mock(return_value=gemini_reply(answer()[:2]))
    with pytest.raises(http.SchemaError, match="horizons"):
        ai_view_for_pair(session, EURAMD, RUN, api_key="k", model="gemini-test")


def test_fr17_ai_job_is_off_without_a_key(clean_db, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from fxf.config import get_settings

    get_settings.cache_clear()
    assert run_ai_view_job(clean_db, run_date=RUN) is True
    with Session(clean_db) as s:
        assert s.scalars(select(JobRun)).all() == []


def test_nfr03_ai_context_uses_only_data_up_to_the_spot_date(session):
    seed(session, ("EURAMD",))
    session.add(
        Rate(
            pair="EURAMD",
            date=RUN + dt.timedelta(days=3),
            rate=Decimal("999"),
            source="t",
            fetched_at=utcnow(),
        )
    )
    session.commit()
    served = session.scalars(
        select(Forecast).where(Forecast.pair == "EURAMD", Forecast.served.is_(True))
    ).all()
    ctx = build_context(session, EURAMD, RUN, list(served))
    assert ctx["recent_moves"]["max_90d"] == pytest.approx(405.92)
    assert "999" not in json.dumps(ctx)


def test_ai_context_leaves_out_the_statistical_verdict(session):
    """An independent read: no served model, served reason or backtest scores to echo."""
    seed(session, ("EURAMD",))
    served = session.scalars(
        select(Forecast).where(Forecast.pair == "EURAMD", Forecast.served.is_(True))
    ).all()
    text = json.dumps(build_context(session, EURAMD, RUN, list(served)))
    for anchor in ("served_model", "served_reason", "backtest", "random_walk", "no model beats"):
        assert anchor not in text
    ctx = build_context(session, EURAMD, RUN, list(served))
    assert set(ctx["related_pairs"]) == {"EUR/USD", "USD/AMD"}
    assert ctx["history"]["low_52w"] == pytest.approx(405.92)


def _llm_history(session: Session, n: int, good: bool) -> None:
    """n daily 5-day forecasts on a rate rising 0.2% a day; a good AI view expects the rise."""
    start = dt.date(2025, 1, 1)
    days = [start + dt.timedelta(days=i) for i in range(n + 10)]
    rate = {d: 400.0 * (1.002**i) for i, d in enumerate(days)}
    for d, r in rate.items():
        session.add(
            Rate(
                pair="EURAMD",
                date=d,
                rate=Decimal(str(round(r, 6))),
                source="t",
                fetched_at=utcnow(),
            )
        )
    for i in range(n):
        run, target = days[i], days[i + 5]
        row = served_row("EURAMD", 5, rate[run], run=run, target=target)
        row.model, row.served, row.model_version = MODEL_LLM, False, "gemini-test@ai-p3"
        lift = 1.008 if good else 1.0
        row.center = Decimal(str(round(rate[run] * lift, 6)))
        row.features_json = {"llm": {"prob_higher": 0.7 if good else 0.5}}
        session.add(row)
    session.commit()


def test_fr17_ai_track_record_counts_only_past_targets(session):
    _llm_history(session, 30, good=True)
    tr = track_record(session, "EURAMD", 5)
    assert tr.n_scored == 30 and tr.required == 250
    assert tr.promoted is False  # far fewer than 250 live forecasts
    assert tr.hit_rate == 1.0 and tr.brier == pytest.approx(0.09)


def test_fr17_ai_is_promoted_only_after_250_live_forecasts_that_beat_the_random_walk(session):
    _llm_history(session, 260, good=True)
    tr = track_record(session, "EURAMD", 5)
    assert tr.n_scored == 250 and tr.promoted is True
    assert tr.mae_ratio_rw < 0.98 and tr.dm_pvalue < 0.10


def test_fr17_a_new_prompt_version_starts_its_track_record_from_zero(session):
    _llm_history(session, 260, good=True)
    assert track_record(session, "EURAMD", 5, model_version="gemini-test@ai-p3").n_scored == 250
    assert track_record(session, "EURAMD", 5, model_version="gemini-test@ai-p4").n_scored == 0


@respx.mock
def test_fr17_latest_forecast_shows_the_ai_view_beside_the_statistical_verdict(clean_db):
    with Session(clean_db) as s:
        seed(s)
        respx.post(URL).mock(return_value=gemini_reply(answer(prob=0.62, change=0.4)))
        run_ai_view(s, RUN, api_key="k", model="gemini-test")
    body = TestClient(create_app(frontend_dist=None)).get("/api/forecasts/EURAMD/latest").json()
    h = body["horizons"][-1]
    assert h["ai_view"]["prob_better_if_wait"] == 0.62
    assert h["ai_view"]["lean"] == "wait"
    assert h["ai_view"]["center"] == pytest.approx(405.92 * 1.004)
    lo, hi = h["ai_view"]["band80"]
    assert lo < h["ai_view"]["center"] < hi
    assert h["ai_view"]["track_record"] == {
        "n_scored": 0,
        "required": 250,
        "hit_rate": None,
        "mae_ratio_rw": None,
        "dm_pvalue": None,
        "brier": None,
        "promoted": False,
    }
    # Unproven, so the statistical answer still decides.
    assert h["signal"]["verdict_source"] == "statistical"
    assert h["signal"]["action"] == "no_edge"


@respx.mock
def test_fr17_ai_lean_treats_45_percent_as_sell_now(clean_db):
    with Session(clean_db) as s:
        seed(s)
        respx.post(URL).mock(return_value=gemini_reply(answer(prob=0.45, change=-0.2)))
        run_ai_view(s, RUN, api_key="k", model="gemini-test")
    body = TestClient(create_app(frontend_dist=None)).get("/api/forecasts/EURAMD/latest").json()
    assert {h["ai_view"]["lean"] for h in body["horizons"]} == {"sell_now"}


@respx.mock
def test_gemini_asks_for_thinking_and_ignores_thought_summaries():
    text = json.dumps({"horizons": answer()})
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": "Weighing the Fed meeting against the CBA path...",
                                    "thought": True,
                                },
                                {"text": text},
                            ]
                        }
                    }
                ]
            },
        )
    )
    out = gemini.generate_json("ctx", {}, model="gemini-test", api_key="k", thinking_level="high")
    assert out["horizons"][0]["days"] == 1
    body = json.loads(route.calls.last.request.content)
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "high"}


@respx.mock
def test_gemini_falls_back_to_default_thinking_when_the_level_is_rejected():
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(400, json={"error": {"message": "Unknown field"}}),
            gemini_reply(answer()),
        ]
    )
    out = gemini.generate_json("ctx", {}, model="gemini-test", api_key="k", thinking_level="high")
    assert len(out["horizons"]) == 3
    assert "thinkingConfig" not in json.loads(route.calls.last.request.content)["generationConfig"]


@respx.mock
def test_ai_view_records_the_thinking_level(session):
    seed(session, ("EURAMD",))
    respx.post(URL).mock(return_value=gemini_reply(answer()))
    rows = ai_view_for_pair(session, EURAMD, RUN, api_key="k", model="gemini-test", thinking="high")
    assert {r["features_json"]["llm"]["thinking"] for r in rows} == {"high"}


@respx.mock
def test_gemini_calls_are_spaced_and_retried_for_the_free_tier(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(http, "sleep", waits.append)
    monkeypatch.setattr(gemini, "_last_call", 0.0)
    respx.post(URL).mock(
        side_effect=[httpx.Response(503), gemini_reply(answer()), gemini_reply(answer())]
    )
    gemini.generate_json("ctx", {}, model="gemini-test", api_key="k")
    gemini.generate_json("ctx", {}, model="gemini-test", api_key="k")
    assert waits[0] == gemini.BACKOFF_BASE_S  # the 503 waits 5s before retrying
    assert 0 < waits[1] <= gemini.MIN_INTERVAL_S  # the second call is spaced from the first


@respx.mock
def test_fr17_ai_view_falls_back_to_the_lite_model_when_the_main_one_is_overloaded(
    session, monkeypatch
):
    monkeypatch.setattr(gemini, "RETRIES", 0)
    seed(session, ("EURAMD",))
    lite = URL.replace("gemini-test", "gemini-lite")
    respx.post(URL).mock(
        return_value=httpx.Response(503, json={"error": {"message": "The model is overloaded."}})
    )
    respx.post(lite).mock(return_value=gemini_reply(answer()))
    rows = ai_view_for_pair(
        session, EURAMD, RUN, api_key="k", model="gemini-test", fallback_model="gemini-lite"
    )
    llm = rows[0]["features_json"]["llm"]
    assert (llm["model"], llm["fallback_from"]) == ("gemini-lite", "gemini-test")
    assert rows[0]["model_version"] == "gemini-lite@ai-p3"


@respx.mock
def test_gemini_failure_message_carries_the_api_explanation(monkeypatch):
    monkeypatch.setattr(gemini, "RETRIES", 0)
    respx.post(URL).mock(
        return_value=httpx.Response(
            429, json={"error": {"message": "Quota exceeded for metric requests per day"}}
        )
    )
    with pytest.raises(http.SourceError, match="Quota exceeded"):
        gemini.generate_json("ctx", {}, model="gemini-test", api_key="k")

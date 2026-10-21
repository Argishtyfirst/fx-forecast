"""Weekly report: models, AI track record and pipeline health, written as Markdown."""

import datetime as dt
from decimal import Decimal

from fxf.models import BacktestMetric, Forecast, JobRun, Rate, utcnow
from fxf.report import build_report, write_report

RUN = dt.date(2026, 10, 21)


def _forecast(model: str, served: bool, features: dict) -> Forecast:
    d = Decimal
    return Forecast(
        run_date=RUN,
        pair="EURAMD",
        horizon_days=21,
        target_date=dt.date(2026, 11, 19),
        model=model,
        model_version="gemini-test@ai-p2" if model == "llm" else "rw1",
        spot=d("405.92"),
        center=d("405.3"),
        q025=d("390"),
        q10=d("397"),
        q25=d("401"),
        q75=d("410"),
        q90=d("415"),
        q975=d("420"),
        served=served,
        meetings_in_horizon=[],
        git_sha="t",
        features_json=features,
    )


def seed(session) -> None:
    session.add(
        Rate(pair="EURAMD", date=RUN, rate=Decimal("405.92"), source="t", fetched_at=utcnow())
    )
    session.add(_forecast("random_walk", True, {}))
    session.add(_forecast("llm", False, {"llm": {"prob_higher": 0.45, "confidence": "medium"}}))
    for model, ratio in (("random_walk", 1.0), ("lightgbm", 0.982)):
        session.add(
            BacktestMetric(
                run_date=RUN,
                pair="EURAMD",
                horizon_days=21,
                model=model,
                window="250d",
                n_obs=250,
                mae=1.0,
                mae_ratio_rw=ratio,
                hit_rate=None,
                cov50=0.564,
                cov80=0.812,
                cov95=0.96,
                pinball=1.0,
                dm_pvalue=0.43 if model == "lightgbm" else None,
            )
        )
    session.add(
        JobRun(
            job="backtest",
            started_at=utcnow(),
            finished_at=utcnow(),
            status="success",
            rows_written=48,
        )
    )
    session.commit()


def test_report_covers_models_ai_view_and_health(session):
    seed(session)
    text = build_report(session, RUN)
    assert text.startswith("# Weekly report, 2026-10-21")
    assert "Statistical estimate. Not financial advice." in text
    assert "| EUR/AMD | 1M | random_walk | 81.2% | 56.4% | 96.0% | lightgbm (0.982, 0.43) |" in text
    assert "| EUR/AMD | 1M | Sell now (2026-10-21) | 45% | medium | 0 of 250 |" in text
    assert "Model and prompt: gemini-test@ai-p2." in text
    assert "| backtest |" in text and "| ai_view | never | never ran |" in text
    assert "—" not in text and "–" not in text


def test_report_handles_an_empty_database(session):
    text = build_report(session, RUN)
    assert "No backtest has run yet." in text
    assert "The AI view has not run yet" in text


def test_write_report_writes_the_dated_file_and_latest(session, tmp_path):
    seed(session)
    paths = write_report(session, tmp_path / "reports", RUN)
    assert [p.name for p in paths] == ["2026-10-21.md", "latest.md"]
    assert paths[0].read_text() == paths[1].read_text()

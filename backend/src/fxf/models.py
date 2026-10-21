"""The 7 Postgres tables (spec: Data model).

Rates and quantiles use NUMERIC(18,8). All timestamps are timezone-aware UTC.
Writers must be idempotent: use `fxf.models.upsert` (INSERT .. ON CONFLICT).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

NUM = Numeric(18, 8)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    pass


class Rate(Base):
    """Daily reference rate history. pair is EURUSD, USDAMD, or a feature series (RUBAMD)."""

    __tablename__ = "rates"

    pair: Mapped[str] = mapped_column(String(12), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    rate: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MacroSeries(Base):
    """Point-in-time macro data. A feature on day t may only use rows with published_at <= cutoff."""

    __tablename__ = "macro_series"

    series_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    value: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    published_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CbMeeting(Base):
    """Meeting calendar. scheduled=False marks unscheduled (emergency) meetings."""

    __tablename__ = "cb_meetings"

    bank: Mapped[str] = mapped_column(String(8), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    scheduled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class CbEvent(Base):
    """One row per central bank decision (FR-05).

    rate_type / rate_before / rate_after hold the headline policy rate
    (constants.BANK_POLICY_RATE). rates_json holds every rate of the decision,
    e.g. for the CBA {"refinancing": {"before": 7.0, "after": 6.75}, "lombard": ..., "deposit": ...}.
    Rates are in percent; surprise_bps is (rate_after - expected) * 100.
    """

    __tablename__ = "cb_events"
    __table_args__ = (UniqueConstraint("bank", "date", name="uq_cb_events_bank_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bank: Mapped[str] = mapped_column(String(8), nullable=False)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    rate_type: Mapped[str] = mapped_column(String(20), nullable=False)
    rate_before: Mapped[Decimal | None] = mapped_column(NUM)
    rate_after: Mapped[Decimal | None] = mapped_column(NUM)
    expected: Mapped[Decimal | None] = mapped_column(NUM)
    expected_source: Mapped[str | None] = mapped_column(String(40))
    surprise_bps: Mapped[float | None] = mapped_column(Float)
    rates_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    statement_url: Mapped[str | None] = mapped_column(Text)
    statement_text: Mapped[str | None] = mapped_column(Text)
    # {"added": [sentences], "removed": [sentences], "previous_event_id": int | None}
    statement_diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    hawkish_score: Mapped[float | None] = mapped_column(Float)
    hawkish_reason: Mapped[str | None] = mapped_column(Text)
    # "<scorer model name>@<prompt version>", e.g. "claude-haiku-5-5@p1" or "lexicon@v1" (FR-07)
    scorer_version: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[str | None] = mapped_column(String(40))
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )


class Forecast(Base):
    """Every model output, not only the served one (spec: Data model).

    Quantiles are rates (not returns). meetings_in_horizon is a list of
    {"bank": "ECB", "date": "YYYY-MM-DD"}. features_json follows the contract in
    fxf.forecast.types.FEATURES_JSON_KEYS.
    """

    __tablename__ = "forecasts"
    __table_args__ = (
        UniqueConstraint(
            "run_date", "pair", "horizon_days", "model", name="uq_forecasts_run_pair_h_model"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    pair: Mapped[str] = mapped_column(String(12), nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    target_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    model: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str] = mapped_column(String(40), nullable=False)
    spot: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    center: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    q025: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    q10: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    q25: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    q75: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    q90: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    q975: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    served: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meetings_in_horizon: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    git_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )


class BacktestMetric(Base):
    """Walk-forward metrics per pair, horizon, model and window ("250d" or "full")."""

    __tablename__ = "backtest_metrics"

    run_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    pair: Mapped[str] = mapped_column(String(12), primary_key=True)
    horizon_days: Mapped[int] = mapped_column(Integer, primary_key=True)
    model: Mapped[str] = mapped_column(String(32), primary_key=True)
    window: Mapped[str] = mapped_column(String(8), primary_key=True)
    n_obs: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[dt.date | None] = mapped_column(Date)
    end_date: Mapped[dt.date | None] = mapped_column(Date)
    mae: Mapped[float] = mapped_column(Float, nullable=False)
    mae_ratio_rw: Mapped[float] = mapped_column(Float, nullable=False)
    hit_rate: Mapped[float | None] = mapped_column(Float)
    cov50: Mapped[float] = mapped_column(Float, nullable=False)
    cov80: Mapped[float] = mapped_column(Float, nullable=False)
    cov95: Mapped[float] = mapped_column(Float, nullable=False)
    pinball: Mapped[float] = mapped_column(Float, nullable=False)
    # Pinball loss of GARCH-only bands (random walk center, no event widening) on the same dates.
    pinball_ref: Mapped[float | None] = mapped_column(Float)
    dm_pvalue: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )


class JobRun(Base):
    """Pipeline health. job is a source key (constants.SOURCES) or a pipeline job name."""

    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(12), nullable=False)  # running|success|failed
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_s: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


def upsert(
    session: Session,
    model: type[Base],
    rows: list[dict[str, Any]],
    conflict_cols: list[str],
    update_cols: list[str] | None = None,
) -> int:
    """INSERT .. ON CONFLICT. With update_cols=None, existing rows are left untouched.

    Returns the number of rows passed (inserted or updated). Chunks large batches.
    """
    if not rows:
        return 0
    table = model.__table__
    n = 0
    for i in range(0, len(rows), 2000):
        chunk = rows[i : i + 2000]
        stmt = insert(table).values(chunk)
        if update_cols:
            stmt = stmt.on_conflict_do_update(
                index_elements=conflict_cols,
                set_={c: getattr(stmt.excluded, c) for c in update_cols},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=conflict_cols)
        session.execute(stmt)
        n += len(chunk)
    return n


class AiAnalysis(Base):
    """Written AI analyses (fxf.ai.analysis), e.g. the weekly reading of the meeting study.

    An eighth table beside the spec's seven: free text with its model and prompt version,
    one row per kind, pair and run date.
    """

    __tablename__ = "ai_analyses"
    __table_args__ = (
        UniqueConstraint("kind", "pair", "run_date", name="uq_ai_analyses_kind_pair_run"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    pair: Mapped[str] = mapped_column(String(12), nullable=False)
    run_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )


class ProviderQuote(Base):
    """Indicative retail rates from Armenian banks and money apps (fxf.quotes), for "the best
    place to convert today". A ninth table beside the spec's seven; kept 30 days.

    buy is what the provider pays you per 1 base unit when you sell the base (AMD per EUR when
    you sell euros); sell is what you pay per 1 base unit when you buy it. Fees, where the
    provider has a published formula, are fee_fixed (in the base currency) plus fee_pct of
    the amount, taken before conversion. Banks quote a spread and no fee.
    """

    __tablename__ = "provider_quotes"
    __table_args__ = (
        UniqueConstraint(
            "provider", "pair", "channel", "fetched_at", name="uq_provider_quotes_p_pair_ch_at"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # bank | app | transfer
    pair: Mapped[str] = mapped_column(String(12), nullable=False)
    channel: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # cash | non_cash | card | transfer
    buy: Mapped[Decimal | None] = mapped_column(NUM, nullable=True)
    sell: Mapped[Decimal | None] = mapped_column(NUM, nullable=True)
    fee_fixed: Mapped[Decimal | None] = mapped_column(NUM, nullable=True)
    fee_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    quoted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

"""Job bodies for the events pipeline. Each function runs inside fxf.jobs.run_job and takes
(ctx, engine, now); fxf.events.pipeline decides when each one runs.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final

import pandas as pd
from sqlalchemy import Engine, select

from fxf import http
from fxf.constants import (
    ATLFED_SERIES,
    SOURCE_CBA,
    SOURCE_CBA_NEWS,
    SOURCE_ECB_RSS,
    SOURCE_FED_RSS,
)
from fxf.data_access import load_macro_frame
from fxf.db import session_scope
from fxf.events import atlanta, calendar, cba, ecb, fed
from fxf.events.calendar import Meeting
from fxf.events.decisions import (
    EXPECTED_ATLFED,
    EXPECTED_PREVIOUS,
    Decision,
    latest_event,
    refresh_diffs,
    set_statement,
    stored_events,
    surprise_bps,
    upsert_events,
)
from fxf.events.text import parse_ecb_rates, parse_fed_target_range
from fxf.jobs import RunContext
from fxf.logging_setup import get_logger
from fxf.models import CbEvent, MacroSeries, upsert, utcnow

log = get_logger(__name__)

# Decisions per bank whose statement text the backfill fetches (spec asks for >= 12).
STATEMENT_BACKFILL_N: Final = 16
LIVE_LOOKBACK: Final = dt.timedelta(days=7)


# --- helpers -------------------------------------------------------------------------------------


def macro_series(engine: Engine | None, series_id: str) -> pd.Series:
    with session_scope(engine) as s:
        frame = load_macro_frame(s, series_id)
    if frame.empty:
        return pd.Series(dtype="float64")
    return frame["value"].astype("float64")


def _after_rates(ev: CbEvent | None) -> dict[str, float | None] | None:
    if ev is None or not ev.rates_json:
        return None
    return {k: (v or {}).get("after") for k, v in ev.rates_json.items()}


def _previous_rates(
    engine: Engine | None, bank: str, day: dt.date, fallback: dict[str, str]
) -> dict[str, float | None]:
    """Rates in force before `day`: the previous event's rates, else the macro series as-of."""
    prev = _after_rates(latest_event(engine, bank, before=day))
    if prev:
        return prev
    out: dict[str, float | None] = {}
    for key, series_id in fallback.items():
        out[key] = fed.asof(macro_series(engine, series_id), day - dt.timedelta(days=1))
    return out


def _ensure_meeting(engine: Engine | None, bank: str, day: dt.date, url: str | None) -> None:
    """A detected decision on a date missing from the calendar is an unscheduled meeting."""
    known = {m.date for m in calendar.stored_meetings(engine, bank)}
    if day not in known:
        calendar.store_meetings(engine, [Meeting(bank, day, False, url)])


def _has_statement(engine: Engine | None, bank: str, day: dt.date) -> bool:
    with session_scope(engine) as s:
        ev = s.scalars(select(CbEvent).where(CbEvent.bank == bank, CbEvent.date == day)).first()
        return bool(ev and ev.statement_text)


# --- calendars --------------------------------------------------------------------------------------


def refresh_fed_calendar(
    ctx: RunContext, engine: Engine | None, now: dt.datetime, *, full: bool = False
) -> None:
    meetings = calendar.fetch_fed_meetings(full=full)
    ctx.rows_written += calendar.store_meetings(engine, meetings)
    ctx.meta["meetings"] = len(meetings)


def refresh_ecb_calendar(
    ctx: RunContext, engine: Engine | None, now: dt.datetime, *, full: bool = False
) -> None:
    pairs = calendar.fetch_ecb_meetings(full=full, today=now.date())
    ctx.rows_written += calendar.store_meetings(engine, [m for m, _ in pairs])
    ctx.meta["meetings"] = len(pairs)


def refresh_cba_calendar(ctx: RunContext, engine: Engine | None, now: dt.datetime) -> None:
    today = now.astimezone(cba.YEREVAN).date()
    future = [m for m in cba.fetch_calendar() if m.date >= today]
    ctx.rows_written += calendar.store_meetings(engine, future)
    ctx.meta["future_meetings"] = len(future)


# --- Fed ---------------------------------------------------------------------------------------------


def fed_expected(engine: Engine | None, day: dt.date) -> float | None:
    return fed.expected_from_tracker(macro_series(engine, ATLFED_SERIES), day)


def poll_fed(ctx: RunContext, engine: Engine | None, now: dt.datetime) -> None:
    """FR-05: record each FOMC statement seen in the RSS feed in the last 7 days."""
    items = fed.parse_rss(SOURCE_FED_RSS, http.fetch_text(SOURCE_FED_RSS, fed.RSS_URL, ext="xml"))
    found = []
    for item in items:
        if not fed.is_fomc_statement(item.title):
            continue
        if not (now - LIVE_LOOKBACK <= item.published_at <= now + dt.timedelta(hours=1)):
            continue
        day = fed.item_day(item)
        if _has_statement(engine, "FED", day):
            continue
        st = fed.fetch_statement(item.link)
        rng = parse_fed_target_range(st.text)
        if rng is None:
            raise http.SchemaError(f"{SOURCE_FED_RSS}: no target range in {item.link}")
        before = _previous_rates(engine, "FED", day, {"upper": "DFEDTARU", "lower": "DFEDTARL"})
        if (
            before.get("mid") is None
            and before.get("upper") is not None
            and before.get("lower") is not None
        ):
            before["mid"] = (float(before["upper"]) + float(before["lower"])) / 2  # type: ignore[arg-type]
        d = Decision(
            "FED",
            day,
            before=before,
            after=fed.rates_from_range(*rng),
            source=SOURCE_FED_RSS,
            published_at=item.published_at,
            statement_url=item.link,
            statement_text=st.text,
        )
        exp = fed_expected(engine, day)
        if exp is not None:
            d.expected, d.expected_source = exp, EXPECTED_ATLFED
        ctx.rows_written += upsert_events(engine, [d], created_at=now)
        _ensure_meeting(engine, "FED", day, item.link)
        found.append(day.isoformat())
    if found:
        refresh_diffs(engine, "FED")
    ctx.meta.update({"items": len(items), "decisions": found})


def fed_history(ctx: RunContext, engine: Engine | None, now: dt.datetime) -> None:
    upper, lower = macro_series(engine, "DFEDTARU"), macro_series(engine, "DFEDTARL")
    if upper.empty or lower.empty:
        upper, lower = fed.fetch_fredgraph("DFEDTARU"), fed.fetch_fredgraph("DFEDTARL")
        ctx.meta["rates_from"] = "fredgraph"
    decisions = fed.history_decisions(
        calendar.stored_meetings(engine, "FED"),
        upper,
        lower,
        macro_series(engine, ATLFED_SERIES),
        now.date(),
    )
    ctx.rows_written += upsert_events(engine, decisions, keep_existing_source=True)
    ctx.meta["decisions"] = len(decisions)


# --- ECB ----------------------------------------------------------------------------------------------


def poll_ecb(ctx: RunContext, engine: Engine | None, now: dt.datetime) -> None:
    """FR-05: record each "Monetary policy decisions" release seen in the press RSS."""
    items = ecb.parse_feed(http.fetch_text(SOURCE_ECB_RSS, ecb.RSS_URL, ext="xml"))
    found = []
    for item in items:
        if not ecb.is_decision(item.title):
            continue
        if not (now - LIVE_LOOKBACK <= item.published_at <= now + dt.timedelta(hours=1)):
            continue
        day = ecb.item_day(item)
        if _has_statement(engine, "ECB", day):
            continue
        link = item.link.replace("europa.eu//", "europa.eu/")
        st = ecb.fetch_decision_page(link)
        after = parse_ecb_rates(st.text)
        if "deposit" not in after:
            raise http.SchemaError(f"{SOURCE_ECB_RSS}: no deposit facility rate in {link}")
        before = _previous_rates(engine, "ECB", day, {"deposit": "ECB_DFR"})
        d = Decision(
            "ECB",
            day,
            before=before,
            after={k: after.get(k) for k in ("deposit", "mro", "mlf")},
            source=SOURCE_ECB_RSS,
            published_at=item.published_at,
            statement_url=link,
            statement_text=st.text,
        )
        ctx.rows_written += upsert_events(engine, [d], created_at=now)
        _ensure_meeting(engine, "ECB", day, link)
        found.append(day.isoformat())
    if found:
        refresh_diffs(engine, "ECB")
    ctx.meta.update({"items": len(items), "decisions": found})


def ecb_history(ctx: RunContext, engine: Engine | None, now: dt.datetime) -> None:
    series: dict[str, pd.Series] = {}
    for name in ecb.FM_KEYS:
        try:
            series[name] = ecb.fetch_fm(name, start=dt.date(2007, 1, 1))
        except http.SourceError as exc:
            if name == "deposit":
                raise
            ctx.meta.setdefault("missing_series", []).append(f"{name}: {exc}")
    decisions = ecb.history_decisions(calendar.stored_meetings(engine, "ECB"), series, now.date())
    ctx.rows_written += upsert_events(engine, decisions, keep_existing_source=True)
    ctx.meta["decisions"] = len(decisions)


# --- CBA ----------------------------------------------------------------------------------------------


def cba_decision_events(decisions: list[cba.CbaDecision]) -> list[Decision]:
    out = []
    prev: cba.CbaDecision | None = None
    for d in sorted(decisions, key=lambda x: x.decision_date):
        before = prev.rates() if prev else {"refinancing": None, "lombard": None, "deposit": None}
        out.append(
            Decision(
                "CBA",
                d.decision_date,
                before=before,
                after=d.rates(),
                source=SOURCE_CBA,
                published_at=d.announced_at,
                statement_url=None,
            )
        )
        prev = d
    return out


def write_cba_rates(
    engine: Engine | None, decisions: list[cba.CbaDecision], now: dt.datetime
) -> int:
    rows = cba.macro_rows(decisions, now)
    with session_scope(engine) as s:
        return upsert(
            s,
            MacroSeries,
            rows,
            ["series_id", "date"],
            ["value", "published_at", "source", "fetched_at"],
        )


def cba_rates(ctx: RunContext, engine: Engine | None, now: dt.datetime) -> None:
    """CBA_REFI / CBA_LOMBARD / CBA_DEPOSIT plus the CBA decision events.

    The curated history is merged with the live export (trusted from cba.LIVE_FROM), so a
    decision the export shows but the news poll missed still becomes an event. A decision the
    news poll already recorded keeps its announcement time and statement.
    """
    seed = cba.load_decisions()
    seed_dates = {d.decision_date for d in seed}
    meeting_dates = {m.date for m in calendar.stored_meetings(engine, "CBA")} | seed_dates
    live = cba.clean_rate_history(cba.fetch_rates_export(), meeting_dates)
    with session_scope(engine) as s:
        announced = {
            ev.date: ev.published_at
            for ev in s.scalars(
                select(CbEvent).where(CbEvent.bank == "CBA", CbEvent.published_at.is_not(None))
            )
            if ev.date not in seed_dates
        }
    merged = [
        cba.CbaDecision(
            d.decision_date,
            d.effective_date,
            d.refinancing,
            d.lombard,
            d.deposit,
            d.scheduled,
            announced.get(d.decision_date) or d.announced_at,
            d.source_url,
        )
        for d in cba.merge_live(seed, live)
    ]
    new = [d for d in merged if d.decision_date not in seed_dates]
    ctx.rows_written += write_cba_rates(engine, merged, now)
    ctx.rows_written += upsert_events(
        engine, cba_decision_events(merged), keep_existing_source=True
    )
    calendar.store_meetings(
        engine, [m for m in cba.decision_meetings(new) if m.date not in meeting_dates]
    )
    ctx.meta.update(
        {
            "decisions": len(merged),
            "live_rows": len(live),
            "new_vs_seed": [d.decision_date.isoformat() for d in new],
        }
    )


def cba_meeting_days(engine: Engine | None, now: dt.datetime) -> list[dt.date]:
    """CBA meeting dates that are today or yesterday in Yerevan."""
    today = now.astimezone(cba.YEREVAN).date()
    return [
        m.date
        for m in calendar.stored_meetings(engine, "CBA")
        if today - dt.timedelta(days=1) <= m.date <= today
    ]


def _cba_from_fallback(day: dt.date) -> tuple[dict[str, float], cba.NewsItem, str] | None:
    for name, url in (("arka", cba.ARKA_RSS_URL), ("interfax", cba.INTERFAX_RSS_URL)):
        try:
            items = cba.parse_news_feed(name, http.fetch_text(SOURCE_CBA_NEWS, url, ext="xml"))
        except http.SourceError as exc:
            log.warning("cba news fallback failed", extra={"source": name, "error": str(exc)})
            continue
        for item in items:
            if item.published_at.astimezone(cba.YEREVAN).date() != day:
                continue
            rates = cba.news_decision(item)
            if rates:
                return rates, item, name
    return None


def poll_cba(ctx: RunContext, engine: Engine | None, now: dt.datetime) -> None:
    """FR-05 for the CBA, on meeting days: cba.am press releases, then ARKA, then Interfax."""
    days = [d for d in cba_meeting_days(engine, now) if not _has_statement(engine, "CBA", d)]
    ctx.meta["meeting_days"] = [d.isoformat() for d in days]
    if not days:
        return
    primary_error: Exception | None = None
    try:
        items = cba.parse_press_list(http.fetch_text(SOURCE_CBA_NEWS, cba.PRESS_URL))
    except http.SourceError as exc:
        primary_error, items = exc, []
    found = []
    for day in days:
        hit = next(
            (
                i
                for i in items
                if cba.is_rate_decision(i.title)
                and i.published_at.astimezone(cba.YEREVAN).date() == day
            ),
            None,
        )
        before = _previous_rates(
            engine,
            "CBA",
            day,
            {"refinancing": "CBA_REFI", "lombard": "CBA_LOMBARD", "deposit": "CBA_DEPOSIT"},
        )
        decision: Decision | None = None
        if hit is not None:
            try:
                release = cba.parse_release(http.fetch_text(SOURCE_CBA_NEWS, hit.url), hit.url)
                rates = cba.decision_from_release(release)
                decision = Decision(
                    "CBA",
                    day,
                    before=before,
                    after={k: rates.get(k) for k in ("refinancing", "lombard", "deposit")},
                    source=SOURCE_CBA_NEWS,
                    published_at=hit.published_at,
                    statement_url=hit.url,
                    statement_text=cba.statement_text(release),
                )
            except http.SourceError as exc:
                primary_error = exc
        if decision is None:
            fb = _cba_from_fallback(day)
            if fb is not None:
                rates, item, name = fb
                decision = Decision(
                    "CBA",
                    day,
                    before=before,
                    after={k: rates.get(k) for k in ("refinancing", "lombard", "deposit")},
                    source=f"{SOURCE_CBA_NEWS}:{name}",
                    published_at=item.published_at,
                    statement_url=item.link,
                )
        if decision is None:
            continue
        ctx.rows_written += upsert_events(engine, [decision], created_at=now)
        # Make the new refinancing rate visible to the forecast engine right away.
        assert decision.published_at is not None
        partial = cba.CbaDecision(
            day,
            day + dt.timedelta(days=1),
            float(decision.after["refinancing"]),  # type: ignore[arg-type]
            decision.after.get("lombard"),
            decision.after.get("deposit"),
            True,
            decision.published_at,
            decision.statement_url,
        )
        ctx.rows_written += write_cba_rates(engine, [partial], now)
        found.append(f"{day.isoformat()} via {decision.source}")
    if found:
        refresh_diffs(engine, "CBA")
    ctx.meta["decisions"] = found
    if primary_error is not None and not found:
        raise primary_error


def cba_history(ctx: RunContext, engine: Engine | None, now: dt.datetime) -> None:
    events = cba_decision_events(cba.load_decisions())
    ctx.rows_written += upsert_events(engine, events, keep_existing_source=True)
    ctx.meta["decisions"] = len(events)


# --- Atlanta Fed --------------------------------------------------------------------------------------


def apply_fed_expectations(engine: Engine | None, atl: pd.Series) -> int:
    """Use the tracker's expectation for every FED event it covers."""
    n = 0
    with session_scope(engine) as s:
        for ev in s.scalars(select(CbEvent).where(CbEvent.bank == "FED")):
            exp = fed.expected_from_tracker(atl, ev.date)
            if exp is None:
                if ev.expected_source is None and ev.rate_before is not None:
                    ev.expected, ev.expected_source = ev.rate_before, EXPECTED_PREVIOUS
                    ev.surprise_bps = surprise_bps(_f(ev.rate_after), _f(ev.rate_before))
                continue
            ev.expected = round(exp, 8)  # type: ignore[assignment]
            ev.expected_source = EXPECTED_ATLFED
            ev.surprise_bps = surprise_bps(_f(ev.rate_after), exp)
            n += 1
    return n


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def atlanta_fed(ctx: RunContext, engine: Engine | None, now: dt.datetime) -> None:
    mpt = atlanta.fetch_mpt()
    try:
        sofr = atlanta.fetch_sofr(mpt["date"].min() - dt.timedelta(days=10), now.date())
    except http.SourceError as exc:
        sofr = pd.Series(dtype="float64")
        ctx.meta["sofr_error"] = str(exc)[:300]
    fomc = [m.date for m in calendar.stored_meetings(engine, "FED") if m.scheduled]
    series = atlanta.expected_series(mpt, sofr, fomc)
    with session_scope(engine) as s:
        ctx.rows_written += upsert(
            s,
            MacroSeries,
            atlanta.macro_rows(series, now),
            ["series_id", "date"],
            ["value", "published_at", "source", "fetched_at"],
        )
    ctx.meta.update(
        {
            "observations": len(series),
            "first": series.index.min().date().isoformat() if len(series) else None,
            "last": series.index.max().date().isoformat() if len(series) else None,
            "fed_events_with_tracker": apply_fed_expectations(engine, series),
        }
    )


# --- statements ----------------------------------------------------------------------------------------


def _fetch_fed_text(ev: CbEvent) -> tuple[str, str]:
    url = (
        ev.statement_url
        if ev.statement_url and "pressreleases/monetary" in ev.statement_url
        else fed.statement_url(ev.date)
    )
    return url, fed.fetch_statement(url).text


def _ecb_urls(engine: Engine | None) -> dict[dt.date, str]:
    return {
        m.date: m.source_url
        for m in calendar.stored_meetings(engine, "ECB")
        if m.source_url and "/press/pr/" in m.source_url
    }


def _cba_urls() -> dict[dt.date, str]:
    return {
        d.decision_date: d.source_url
        for d in cba.load_decisions()
        if d.source_url and ("press-releases" in d.source_url or cba.is_old_site(d.source_url))
    }


def backfill_statements(
    ctx: RunContext,
    engine: Engine | None,
    now: dt.datetime,
    bank: str,
    n: int = STATEMENT_BACKFILL_N,
) -> None:
    events = [e for e in stored_events(engine, bank) if e.date <= now.date()][-n:]
    urls = _ecb_urls(engine) if bank == "ECB" else _cba_urls() if bank == "CBA" else {}
    done, failed = 0, []
    for ev in events:
        if ev.statement_text:
            continue
        try:
            if bank == "FED":
                url, text = _fetch_fed_text(ev)
            elif bank == "ECB":
                url = urls.get(ev.date) or ""
                if not url:
                    failed.append(f"{ev.date}: no release URL")
                    continue
                text = ecb.fetch_decision_page(url).text
            else:
                url = urls.get(ev.date) or ""
                if not url:
                    failed.append(f"{ev.date}: no release URL")
                    continue
                text = cba.statement_text(
                    cba.parse_release(http.fetch_text(SOURCE_CBA_NEWS, url), url)
                )
        except http.SourceError as exc:
            failed.append(f"{ev.date}: {exc}"[:200])
            continue
        if set_statement(engine, bank, ev.date, url, text):
            done += 1
    ctx.rows_written += done
    ctx.rows_written += refresh_diffs(engine, bank)
    ctx.meta.update({"bank": bank, "statements": done, "failed": failed[:10]})
    if failed and not done:
        raise http.SourceError(f"{bank} statements: all {len(failed)} fetches failed: {failed[0]}")


def utc_now() -> dt.datetime:
    return utcnow()

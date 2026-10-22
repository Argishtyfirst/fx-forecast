"""Weekly AI analysis of the meeting study and the around-meetings backtest, per pair.

Gemini reads how the pair moved around each bank's meetings over the last year
(fxf.events.study), how the served statistical bands did on meeting weeks against other
weeks (backtest windows "evt_*"), the overall calibration, the meetings coming up and the AI
view's own live record, and writes a short note: a headline, 2 to 4 points and what to
watch next. It is written text for the Backtest view, not a forecast, and it is stored in
ai_analyses with its model and prompt version.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final

from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from fxf import http
from fxf.ai.gemini import generate_json_with_fallback
from fxf.ai.track import track_record
from fxf.config import get_settings
from fxf.constants import (
    HORIZON_LABELS,
    HORIZONS,
    JOB_AI_ANALYSIS,
    MODEL_LLM,
    MODEL_RW,
    PAIRS,
    PairSpec,
)
from fxf.data_access import load_rates
from fxf.db import session_scope
from fxf.events.study import load_study
from fxf.jobs import job_run
from fxf.logging_setup import get_logger
from fxf.models import AiAnalysis, BacktestMetric, CbMeeting, Forecast, upsert, utcnow

log = get_logger(__name__)

KIND: Final = "event_study"
PROMPT_VERSION: Final = "an-p3"

SYSTEM: Final = """You are a foreign-exchange analyst writing a short weekly note for one \
person who converts {base} into {quote} and wants to understand central bank meetings. The \
JSON context holds: how this pair moved around each bank's meetings over the last year (the \
reaction from the last fix before the decision to the first fix after, against a normal day, \
and how often it followed the surprise or the statement's tone); how the statistical \
forecast's 80% ranges did on weeks with a meeting against other weeks (target: 75 to 85% of \
outcomes inside); the meetings coming up; and the AI view's own live record.

Write for a busy reader who must get the point in 5 seconds.
- headline: THE takeaway as one plain sentence of at most 22 words, with the key number. Not a \
title. Example: "Fed weeks are where the ranges fail: EUR/USD moved 2.1x a normal day and the 1-week \
range held 57% of outcomes."
- for_you: what this means for someone converting {base} into {quote}, at most 28 words, in \
practical terms (how wide to expect the swing around the next meeting). Never tell anyone to \
buy, sell or wait.
- points: 2 or 3 facts, each at most 22 words, each with a number from the context.
- watch_next: the next meetings inside the coming month with their dates, at most 22 words.
Always write numbers as digits with % or x (57%, 2.1x), never in words. Say when a sample is \
small (a year holds about 8 meetings per bank). Use commas and periods, never dashes.
Then give the same note in Armenian (hy) and Russian (ru): natural, correct prose a native \
reader would write, the same facts and numbers, standard names (Fed: ՖՌՀ / ФРС, ECB: ԵԿԲ / ЕЦБ, \
CBA: ՀՀ ԿԲ / ЦБ РА)."""

TEXT_SCHEMA: Final[dict[str, Any]] = {
    "type": "OBJECT",
    "properties": {
        "headline": {"type": "STRING"},
        "for_you": {"type": "STRING"},
        "points": {"type": "ARRAY", "items": {"type": "STRING"}},
        "watch_next": {"type": "STRING"},
    },
    "required": ["headline", "for_you", "points", "watch_next"],
}
RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "OBJECT",
    "properties": {
        "headline": {"type": "STRING"},
        "for_you": {"type": "STRING"},
        "points": {"type": "ARRAY", "items": {"type": "STRING"}},
        "watch_next": {"type": "STRING"},
        "hy": TEXT_SCHEMA,
        "ru": TEXT_SCHEMA,
    },
    "required": ["headline", "for_you", "points", "watch_next", "hy", "ru"],
}


class NoteText(BaseModel):
    headline: str = Field(default="", max_length=600)
    for_you: str = Field(default="", max_length=800)
    points: list[str] = Field(default_factory=list, max_length=6)
    watch_next: str = Field(default="", max_length=1200)


class Note(BaseModel):
    headline: str = Field(min_length=3, max_length=300)
    for_you: str = Field(min_length=3, max_length=400)
    points: list[str] = Field(min_length=1, max_length=6)
    watch_next: str = Field(min_length=3, max_length=600)
    hy: NoteText | None = None
    ru: NoteText | None = None


NOTE = TypeAdapter(Note)


def _clean(text: str) -> str:
    """The UI rule: no em or en dashes in visible text."""
    return " ".join(text.replace("—", ", ").replace("–", "-").split())


def _event_backtest(session: Session, pair: str) -> list[dict[str, Any]]:
    run_date = session.scalar(
        select(func.max(BacktestMetric.run_date)).where(BacktestMetric.pair == pair)
    )
    if run_date is None:
        return []
    rows = session.scalars(
        select(BacktestMetric).where(
            BacktestMetric.pair == pair,
            BacktestMetric.run_date == run_date,
            BacktestMetric.model == MODEL_RW,
            BacktestMetric.window.in_(["250d", "evt_FED", "evt_ECB", "evt_CBA", "evt_none"]),
        )
    ).all()
    return [
        {
            "horizon": HORIZON_LABELS.get(r.horizon_days, f"{r.horizon_days}D"),
            "subset": {"250d": "all weeks"}.get(r.window, r.window.replace("evt_", "meeting of ")),
            "n": r.n_obs,
            "band80_coverage": round(r.cov80, 3),
            "band50_coverage": round(r.cov50, 3),
            "mean_abs_error_vs_random_walk": round(r.mae_ratio_rw, 3),
        }
        for r in sorted(rows, key=lambda r: (r.horizon_days, r.window))
    ]


def _upcoming(session: Session, pair: PairSpec, today: dt.date) -> list[dict[str, str]]:
    rows = session.scalars(
        select(CbMeeting)
        .where(
            CbMeeting.bank.in_(list(pair.banks)),
            CbMeeting.date > today,
            CbMeeting.date <= today + dt.timedelta(days=60),
        )
        .order_by(CbMeeting.date)
    ).all()
    return [{"bank": m.bank, "date": m.date.isoformat()} for m in rows]


def _ai_record(session: Session, pair: str) -> list[dict[str, Any]]:
    rates = load_rates(session, pair)
    out = []
    for h in HORIZONS:
        version = session.scalar(
            select(Forecast.model_version)
            .where(Forecast.pair == pair, Forecast.horizon_days == h, Forecast.model == MODEL_LLM)
            .order_by(Forecast.run_date.desc())
            .limit(1)
        )
        tr = track_record(session, pair, h, rates, version)
        out.append({"horizon": HORIZON_LABELS[h], "scored": tr.n_scored, "hit_rate": tr.hit_rate})
    return out


def build_context(session: Session, pair: PairSpec, as_of: dt.date) -> dict[str, Any]:
    summaries, reactions = load_study(session, pair, as_of)
    return {
        "pair": f"{pair.base}/{pair.quote}",
        "as_of": as_of.isoformat(),
        "meeting_reactions_last_year": [
            {
                "bank": s.bank,
                "meetings": s.n,
                "mean_abs_reaction_pct": s.mean_abs_reaction_pct,
                "normal_day_abs_move_pct": s.normal_abs_move_pct,
                "reaction_vs_normal": s.reaction_ratio,
                "mean_run_up_pct": s.mean_run_up_pct,
                "mean_follow_pct": s.mean_follow_pct,
                "followed_signal": f"{round((s.consistency or 0) * s.n_signed)} of {s.n_signed}"
                if s.n_signed
                else "no expected direction",
            }
            for s in summaries
        ],
        "recent_meetings": [
            {
                "bank": r.bank,
                "date": r.date.isoformat(),
                "surprise_bps": r.surprise_bps,
                "tone": r.hawkish_score,
                "run_up_pct": r.run_up_pct,
                "reaction_pct": r.reaction_pct,
                "follow_pct": r.follow_pct,
            }
            for r in reactions[-10:]
        ],
        "statistical_bands_around_meetings": _event_backtest(session, pair.id),
        "upcoming_meetings": _upcoming(session, pair, as_of),
        "ai_view_live_record": _ai_record(session, pair.id),
    }


def analyse_pair(
    session: Session, pair: PairSpec, run_date: dt.date, *, api_key: str, models: list[str]
) -> dict[str, Any]:
    import json

    as_of = (
        session.scalar(select(func.max(Forecast.run_date)).where(Forecast.pair == pair.id))
        or run_date
    )
    ctx = build_context(session, pair, as_of)
    session.commit()  # release the connection during the slow model call
    raw, used = generate_json_with_fallback(
        f"Context:\n{json.dumps(ctx, default=str, separators=(',', ':'))}\n\nWrite the note.",
        RESPONSE_SCHEMA,
        models=models,
        api_key=api_key,
        system=SYSTEM.format(base=pair.base, quote=pair.quote),
        thinking_level="low",
    )
    note: Note = http.validate("gemini", raw, NOTE)
    return {
        "kind": KIND,
        "pair": pair.id,
        "run_date": run_date,
        "model": used,
        "prompt_version": PROMPT_VERSION,
        "content": {
            "headline": _clean(note.headline),
            "for_you": _clean(note.for_you),
            "points": [_clean(p) for p in note.points[:3]],
            "watch_next": _clean(note.watch_next),
            "i18n": {
                lang: {
                    "headline": _clean(text.headline),
                    "for_you": _clean(text.for_you),
                    "points": [_clean(p) for p in text.points[:3]],
                    "watch_next": _clean(text.watch_next),
                }
                for lang, text in (("hy", note.hy), ("ru", note.ru))
                if text is not None and text.headline
            },
            "generated_at": utcnow().isoformat(),
            "provider": "gemini",
        },
        "created_at": utcnow(),
    }


def run_ai_analysis_job(engine: Engine | None = None, *, run_date: dt.date | None = None) -> bool:
    """Job `ai_analysis`. Off without GEMINI_API_KEY (nothing runs or is recorded)."""
    s = get_settings()
    if not s.gemini_api_key:
        log.info("ai analysis off: GEMINI_API_KEY is not set")
        return True
    day = run_date or dt.date.today()
    models = [s.fxf_ai_model, s.fxf_ai_fallback_model]
    try:
        with job_run(JOB_AI_ANALYSIS, engine=engine, meta={"models": models}) as run:
            errors = []
            for pair in PAIRS.values():
                with session_scope(engine) as session:
                    try:
                        row = analyse_pair(
                            session, pair, day, api_key=s.gemini_api_key, models=models
                        )
                    except Exception as exc:  # one pair failing must not lose the others
                        errors.append(f"{pair.id}: {exc}")
                        continue
                    run.rows_written += upsert(
                        session,
                        AiAnalysis,
                        [row],
                        ["kind", "pair", "run_date"],
                        ["model", "prompt_version", "content", "created_at"],
                    )
            if errors:
                raise RuntimeError("; ".join(errors))
        return True
    except Exception:
        return False

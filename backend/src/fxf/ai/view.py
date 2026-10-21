"""Daily AI view job: one Gemini call per pair, stored as model "llm" next to the
statistical forecasts (never served; fxf.api.signal decides whether it may lead).

The answer gives, per horizon, P(rate higher at the target), an expected change, a
confidence and a reason. The stored row uses the LLM's expected change as its center and
the served GARCH bands re-centred on it, like every other center model (spec: Forecasting
models), so it can be scored on exactly the same metrics.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal
from typing import Any, Final, Literal

from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from fxf import http
from fxf.ai.context import build_context
from fxf.ai.gemini import generate_json
from fxf.config import get_settings, git_sha
from fxf.constants import HORIZONS, JOB_AI, MODEL_LLM, PAIRS, QUANTILE_COLUMNS, PairSpec
from fxf.db import session_scope
from fxf.jobs import job_run
from fxf.logging_setup import get_logger
from fxf.models import Forecast, upsert, utcnow

log = get_logger(__name__)

PROVIDER: Final = "gemini"
PROMPT_VERSION: Final = "ai-p3"
PROB_BOUNDS: Final = (0.05, 0.95)

# ai-p2: an independent read. ai-p1 showed the model the statistical verdict and told it to
# stay near 0.5, and it simply echoed the random walk. ai-p3: thinking on (settings
# fxf_ai_thinking) and up to three sentences of reasoning that say how the drivers net out.
SYSTEM: Final = """You are an experienced foreign-exchange analyst giving your own independent \
read on one currency pair. The JSON context holds spot, recent moves, a year of month-end \
closes, related pairs, policy rates and their recent path, central bank meetings inside each \
horizon, each bank's last decision and its new statement sentences, and a statistical risk \
range per horizon (how far the rate typically moves, not a direction).

For each horizon, estimate the probability that the rate on the target date will be HIGHER \
than spot, the expected change in percent, your confidence, and why. Form your own view from \
the drivers: trend and momentum, interest-rate differentials and the direction of policy, the \
likely outcome and surprise of meetings inside the horizon, the tone of recent statements, how \
the related pairs and the CBA's managed float have behaved, and anything else in the context. \
Commit to a lean when you see one; use 0.50 only when you genuinely see none.

Stay honest about uncertainty: exchange rates are hard to predict, so probabilities beyond \
0.35-0.65 need strong, specific reasons. The expected change must have the same sign as \
(probability - 0.5) and stay inside the 80% risk band. Confidence: "low" for a weak lean, \
"medium" for one clear reason, "high" for several reasons that agree. Think it through before \
answering. Reasoning: at most three sentences that name the specific drivers, which way each \
points, and how they net out. Describe the forecast; never tell anyone what to do."""

RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "OBJECT",
    "properties": {
        "horizons": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "days": {"type": "INTEGER"},
                    "prob_higher": {"type": "NUMBER"},
                    "expected_change_pct": {"type": "NUMBER"},
                    "confidence": {"type": "STRING", "enum": ["low", "medium", "high"]},
                    "reasoning": {"type": "STRING"},
                },
                "required": [
                    "days",
                    "prob_higher",
                    "expected_change_pct",
                    "confidence",
                    "reasoning",
                ],
            },
        }
    },
    "required": ["horizons"],
}


class HorizonAnswer(BaseModel):
    days: int
    prob_higher: float = Field(ge=0.0, le=1.0)
    expected_change_pct: float
    confidence: Literal["low", "medium", "high"]
    reasoning: str = Field(min_length=1, max_length=1200)


class Answer(BaseModel):
    horizons: list[HorizonAnswer]


ANSWER = TypeAdapter(Answer)


def model_version(model: str) -> str:
    return f"{model}@{PROMPT_VERSION}"


def _served_rows(session: Session, pair: str, run_date: dt.date) -> list[Forecast]:
    return list(
        session.scalars(
            select(Forecast).where(
                Forecast.pair == pair, Forecast.run_date == run_date, Forecast.served.is_(True)
            )
        ).all()
    )


def _consistent(h: HorizonAnswer, row: Forecast) -> tuple[float, float, bool]:
    """Clamp the probability, force the expected change to agree with it in sign, and keep
    the implied center inside the served 80% band. Returns (prob, change_pct, adjusted)."""
    p = min(max(h.prob_higher, PROB_BOUNDS[0]), PROB_BOUNDS[1])
    spot = float(row.spot)
    change = h.expected_change_pct
    adjusted = p != h.prob_higher
    if (p - 0.5) * change < 0 or abs(p - 0.5) < 1e-9:
        change, adjusted = 0.0, adjusted or change != 0.0
    lo = (float(row.q10) / spot - 1.0) * 100.0
    hi = (float(row.q90) / spot - 1.0) * 100.0
    clamped = min(max(change, lo), hi)
    return p, clamped, adjusted or clamped != change


def _row(row: Forecast, ans: HorizonAnswer, ctx_digest: str, model: str) -> dict[str, Any]:
    prob, change, adjusted = _consistent(ans, row)
    spot = float(row.spot)
    center = spot * (1.0 + change / 100.0)
    shift = center / float(row.center)
    quantiles = {
        c: Decimal(str(round(float(getattr(row, c)) * shift, 8))) for c in QUANTILE_COLUMNS
    }
    return {
        "run_date": row.run_date,
        "pair": row.pair,
        "horizon_days": row.horizon_days,
        "target_date": row.target_date,
        "model": MODEL_LLM,
        "model_version": model_version(model),
        "spot": row.spot,
        "center": Decimal(str(round(center, 8))),
        **quantiles,
        "served": False,
        "meetings_in_horizon": row.meetings_in_horizon,
        "git_sha": git_sha(),
        "features_json": {
            "spot_date": (row.features_json or {}).get("spot_date"),
            "llm": {
                "provider": PROVIDER,
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "generated_at": utcnow().isoformat(),
                "prob_higher": round(prob, 4),
                "expected_change_pct": round(change, 4),
                "confidence": ans.confidence,
                "reasoning": ans.reasoning.strip(),
                "adjusted": adjusted,
                "raw": ans.model_dump(),
                "context_sha256": ctx_digest,
            },
        },
        "created_at": utcnow(),
    }


def ai_view_for_pair(
    session: Session,
    pair: PairSpec,
    run_date: dt.date,
    *,
    api_key: str,
    model: str,
    thinking: str | None = None,
) -> list[dict[str, Any]]:
    served = _served_rows(session, pair.id, run_date)
    if not served:
        raise RuntimeError(
            f"no served forecast for {pair.id} on {run_date}; run the forecast job first"
        )
    ctx = build_context(session, pair, run_date, served)
    text = json.dumps(ctx, default=str, separators=(",", ":"))
    digest = hashlib.sha256(text.encode()).hexdigest()
    raw = generate_json(
        f"Context:\n{text}\n\nGive your independent read for horizons (trading days): "
        f"{list(HORIZONS)}.",
        RESPONSE_SCHEMA,
        model=model,
        api_key=api_key,
        system=SYSTEM,
        thinking_level=thinking,
    )
    answer: Answer = http.validate("gemini", raw, ANSWER)
    by_days = {h.days: h for h in answer.horizons}
    if set(by_days) != {r.horizon_days for r in served}:
        raise http.SchemaError(
            f"gemini: answered horizons {sorted(by_days)}, expected {list(HORIZONS)}"
        )
    rows = [_row(r, by_days[r.horizon_days], digest, model) for r in served]
    for row in rows:
        row["features_json"]["llm"]["thinking"] = thinking or "default"
    return rows


def run_ai_view(
    session: Session,
    run_date: dt.date,
    *,
    api_key: str,
    model: str,
    thinking: str | None = None,
) -> int:
    """Write the AI view for every pair. Tries every pair, then raises if any failed."""
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for pair in PAIRS.values():
        try:
            rows.extend(
                ai_view_for_pair(
                    session, pair, run_date, api_key=api_key, model=model, thinking=thinking
                )
            )
        except Exception as exc:  # one pair failing must not lose the others
            log.warning("ai view failed", extra={"pair": pair.id, "error": str(exc)})
            errors.append(f"{pair.id}: {exc}")
    cols = (
        [c for c in rows[0] if c not in {"run_date", "pair", "horizon_days", "model"}]
        if rows
        else []
    )
    written = upsert(session, Forecast, rows, ["run_date", "pair", "horizon_days", "model"], cols)
    session.commit()
    if errors:
        raise RuntimeError("; ".join(errors))
    return written


def latest_served_run_date(session: Session) -> dt.date | None:
    return session.scalar(select(func.max(Forecast.run_date)).where(Forecast.served.is_(True)))


def run_ai_view_job(engine: Engine | None = None, *, run_date: dt.date | None = None) -> bool:
    """Job `ai_view`. Without GEMINI_API_KEY the AI view is off: nothing runs or is recorded."""
    s = get_settings()
    if not s.gemini_api_key:
        log.info("ai view off: GEMINI_API_KEY is not set")
        return True
    try:
        meta = {"model": s.fxf_ai_model, "thinking": s.fxf_ai_thinking or "default"}
        with job_run(JOB_AI, engine=engine, meta=meta) as run:
            with session_scope(engine) as session:
                day = run_date or latest_served_run_date(session)
                if day is None:
                    raise RuntimeError("no served forecast yet")
                run.meta["run_date"] = day.isoformat()
                run.rows_written = run_ai_view(
                    session,
                    day,
                    api_key=s.gemini_api_key,
                    model=s.fxf_ai_model,
                    thinking=s.fxf_ai_thinking or None,
                )
        return True
    except Exception:
        return False

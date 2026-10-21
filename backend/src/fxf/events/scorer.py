"""Hawkish/dovish statement scorer (FR-07), job constants.JOB_SCORE.

Each statement is scored from -1 (dovish) to +1 (hawkish) with a one-line reason, given the
statement text and its sentence diff against the bank's previous statement.

- With GEMINI_API_KEY set (the default in production): Gemini, the same model as the AI view
  (settings.fxf_ai_model, default gemini-3.8-flash) through fxf.ai.gemini, strict JSON
  through a response schema, low thinking, scorer_version "<model>@<PROMPT_VERSION>". Free
  tier, so NFR-07 holds at zero cost.
- Else with ANTHROPIC_API_KEY set: Claude (settings.fxf_scorer_model, default
  claude-haiku-5-5) via the Anthropic SDK, strict JSON through structured outputs.
- Without a key: a deterministic lexicon scorer, scorer_version "lexicon@v1", so the
  pipeline still runs.

When the active scorer_version differs from a stored one, every statement is scored again
(spec: "When the scorer model or prompt changes, the system scores all historical
statements again"). Cost (NFR-07): the statement is cut to MAX_STATEMENT_CHARS and the diff
to MAX_DIFF_SENTENCES per side (about 3k input tokens), effort is "low" and max_tokens
small; at Haiku 5.5 prices ($0.10 / $0.50 per MTok) one call costs under $0.001, so the
roughly 3 decisions a month, and even a full rescore of a few hundred statements, stay far
below 1 USD.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Protocol

from sqlalchemy import Engine, or_, select

from fxf.config import get_settings
from fxf.db import session_scope
from fxf.jobs import RunContext
from fxf.logging_setup import get_logger
from fxf.models import CbEvent

log = get_logger(__name__)

PROMPT_VERSION: Final = "p1"
LEXICON_VERSION: Final = "lexicon@v1"
MAX_STATEMENT_CHARS: Final = 6000
MAX_DIFF_SENTENCES: Final = 15
MAX_TOKENS: Final = 1024  # room for adaptive thinking plus a one-line JSON answer
# Statements scored per run. A full rescore after a scorer change spreads over a few runs
# instead of one long run against a rate-limited free tier.
MAX_PER_RUN: Final = 12

SYSTEM_PROMPT: Final = (
    "You rate central bank monetary policy statements for a currency forecasting model. "
    "Score the policy stance the statement communicates on a scale from -1 (clearly dovish: "
    "easing, cuts, concern about weak growth, signals of lower rates ahead) through 0 (neutral, "
    "balanced or data dependent) to +1 (clearly hawkish: tightening, hikes, concern about "
    "inflation, signals of higher or longer-held rates). Weigh what changed against the "
    "previous statement (added and removed sentences) more than boilerplate. Answer with a "
    'JSON object {"score": number between -1 and 1, "reason": one short line, at most 25 words}.'
)

OUTPUT_SCHEMA: Final = {
    "type": "object",
    "properties": {"score": {"type": "number"}, "reason": {"type": "string"}},
    "required": ["score", "reason"],
    "additionalProperties": False,
}


class ScoreError(ValueError):
    """The scorer returned something that is not a valid score."""


@dataclass(frozen=True)
class Score:
    score: float
    reason: str


class Scorer(Protocol):
    version: str

    def score(self, bank: str, statement: str, diff: dict[str, Any] | None) -> Score: ...


def validate_output(raw: str | dict[str, Any]) -> Score:
    """Parse and validate {"score": -1..1, "reason": "..."}; clamp the score into [-1, 1]."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise ScoreError(f"scorer output is not JSON: {str(raw)[:200]!r}") from exc
    if not isinstance(data, dict) or "score" not in data or "reason" not in data:
        raise ScoreError(f"scorer output lacks score/reason: {str(raw)[:200]!r}")
    try:
        score = float(data["score"])
    except (TypeError, ValueError) as exc:
        raise ScoreError(f"score is not a number: {data['score']!r}") from exc
    if math.isnan(score) or math.isinf(score):
        raise ScoreError("score is not finite")
    reason = re.sub(r"\s+", " ", str(data["reason"])).strip()
    if not reason:
        raise ScoreError("empty reason")
    return Score(max(-1.0, min(1.0, score)), reason[:300])


def build_prompt(bank: str, statement: str, diff: dict[str, Any] | None) -> str:
    text = (
        statement
        if len(statement) <= MAX_STATEMENT_CHARS
        else statement[:MAX_STATEMENT_CHARS] + " [...]"
    )
    added = (diff or {}).get("added") or []
    removed = (diff or {}).get("removed") or []
    parts = [f"Central bank: {bank}", "", "<statement>", text, "</statement>"]
    if diff and diff.get("previous_event_id") is not None:
        parts += [
            "",
            "<added_sentences>",
            *[f"- {s}" for s in added[:MAX_DIFF_SENTENCES]],
            "</added_sentences>",
        ]
        parts += [
            "<removed_sentences>",
            *[f"- {s}" for s in removed[:MAX_DIFF_SENTENCES]],
            "</removed_sentences>",
        ]
    else:
        parts += ["", "(No previous statement to compare against.)"]
    return "\n".join(parts)


class ClaudeScorer:
    """Claude via the Anthropic SDK. `client` is injectable for tests."""

    def __init__(self, model: str, client: Any | None = None, api_key: str | None = None) -> None:
        self.model = model
        self.version = f"{model}@{PROMPT_VERSION}"
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
        self.client = client

    def score(self, bank: str, statement: str, diff: dict[str, Any] | None) -> Score:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(bank, statement, diff)}],
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
        )
        if getattr(response, "stop_reason", None) == "refusal":
            raise ScoreError("scorer declined the request (refusal)")
        text = "".join(
            getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text"
        )
        if not text:
            raise ScoreError(
                f"no text in scorer response (stop_reason={getattr(response, 'stop_reason', None)})"
            )
        return validate_output(text)


GEMINI_SCHEMA: Final = {
    "type": "OBJECT",
    "properties": {"score": {"type": "NUMBER"}, "reason": {"type": "STRING"}},
    "required": ["score", "reason"],
}


class GeminiScorer:
    """Gemini through fxf.ai.gemini (paced and retried for the free tier)."""

    def __init__(self, model: str, api_key: str, thinking: str | None = "low") -> None:
        self.model = model
        self.api_key = api_key
        self.thinking = thinking
        self.version = f"{model}@{PROMPT_VERSION}"

    def score(self, bank: str, statement: str, diff: dict[str, Any] | None) -> Score:
        from fxf.ai.gemini import generate_json

        raw = generate_json(
            build_prompt(bank, statement, diff),
            GEMINI_SCHEMA,
            model=self.model,
            api_key=self.api_key,
            system=SYSTEM_PROMPT,
            thinking_level=self.thinking,
            max_output_tokens=2048,
        )
        return validate_output(raw)


# --- deterministic fallback --------------------------------------------------------------------

_HAWKISH = (
    r"rais(?:e|ed|ing)\b",
    r"increas(?:e|ed|ing) (?:the )?(?:policy|refinancing|target|key|three key)",
    r"hik(?:e|ed|es|ing)\b",
    r"tighten\w*",
    r"restrictive",
    r"inflation(?:ary)? (?:pressures?|risks?) (?:remain|persist|intensif|rose|increas)\w*",
    r"upside risks? to (?:the )?inflation",
    r"elevated inflation|inflation remains (?:elevated|high|above)",
    r"above (?:the )?(?:target|goal)",
    r"higher (?:policy rate|rates)",
    r"further (?:increases|tightening|firming)",
    r"strong(?:er)? (?:demand|growth|labor|labour)",
    r"overheating|excess demand",
    r"vigilant|stand ready to (?:raise|tighten)",
)
_DOVISH = (
    r"lower(?:ed|ing)? (?:the )?(?:policy|refinancing|target|key|three key|deposit)",
    r"reduc(?:e|ed|ing) (?:the )?(?:policy|refinancing|target|key|three key)",
    r"\bcut(?:s|ting)?\b",
    r"eas(?:e|ed|ing)\b",
    r"accommodative|stimulat\w*",
    r"downside risks?",
    r"slow(?:er|ing|ed|down)",
    r"weak(?:er|ening|ness)?",
    r"below (?:the )?(?:target|goal)",
    r"disinflation\w*|deflation\w*",
    r"inflation (?:has )?(?:eased|declined|moderated|fallen|slowed)",
    r"unemployment (?:rate )?(?:has )?(?:risen|rose|moved up|increased)",
    r"lower (?:policy rate|rates)|further (?:reductions|easing|cuts)",
)
# Whole words only ("eased" must not match inside "increased" or "released").
_H = [re.compile(rf"\b(?:{p})\b", re.I) for p in _HAWKISH]
_D = [re.compile(rf"\b(?:{p})\b", re.I) for p in _DOVISH]
# The decision itself weighs most.
_DECISION_WEIGHT: Final = 3
_DECIDED_UP = re.compile(r"\bdecided (?:today )?to (?:raise|increase|hike)\b", re.I)
_DECIDED_DOWN = re.compile(r"\bdecided (?:today )?to (?:lower|reduce|cut|decrease)\b", re.I)


def _count(text: str, pats: list[re.Pattern[str]]) -> tuple[int, list[str]]:
    hits: list[str] = []
    for p in pats:
        hits += [m.group(0).lower() for m in p.finditer(text)]
    return len(hits), hits


class LexiconScorer:
    """Counts hawkish vs dovish phrases; sentences added since the last statement weigh 2x and
    the rate decision itself counts as three phrases."""

    version = LEXICON_VERSION

    def score(self, bank: str, statement: str, diff: dict[str, Any] | None) -> Score:
        text = statement[:MAX_STATEMENT_CHARS]
        h, hh = _count(text, _H)
        d, dd = _count(text, _D)
        added = (
            " ".join((diff or {}).get("added") or [])
            if diff and diff.get("previous_event_id")
            else ""
        )
        if added:
            ah, ahh = _count(added, _H)
            ad, add = _count(added, _D)
            h, d, hh, dd = h + ah, d + ad, hh + ahh, dd + add
        if _DECIDED_UP.search(text):
            h += _DECISION_WEIGHT
            hh.insert(0, "decided to raise")
        if _DECIDED_DOWN.search(text):
            d += _DECISION_WEIGHT
            dd.insert(0, "decided to lower")
        raw = (h - d) / (h + d + 4.0)
        score = round(max(-1.0, min(1.0, raw)), 4)
        top = lambda xs: ", ".join(sorted(set(xs), key=xs.index)[:3]) or "none"  # noqa: E731
        reason = f"lexicon: {h} hawkish ({top(hh)}) vs {d} dovish ({top(dd)}) phrases"
        return Score(score, reason)


def active_scorer(client: Any | None = None) -> Scorer:
    """Gemini when GEMINI_API_KEY is set, else Claude, else the lexicon. `client` injects a
    Claude client in tests."""
    s = get_settings()
    if client is not None:
        return ClaudeScorer(s.fxf_scorer_model, client=client, api_key=s.anthropic_api_key)
    if s.gemini_api_key:
        return GeminiScorer(s.fxf_ai_model, s.gemini_api_key)
    if s.anthropic_api_key:
        return ClaudeScorer(s.fxf_scorer_model, api_key=s.anthropic_api_key)
    return LexiconScorer()


def score_statements(
    ctx: RunContext,
    engine: Engine | None = None,
    *,
    scorer: Scorer | None = None,
    scorer_factory: Callable[[], Scorer] | None = None,
) -> None:
    """Score unscored statements, or all of them when the scorer version changed."""
    scorer = scorer or (scorer_factory or active_scorer)()
    with session_scope(engine) as s:
        stored = {
            v
            for (v,) in s.execute(
                select(CbEvent.scorer_version).where(CbEvent.scorer_version.is_not(None)).distinct()
            )
        }
        ids = list(
            s.scalars(
                select(CbEvent.id)
                .where(
                    CbEvent.statement_text.is_not(None),
                    or_(
                        CbEvent.hawkish_score.is_(None),
                        CbEvent.scorer_version.is_(None),
                        CbEvent.scorer_version != scorer.version,
                    ),
                )
                .order_by(CbEvent.date)
            )
        )
    rescore = bool(stored - {scorer.version})
    ctx.meta.update(
        {"scorer_version": scorer.version, "rescore_all": rescore, "candidates": len(ids)}
    )
    from fxf.ai.gemini import is_transient

    errors: list[str] = []
    ctx.meta["deferred"] = max(0, len(ids) - MAX_PER_RUN)
    for n, event_id in enumerate(ids[:MAX_PER_RUN]):
        with session_scope(engine) as s:
            ev = s.get(CbEvent, event_id)
            if ev is None or not ev.statement_text:
                continue
            try:
                result = scorer.score(ev.bank, ev.statement_text, ev.statement_diff)
            except Exception as exc:
                if is_transient(exc):
                    # Rate limited or overloaded: stop for this run; the rest wait for the next.
                    ctx.meta["deferred"] = len(ids) - n
                    ctx.meta["stopped"] = str(exc)[:300]
                    log.warning("scorer unavailable; deferring", extra={"error": str(exc)})
                    break
                # One bad statement must not block the others.
                errors.append(f"{ev.bank} {ev.date}: {type(exc).__name__}: {exc}")
                log.warning(
                    "statement scoring failed", extra={"event_id": event_id, "error": str(exc)}
                )
                continue
            ev.hawkish_score = result.score
            ev.hawkish_reason = result.reason
            ev.scorer_version = scorer.version
            ctx.rows_written += 1
    if errors:
        ctx.meta["errors"] = errors[:20]
        raise ScoreError(f"{len(errors)} statement(s) could not be scored: {errors[0]}")

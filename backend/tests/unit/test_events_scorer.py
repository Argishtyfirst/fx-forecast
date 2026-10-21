"""Hawkish scorer (FR-07): output validation, lexicon fallback, Claude call shape, rescoring.

No real API calls: the Anthropic client is a stub.
"""

import datetime as dt
from types import SimpleNamespace

import pytest

from fxf.events import scorer as sc
from fxf.events.decisions import Decision, refresh_diffs, stored_events, upsert_events
from fxf.jobs import RunContext


class StubMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text=reply),
            ],
        )


def stub_client(*replies):
    return SimpleNamespace(messages=StubMessages(replies))


@pytest.mark.parametrize(
    ("raw", "score"),
    [
        ('{"score": 0.4, "reason": "raised rates"}', 0.4),
        ('{"score": 3, "reason": "x"}', 1.0),
        ({"score": -7, "reason": "x"}, -1.0),
    ],
)
def test_validate_output_clamps(raw, score):
    assert sc.validate_output(raw).score == score


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"score": "high", "reason": "x"}',
        '{"reason": "x"}',
        '{"score": 0.1, "reason": " "}',
        '{"score": NaN, "reason": "x"}',
    ],
)
def test_validate_output_rejects_bad_shapes(raw):
    with pytest.raises(sc.ScoreError):
        sc.validate_output(raw)


def test_lexicon_scorer_is_deterministic_and_signed():
    s = sc.LexiconScorer()
    hawk = s.score(
        "FED", "The Committee decided to raise the target range. Inflation remains elevated.", None
    )
    dove = s.score(
        "FED",
        "The Committee decided to lower the target range. Downside risks to growth have increased and growth is slowing.",
        None,
    )
    assert hawk.score > 0 > dove.score
    assert s.score("FED", "The Committee decided to raise the target range.", None) == s.score(
        "FED", "The Committee decided to raise the target range.", None
    )
    assert hawk.reason.startswith("lexicon:") and s.version == "lexicon@v1"


def test_claude_scorer_sends_statement_and_diff_with_strict_json_format():
    client = stub_client('{"score": 0.6, "reason": "Hike and hawkish guidance."}')
    s = sc.ClaudeScorer("claude-haiku-5-5", client=client)
    diff = {"added": ["Rates rose."], "removed": ["Rates held."], "previous_event_id": 3}
    out = s.score("ECB", "Rates rose. Inflation is high.", diff)
    assert out == sc.Score(0.6, "Hike and hawkish guidance.")
    (call,) = client.messages.calls
    assert call["model"] == "claude-haiku-5-5"
    assert call["max_tokens"] <= 1024
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["output_config"]["effort"] == "low"
    assert "temperature" not in call  # not accepted by Haiku 5.5
    prompt = call["messages"][0]["content"]
    assert "Rates rose. Inflation is high." in prompt and "- Rates held." in prompt
    assert s.version == "claude-haiku-5-5@p1"


def test_claude_scorer_truncates_long_statements():
    client = stub_client('{"score": 0, "reason": "neutral"}')
    sc.ClaudeScorer("m", client=client).score("CBA", "word " * 5000, None)
    assert len(client.messages.calls[0]["messages"][0]["content"]) < sc.MAX_STATEMENT_CHARS + 500


def test_active_scorer_without_api_key_is_lexicon(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from fxf.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(get_settings(), "anthropic_api_key", None)
    monkeypatch.setattr(get_settings(), "gemini_api_key", None)
    assert sc.active_scorer().version == "lexicon@v1"


def _seed_statements(engine):
    upsert_events(
        engine,
        [
            Decision(
                "FED",
                dt.date(2026, 7, 29),
                {"mid": 3.625},
                {"mid": 3.625},
                statement_text="The Committee decided to maintain the target range.",
            ),
            Decision(
                "FED",
                dt.date(2026, 9, 16),
                {"mid": 3.625},
                {"mid": 3.875},
                statement_text="The Committee decided to raise the target range. Inflation remains elevated.",
            ),
            Decision(
                "ECB", dt.date(2026, 9, 10), {"deposit": 2.25}, {"deposit": 2.5}
            ),  # no text: not scored
        ],
    )
    refresh_diffs(engine)


def _ctx():
    return RunContext(job="score_statements", run_id=0)


def test_fr07_score_stores_model_and_prompt_version(clean_db):
    _seed_statements(clean_db)
    client = stub_client(
        '{"score": -0.2, "reason": "Holds rates, balanced risks."}',
        '{"score": 0.7, "reason": "Hikes; inflation elevated."}',
    )
    ctx = _ctx()
    sc.score_statements(ctx, clean_db, scorer=sc.ClaudeScorer("claude-haiku-5-5", client=client))
    events = {e.date: e for e in stored_events(clean_db, "FED")}
    assert events[dt.date(2026, 9, 16)].hawkish_score == 0.7
    assert events[dt.date(2026, 9, 16)].hawkish_reason == "Hikes; inflation elevated."
    assert {e.scorer_version for e in events.values()} == {"claude-haiku-5-5@p1"}
    assert stored_events(clean_db, "ECB")[0].scorer_version is None
    assert ctx.rows_written == 2 and len(client.messages.calls) == 2
    # The diff goes to the scorer with the statement.
    assert (
        "- The Committee decided to maintain the target range."
        in client.messages.calls[1]["messages"][0]["content"]
    )
    # Already scored with the active version: nothing to do.
    sc.score_statements(_ctx(), clean_db, scorer=sc.ClaudeScorer("claude-haiku-5-5", client=client))
    assert len(client.messages.calls) == 2


def test_changed_scorer_version_rescores_all_history(clean_db):
    _seed_statements(clean_db)
    sc.score_statements(_ctx(), clean_db, scorer=sc.LexiconScorer())
    assert {e.scorer_version for e in stored_events(clean_db, "FED")} == {"lexicon@v1"}
    client = stub_client('{"score": 0.1, "reason": "r"}')
    ctx = _ctx()
    sc.score_statements(ctx, clean_db, scorer=sc.ClaudeScorer("claude-haiku-5-5", client=client))
    assert ctx.meta["rescore_all"] is True and ctx.rows_written == 2
    assert {e.scorer_version for e in stored_events(clean_db, "FED")} == {"claude-haiku-5-5@p1"}
    # A prompt version bump rescores everything again.
    v2 = sc.ClaudeScorer("claude-haiku-5-5", client=client)
    v2.version = "claude-haiku-5-5@p2"
    ctx = _ctx()
    sc.score_statements(ctx, clean_db, scorer=v2)
    assert ctx.rows_written == 2


def test_one_failed_score_does_not_block_others_but_fails_the_job(clean_db):
    _seed_statements(clean_db)
    client = stub_client(RuntimeError("overloaded"), '{"score": 0.3, "reason": "ok"}')
    with pytest.raises(sc.ScoreError):
        sc.score_statements(_ctx(), clean_db, scorer=sc.ClaudeScorer("m", client=client))
    scored = [e for e in stored_events(clean_db, "FED") if e.hawkish_score is not None]
    assert len(scored) == 1


def test_fr07_active_scorer_prefers_gemini_when_its_key_is_set(monkeypatch):
    from fxf.config import get_settings

    monkeypatch.setattr(get_settings(), "gemini_api_key", "g-key")
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "a-key")
    monkeypatch.setattr(get_settings(), "fxf_ai_model", "gemini-3.8-flash")
    scorer = sc.active_scorer()
    assert isinstance(scorer, sc.GeminiScorer)
    assert scorer.version == "gemini-3.8-flash@p1"


def test_fr07_gemini_scorer_returns_a_clamped_score_with_its_version(monkeypatch):
    import json

    import httpx
    import respx

    from fxf import http as fxf_http

    monkeypatch.setattr(fxf_http, "sleep", lambda _s: None)
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
    with respx.mock:
        route = respx.post(url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": json.dumps(
                                            {
                                                "score": 1.7,
                                                "reason": "Signals further hikes to fight inflation.",
                                            }
                                        )
                                    }
                                ]
                            }
                        }
                    ]
                },
            )
        )
        result = sc.GeminiScorer("gemini-test", "g-key").score(
            "FED", "The Committee decided to raise...", None
        )
    assert result.score == 1.0  # clamped
    assert result.reason == "Signals further hikes to fight inflation."
    body = json.loads(route.calls.last.request.content)
    assert body["systemInstruction"]["parts"][0]["text"] == sc.SYSTEM_PROMPT
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}


def test_fr07_an_overloaded_scorer_defers_the_rest_instead_of_failing(session):
    import datetime as dt

    from fxf.http import SourceError
    from fxf.jobs import RunContext
    from fxf.models import CbEvent

    for i in range(3):
        session.add(
            CbEvent(
                bank="FED",
                date=dt.date(2026, 1, 1 + i),
                rate_type="target_mid",
                statement_text=f"Statement {i}.",
            )
        )
    session.commit()

    class Overloaded:
        version = "gemini-test@p1"
        calls = 0

        def score(self, bank, statement, diff):
            self.calls += 1
            if self.calls == 2:
                raise SourceError("gemini: failed after 6 attempts: HTTP 503 (overloaded)")
            return sc.Score(0.2, "Balanced.")

    ctx = RunContext(job="score_statements", run_id=1)
    scorer = Overloaded()
    sc.score_statements(ctx, session.get_bind(), scorer=scorer)  # does not raise
    assert ctx.rows_written == 1
    assert ctx.meta["deferred"] == 2 and "HTTP 503" in ctx.meta["stopped"]
    assert scorer.calls == 2  # stopped at the first overload, did not hammer the rest


def test_fr07_scoring_is_capped_per_run(session):
    import datetime as dt

    from fxf.jobs import RunContext
    from fxf.models import CbEvent

    for i in range(sc.MAX_PER_RUN + 3):
        session.add(
            CbEvent(
                bank="ECB",
                date=dt.date(2025, 1, 1) + dt.timedelta(days=i),
                rate_type="deposit",
                statement_text=f"Text {i}.",
            )
        )
    session.commit()
    ctx = RunContext(job="score_statements", run_id=1)
    sc.score_statements(ctx, session.get_bind(), scorer=sc.LexiconScorer())
    assert ctx.rows_written == sc.MAX_PER_RUN and ctx.meta["deferred"] == 3

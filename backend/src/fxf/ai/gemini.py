"""Gemini generateContent with a JSON response schema.

The API key travels in the x-goog-api-key header, so it never reaches a URL, a log line or
the raw response store.
"""

from __future__ import annotations

import json
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from fxf import http
from fxf.http import SchemaError, SourceError
from fxf.logging_setup import get_logger

log = get_logger(__name__)

SOURCE: Final = "gemini"
URL: Final = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class _Part(BaseModel):
    model_config = ConfigDict(extra="allow")
    text: str | None = None
    thought: bool | None = None  # a thinking summary, not part of the answer


class _Content(BaseModel):
    model_config = ConfigDict(extra="allow")
    parts: list[_Part] = Field(min_length=1)


class _Candidate(BaseModel):
    model_config = ConfigDict(extra="allow")
    content: _Content
    finishReason: str | None = None  # noqa: N815 - API field name


class GenerateContentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    candidates: list[_Candidate] = Field(min_length=1)


def generate_json(
    prompt: str,
    response_schema: dict[str, Any],
    *,
    model: str,
    api_key: str,
    system: str | None = None,
    thinking_level: str | None = None,
    # Room for a reasoning model's thinking tokens, which count toward this limit; billing is
    # on the tokens actually produced.
    max_output_tokens: int = 8192,
) -> Any:
    """One deterministic (temperature 0) call; returns the parsed JSON answer.

    `thinking_level` ("low" | "medium" | "high") asks a thinking model to reason more before
    answering. If the API rejects the setting (HTTP 400), the call is retried once without
    it, so the model's default thinking applies instead of the job failing.
    """
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": max_output_tokens,
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
        },
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if thinking_level:
        body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": thinking_level}
    url = URL.format(model=model)
    headers = {"x-goog-api-key": api_key}
    try:
        resp: GenerateContentResponse = http.post_json(
            SOURCE, url, body, GenerateContentResponse, headers=headers
        )
    except SourceError as exc:
        if not thinking_level or "HTTP 400" not in str(exc):
            raise
        log.warning(
            "thinking level rejected; retrying with the model default", extra={"model": model}
        )
        body["generationConfig"].pop("thinkingConfig")
        resp = http.post_json(SOURCE, url, body, GenerateContentResponse, headers=headers)
    candidate = resp.candidates[0]
    text = "".join(p.text or "" for p in candidate.content.parts if not p.thought).strip()
    try:
        return json.loads(text)
    except ValueError as exc:
        reason = candidate.finishReason or "unknown"
        raise SchemaError(f"{SOURCE}: answer is not JSON (finishReason={reason})") from exc

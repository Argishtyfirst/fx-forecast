"""Statement text helpers: sentence splitting, the sentence diff (FR-06) and rate parsing.

The splitter is rule based. It does not end a sentence at
- known abbreviations ("U.S.", "e.g.", "Mr.", "Jan.", "No.", "p.m.", ...),
- single-letter initials ("Jerome H. Powell"),
- decimal points and thousands ("4.25 percent", "1.5%", "€1.7 trillion"),
- a period followed by a lower-case word or a digit continuation.
Paragraph breaks (blank lines or newlines between blocks) always end a sentence.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Lower-cased abbreviations without the final period. Multi-dot ones ("u.s") are matched
# against the token that precedes the period.
_ABBREVIATIONS = frozenset(
    {
        "u.s",
        "u.k",
        "e.u",
        "u.n",
        "e.g",
        "i.e",
        "etc",
        "vs",
        "cf",
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "sr",
        "jr",
        "st",
        "inc",
        "ltd",
        "co",
        "corp",
        "no",
        "nos",
        "art",
        "para",
        "approx",
        "a.m",
        "p.m",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "oct",
        "nov",
        "dec",
        "pp",
        "bn",
        "mln",
        "thsd",
        "fig",
    }
)

_WS = re.compile(r"[ \t\r\f\v   ]+")
_PARA = re.compile(r"\n\s*\n|\n")
# Candidate boundary: terminal punctuation, optional closing quotes/brackets, then space.
_BOUNDARY = re.compile(r"([.!?]+)([\"'”’)\]]*)(\s+)")
_TOKEN_BEFORE = re.compile(r"(\S+)$")


def normalize_space(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _is_abbreviation(prefix: str) -> bool:
    m = _TOKEN_BEFORE.search(prefix)
    if not m:
        return False
    token = m.group(1).lstrip("(\"'“‘[").lower()
    if token in _ABBREVIATIONS:
        return True
    # Single-letter initial ("H." in "Jerome H. Powell") or dotted acronym ("U.S", "a.m").
    if re.fullmatch(r"[a-z]", token):
        return True
    return bool(re.fullmatch(r"(?:[a-z]\.)+[a-z]", token))


def _split_paragraph(par: str) -> list[str]:
    par = normalize_space(par)
    if not par:
        return []
    out: list[str] = []
    start = 0
    for m in _BOUNDARY.finditer(par):
        end = m.end(2)
        nxt = par[m.end() : m.end() + 1]
        prefix = par[start : m.start()]
        punct = m.group(1)
        if not nxt:
            continue
        if punct == ".":
            if _is_abbreviation(prefix):
                continue
            # "4. 25" never happens in clean text, but "No. 5" and "p. 3" do.
            if nxt.islower():
                continue
        elif nxt.islower():
            continue
        out.append(par[start:end].strip())
        start = m.end()
    tail = par[start:].strip()
    if tail:
        out.append(tail)
    return [s for s in out if s]


def split_sentences(text: str) -> list[str]:
    """Split text into sentences. Paragraph breaks always end a sentence."""
    if not text:
        return []
    sentences: list[str] = []
    for par in _PARA.split(text.replace("\r\n", "\n")):
        sentences.extend(_split_paragraph(par))
    return sentences


def _key(sentence: str) -> str:
    s = unicodedata.normalize("NFKC", sentence)
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-")
    return normalize_space(s).lower()


def sentence_diff(previous: str | None, current: str) -> tuple[list[str], list[str]]:
    """Sentences added in `current` and removed from `previous` (FR-06).

    Comparison ignores case, whitespace and typographic quote/dash variants. Order follows
    the text the sentence comes from. Repeated sentences count as a multiset.
    """
    prev = split_sentences(previous or "")
    cur = split_sentences(current)
    prev_counts: dict[str, int] = {}
    for s in prev:
        prev_counts[_key(s)] = prev_counts.get(_key(s), 0) + 1
    cur_counts: dict[str, int] = {}
    for s in cur:
        cur_counts[_key(s)] = cur_counts.get(_key(s), 0) + 1

    added: list[str] = []
    seen: dict[str, int] = {}
    for s in cur:
        k = _key(s)
        seen[k] = seen.get(k, 0) + 1
        if seen[k] > prev_counts.get(k, 0):
            added.append(s)
    removed: list[str] = []
    seen = {}
    for s in prev:
        k = _key(s)
        seen[k] = seen.get(k, 0) + 1
        if seen[k] > cur_counts.get(k, 0):
            removed.append(s)
    return added, removed


def statement_diff(
    previous: str | None, current: str, previous_event_id: int | None
) -> dict[str, Any]:
    added, removed = sentence_diff(previous, current)
    return {"added": added, "removed": removed, "previous_event_id": previous_event_id}


# --- rate parsing ---------------------------------------------------------------------------

_NUM = r"\d+(?:-\d+/\d+)?|\d+/\d+"


def parse_fraction(raw: str) -> float:
    """'3-3/4' -> 3.75, '1/4' -> 0.25, '4' -> 4.0, '0' -> 0.0."""
    raw = raw.strip()
    m = re.fullmatch(r"(\d+)-(\d+)/(\d+)", raw)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    m = re.fullmatch(r"(\d+)/(\d+)", raw)
    if m:
        return int(m.group(1)) / int(m.group(2))
    return float(raw)


def _clean_rate_text(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("–", "-").replace("‑", "-").replace("−", "-")
    return normalize_space(t)


_FED_BY = r"(?:by\s+(?:\d+(?:-\d+/\d+)?|\d+/\d+)\s+(?:percentage points?|basis points?)\s*)?"
_FED_RANGE = re.compile(
    rf"target range for the federal funds rate\s*{_FED_BY}(?:at|to|of)?\s*({_NUM})\s*(?:to|-)\s*({_NUM})\s*percent",
    re.I,
)
_FED_TARGET = re.compile(
    rf"target (?:for|of) the federal funds rate[^.]*?\b(?:at|to|of)\s*({_NUM})\s*percent", re.I
)


def parse_fed_target_range(text: str) -> tuple[float, float] | None:
    """(lower, upper) in percent from an FOMC statement, or None if not stated."""
    t = _clean_rate_text(text)
    m = _FED_RANGE.search(t)
    if m:
        lo, hi = parse_fraction(m.group(1)), parse_fraction(m.group(2))
        return (min(lo, hi), max(lo, hi))
    m = _FED_TARGET.search(t)
    if m:
        v = parse_fraction(m.group(1))
        return (v, v)
    return None


_PCT = r"(-?\d+(?:\.\d+)?)\s?%"
_ECB_FACILITY = {
    "deposit facility": "deposit",
    "main refinancing operations": "mro",
    "marginal lending facility": "mlf",
}


def parse_ecb_rates(text: str) -> dict[str, float]:
    """Rates after an ECB decision: keys deposit, mro, mlf (percent).

    Handles the 'interest rates on the A, the B and the C will be ... x%, y% and z%
    respectively' form (any facility order) and single-facility sentences.
    """
    t = _clean_rate_text(text).replace("minus ", "-")
    out: dict[str, float] = {}
    for m in re.finditer(
        r"interest rates? on (.{10,220}?)(?:will|would|remain|were|are|is)\b(.{0,160}?)respectively",
        t,
        re.I,
    ):
        names = [
            (m.group(1).lower().find(k), v)
            for k, v in _ECB_FACILITY.items()
            if k in m.group(1).lower()
        ]
        names = [v for pos, v in sorted(names) if pos >= 0]
        vals = [float(x) for x in re.findall(_PCT, m.group(2))]
        if len(names) == len(vals) and names:
            for k, v in zip(names, vals, strict=True):
                out.setdefault(k, v)
    if "deposit" not in out:
        m = re.search(rf"(?:deposit facility(?: rate)?)[^.%]{{0,160}}?(?:at|to)\s+{_PCT}", t, re.I)
        if m:
            out["deposit"] = float(m.group(1))
    return out


_CBA_PATTERNS = {
    "refinancing": [
        rf"(?:refinancing|policy) rate[^%]{{0,160}}?(?:setting it at|set at|to|at|unchanged,? at|unchanged\s*-?)\s*{_PCT}",
        r"(?:refinancing|policy) rate[^%]{0,60}?(?<!by )(?<![\d.])(\d+(?:\.\d+)?)\s?%",
    ],
    "lombard": [rf"lombard repo(?: facility)?(?: rate)?[^.%]{{0,60}}?{_PCT}"],
    "deposit": [rf"deposit facility(?: rate)?[^.%]{{0,60}}?{_PCT}"],
}


def parse_cba_rates(text: str) -> dict[str, float]:
    """CBA rates from a press release or news text: keys refinancing, lombard, deposit."""
    t = re.sub(r"\s?percent\b(?!age)", "%", _clean_rate_text(text), flags=re.I)
    t = t.replace(" %", "%")
    out: dict[str, float] = {}
    for key, patterns in _CBA_PATTERNS.items():
        for p in patterns:
            m = re.search(p, t, re.I)
            if m:
                out[key] = float(m.group(1))
                break
    return out

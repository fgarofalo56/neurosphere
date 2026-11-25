"""Fail-closed redaction engine (PRP-101 item 5).

``redact`` is the one function a capture path calls on every content part before encryption.
It returns either ``Redacted`` (normalized text with every must-redact detection replaced by
its typed placeholder, plus findings) or ``RedactionFailed(reason)``. There is no third
outcome: no code path returns the input, a partial output or any matched text.

Pipeline:

1. Size: more than ``budget.max_input_chars`` characters, before or after normalization, is
   ``input_too_large``.
2. Normalize (Clarification 7): NFKC, then remove zero-width, invisible formatting and bidi
   control characters. Detection runs on, and the output is, the normalized text.
3. Detect within a deadline (``time.monotonic``, ``budget.max_seconds``). Built-in detectors
   (linear, tested on 1 MB) run on the whole text so a long credential (a private-key block)
   is never split. Customer detectors run on ``budget.chunk_chars`` chunks overlapping by
   ``budget.chunk_overlap`` (Clarification 5: ``re`` cannot be interrupted, the chunk bounds
   each call). The overlap must be at least ``2 * W + 2`` where ``W`` is the largest possible
   customer match width (``DetectorSet.customer_max_width``), else ``pattern_unsafe``: a
   match touching a chunk edge is discarded (it may be cut, or see a false word boundary) and
   is found whole, strictly inside, in a neighbouring chunk; the factor 2 covers a discarded
   edge match hiding a real one from ``finditer`` in the same chunk. The deadline is checked
   before and after every built-in call and after every chunk call; exceeding it is
   ``budget_exhausted``. A single call cannot be interrupted, so one built-in call can overrun
   the deadline by at most its own 1 MB worst case (about 1 s); a customer call by its
   documented per-chunk cost (``detectors/customer.py``).
4. Resolve overlaps: matches whose spans intersect form a cluster (transitively). A cluster
   with any must-redact member (credential category, ``always_redact`` detector, or a category
   the config redacts) is replaced WHOLE by one placeholder, so a credential is never partly
   kept; the placeholder's category comes from the top-priority must-redact member
   (credential category, then ``always_redact``, then configured; then longer span, higher
   confidence, earlier detector). A cluster with no must-redact member is kept as written and
   reported as one ``kept`` finding of its top member.
5. Findings: one per (category, detector, action) with the exact cluster count, up to 64
   offsets into the REDACTED text, the highest confidence, the detector version and the
   sensitivity category. Never matched text.
6. Self-check: every ``always_redact`` or credential-category detector runs again over the
   output; any match is ``detector_error``.

Any ``Exception`` anywhere is ``detector_error``. Nothing here logs.
"""

from __future__ import annotations

import time
import unicodedata
from dataclasses import dataclass
from typing import Final, cast

from neurosphere_core.classification.detector_set import DetectorSet
from neurosphere_core.classification.detectors.customer import PatternRefused
from neurosphere_core.classification.models import (
    CREDENTIAL_CATEGORIES,
    SENSITIVITY_CATEGORY_FOR,
    Action,
    Confidence,
    Finding,
    Match,
    PartKind,
    ReasonCode,
    Redacted,
    RedactionBudget,
    RedactionConfig,
    RedactionFailed,
    RedactionResult,
    SensitivityCategory,
    placeholder,
)
from neurosphere_core.classification.protocol import Detector

__all__ = ["redact"]

#: Every Unicode Default_Ignorable_Code_Point (DerivedCoreProperties.txt) plus U+2800, removed
#: after NFKC. A hand-picked subset let variation selectors and tag characters split a key.
_INVISIBLE: Final[frozenset[int]] = frozenset(
    {
        0x00AD,  # soft hyphen
        0x034F,  # combining grapheme joiner
        0x061C,  # arabic letter mark
        *range(0x115F, 0x1161),  # hangul choseong/jungseong fillers
        *range(0x17B4, 0x17B6),  # khmer inherent vowels
        *range(0x180B, 0x1810),  # mongolian free variation selectors, vowel separator
        *range(0x200B, 0x2010),  # zero-width space/non-joiner/joiner, LRM, RLM
        *range(0x202A, 0x202F),  # bidi embeddings and overrides
        *range(0x2060, 0x2070),  # word joiner, invisible operators, bidi isolates, deprecated
        0x2800,  # braille pattern blank (not default-ignorable, but renders as nothing)
        0x3164,  # hangul filler
        *range(0xFE00, 0xFE10),  # variation selectors 1-16
        0xFEFF,  # zero-width no-break space / BOM
        0xFFA0,  # halfwidth hangul filler
        *range(0xFFF0, 0xFFF9),  # unassigned specials
        *range(0x1BCA0, 0x1BCA4),  # shorthand format controls
        *range(0x1D173, 0x1D17B),  # musical symbol formatting
        *range(0xE0000, 0xE1000),  # tags, variation selectors supplement, reserved
    }
)
_STRIP_INVISIBLE: Final[dict[int, None]] = dict.fromkeys(_INVISIBLE)

_CONFIDENCE_RANK: Final[dict[str, int]] = {"high": 0, "medium": 1, "low": 2}
_MAX_OFFSETS: Final = 64
_DEFAULT_BUDGET: Final = RedactionBudget()


class _Fail(Exception):  # noqa: N818 - internal control flow, never escapes ``redact``
    """Internal: abort with a reason code. Carries no text."""

    def __init__(self, reason: ReasonCode) -> None:
        super().__init__(reason)
        self.reason: ReasonCode = reason


@dataclass(frozen=True, slots=True)
class _Hit:
    match: Match
    index: int  # detector position in the set


class _Clock:
    __slots__ = ("_deadline",)

    def __init__(self, seconds: float) -> None:
        self._deadline = time.monotonic() + seconds

    def check(self) -> None:
        if time.monotonic() > self._deadline:
            raise _Fail("budget_exhausted")


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(_STRIP_INVISIBLE)


def _validated(match: object, detector: Detector, length: int, offset: int) -> Match:
    """Fail closed on anything a detector should never return."""
    if not isinstance(match, Match):
        raise _Fail("detector_error")
    if match.detector_id != detector.detector_id or match.category not in detector.kinds:
        raise _Fail("detector_error")
    if match.end > length:
        raise _Fail("detector_error")
    if offset == 0:
        return match
    return Match(
        start=match.start + offset,
        end=match.end + offset,
        category=match.category,
        confidence=match.confidence,
        detector_id=match.detector_id,
        sensitivity_category=match.sensitivity_category,
    )


def _run_whole(detector: Detector, text: str, clock: _Clock) -> list[Match]:
    clock.check()
    found = detector.find(text)
    clock.check()
    if not isinstance(found, tuple):
        raise _Fail("detector_error")
    return [_validated(m, detector, len(text), 0) for m in found]


def _run_chunked(
    detector: Detector, text: str, clock: _Clock, chunk: int, overlap: int
) -> list[Match]:
    size = len(text)
    step = chunk - overlap
    out: set[Match] = set()
    start = 0
    while True:
        end = min(start + chunk, size)
        piece = text[start:end]
        clock.check()
        found = detector.find(piece)
        clock.check()
        if not isinstance(found, tuple):
            raise _Fail("detector_error")
        for raw in found:
            m = _validated(raw, detector, len(piece), start)
            # Edge-touching matches may be cut or see a false boundary; the neighbouring
            # chunk holds the same match strictly inside (overlap >= 2 * width + 2).
            if start > 0 and m.start == start:
                continue
            if end < size and m.end == end:
                continue
            out.add(m)
        if end >= size:
            break
        start += step
    return sorted(out, key=lambda m: (m.start, m.end))


def _detect(
    detector_set: DetectorSet, text: str, budget: RedactionBudget, clock: _Clock
) -> list[_Hit]:
    hits: list[_Hit] = []
    customer = set(map(id, detector_set.customer_detectors))
    if customer and 2 * detector_set.customer_max_width + 2 > budget.chunk_overlap:
        raise _Fail("pattern_unsafe")
    for index, detector in enumerate(detector_set.all_detectors):
        if id(detector) in customer:
            matches = _run_chunked(detector, text, clock, budget.chunk_chars, budget.chunk_overlap)
        else:
            matches = _run_whole(detector, text, clock)
        hits.extend(_Hit(m, index) for m in matches)
    return hits


def _clusters(hits: list[_Hit]) -> list[list[_Hit]]:
    ordered = sorted(hits, key=lambda h: (h.match.start, h.match.end, h.index))
    clusters: list[list[_Hit]] = []
    reach = -1
    for hit in ordered:
        if clusters and hit.match.start < reach:
            clusters[-1].append(hit)
            reach = max(reach, hit.match.end)
        else:
            clusters.append([hit])
            reach = hit.match.end
    return clusters


@dataclass(frozen=True, slots=True)
class _Resolved:
    hit: _Hit
    action: Action
    start: int  # in the input text
    end: int


def _tier(hit: _Hit, detectors: tuple[Detector, ...], config: RedactionConfig) -> int:
    if hit.match.category in CREDENTIAL_CATEGORIES:
        return 0
    if detectors[hit.index].always_redact:
        return 1
    if config.mode_for(hit.match.category) == "redact":
        return 2
    return 3


def _priority(
    hit: _Hit, detectors: tuple[Detector, ...], config: RedactionConfig
) -> tuple[int, int, int, int]:
    m = hit.match
    return (
        _tier(hit, detectors, config),
        -(m.end - m.start),
        _CONFIDENCE_RANK[m.confidence],
        hit.index,
    )


def _resolve(
    clusters: list[list[_Hit]], detectors: tuple[Detector, ...], config: RedactionConfig
) -> list[_Resolved]:
    resolved: list[_Resolved] = []
    for cluster in clusters:
        top = min(cluster, key=lambda h: _priority(h, detectors, config))
        if _tier(top, detectors, config) < 3:
            start = min(h.match.start for h in cluster)
            end = max(h.match.end for h in cluster)
            resolved.append(_Resolved(top, "replaced", start, end))
        else:
            resolved.append(_Resolved(top, "kept", top.match.start, top.match.end))
    return resolved


def _rewrite(text: str, resolved: list[_Resolved]) -> tuple[str, list[tuple[int, int]]]:
    """Output text and, per resolved cluster, its (start, end) in the output."""
    pieces: list[str] = []
    spans: list[tuple[int, int]] = []
    cursor = 0  # input position copied so far
    out_len = 0
    for item in resolved:
        if item.action == "replaced":
            prefix = text[cursor : item.start]
            pieces.append(prefix)
            out_len += len(prefix)
            token = placeholder(item.hit.match.category)
            pieces.append(token)
            spans.append((out_len, out_len + len(token)))
            out_len += len(token)
            cursor = item.end
        else:
            # Kept: copy through the kept span; earlier clusters never reach past it.
            shift = out_len - cursor
            spans.append((item.start + shift, item.end + shift))
    pieces.append(text[cursor:])
    return "".join(pieces), spans


def _findings(
    resolved: list[_Resolved],
    spans: list[tuple[int, int]],
    detectors: tuple[Detector, ...],
    part: PartKind,
) -> tuple[Finding, ...]:
    groups: dict[tuple[str, int, str], list[int]] = {}
    for position, item in enumerate(resolved):
        key = (item.hit.match.category, item.hit.index, item.action)
        groups.setdefault(key, []).append(position)
    findings: list[tuple[tuple[int, int], Finding]] = []
    for (category, index, action), positions in groups.items():
        hits = [resolved[p].hit for p in positions]
        detector = detectors[index]
        override = hits[0].match.sensitivity_category
        sensitivity = override if override is not None else SENSITIVITY_CATEGORY_FOR[category]
        confidence = min((h.match.confidence for h in hits), key=_CONFIDENCE_RANK.__getitem__)
        offsets = tuple(spans[p] for p in positions[:_MAX_OFFSETS])
        finding = Finding(
            category=hits[0].match.category,
            part=part,
            detector_id=detector.detector_id,
            detector_version=detector.version,
            count=len(positions),
            action=cast("Action", action),
            confidence=cast("Confidence", confidence),
            offsets=offsets,
            sensitivity_category=cast("SensitivityCategory | None", sensitivity),
        )
        findings.append(((offsets[0][0], index), finding))
    findings.sort(key=lambda pair: pair[0])
    return tuple(f for _, f in findings)


def _self_check(detector_set: DetectorSet, output: str, clock: _Clock) -> None:
    for detector in detector_set.all_detectors:
        if detector.always_redact or detector.kinds & CREDENTIAL_CATEGORIES:
            if _run_whole(detector, output, clock):
                raise _Fail("detector_error")


def _redact(
    text: str,
    part: PartKind,
    config: RedactionConfig,
    detector_set: DetectorSet,
    budget: RedactionBudget,
) -> Redacted:
    if not isinstance(text, str):
        raise _Fail("detector_error")
    if not isinstance(config, RedactionConfig) or not isinstance(detector_set, DetectorSet):
        raise _Fail("detector_error")
    if not isinstance(budget, RedactionBudget):
        raise _Fail("detector_error")
    if len(text) > budget.max_input_chars:
        raise _Fail("input_too_large")
    clock = _Clock(budget.max_seconds)
    normalized = _normalize(text)
    if len(normalized) > budget.max_input_chars:
        raise _Fail("input_too_large")
    detectors = detector_set.all_detectors
    hits = _detect(detector_set, normalized, budget, clock)
    resolved = _resolve(_clusters(hits), detectors, config)
    output, spans = _rewrite(normalized, resolved)
    findings = _findings(resolved, spans, detectors, part)
    _self_check(detector_set, output, clock)
    return Redacted(text=output, findings=findings, set_version=detector_set.version)


def redact(
    text: str,
    *,
    part: PartKind,
    config: RedactionConfig,
    detector_set: DetectorSet,
    budget: RedactionBudget = _DEFAULT_BUDGET,
) -> RedactionResult:
    """Redact one content part; fail closed.

    Returns ``Redacted`` or ``RedactionFailed(reason)`` with reason ``input_too_large``,
    ``budget_exhausted``, ``pattern_unsafe`` or ``detector_error``. Never raises for an
    ``Exception`` (``KeyboardInterrupt`` and ``SystemExit`` propagate), never returns the
    input or partial output on failure, never logs.
    """
    try:
        return _redact(text, part, config, detector_set, budget)
    except _Fail as failure:
        return RedactionFailed(reason=failure.reason)
    except PatternRefused:
        return RedactionFailed(reason="pattern_unsafe")
    except Exception:
        return RedactionFailed(reason="detector_error")

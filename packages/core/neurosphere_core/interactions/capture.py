"""Opt-in body capture: extraction and the capture pipeline (PRP-103 item 2).

This is the only code that turns the body fields the payload guard would drop into stored,
redacted, encrypted interaction content. It never changes :mod:`neurosphere_core.payload.guard`;
it reuses its field rule (:func:`~neurosphere_core.payload.guard.is_body_field`).

Extraction (:func:`extract_body_parts`) is pure and iterative. It maps body fields to content
parts (Clarification 6): ``prompt`` <- ``prompt``, ``gen_ai.prompt``, ``gen_ai.input.messages``,
``messages`` and any ``*.prompt``; ``response`` <- ``response``, ``completion``,
``gen_ai.completion``, ``gen_ai.output.messages`` and any ``*.response``;
``system_instructions`` <- ``gen_ai.system_instructions``. Structured values (message lists,
OTLP ``arrayValue`` / ``kvlistValue``) are serialised deterministically to JSON text. Size caps
cut at a whitespace boundary, so a cap never keeps the front half of a token (a secret cut in
two may no longer be recognisable by its detector).

The pipeline (:class:`CapturePipeline`) admits or sheds (bounded in-flight work, per-policy rate
limit), redacts every part with PRP-101 (credentials always; other categories unless the policy
keeps them), seals and stores the ``RedactedContent`` with PRP-102, appends one
``interaction.capture`` audit event and returns the ``payload_ref``. Any failure in detection,
redaction, key wrap, storage or the audit write keeps no content: an index-only record (no
blob) is written instead, ``interaction.capture_dropped`` is audited and the ``payload_ref``
says ``redaction_failed``.

Captured values are secret-grade: they never appear in an exception, a log record, a ``repr``,
an audit event or a counter label. Only reason codes, ids and counts leave this module.
"""

from __future__ import annotations

import json
import math
import re
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, Protocol, runtime_checkable

from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord
from neurosphere_contracts.interactions.v1.redacted_content import RedactedContent
from neurosphere_contracts.telemetry.v1.content_envelope import ContentEnvelope
from neurosphere_contracts.telemetry.v1.telemetry_event import PayloadRef
from opentelemetry import metrics as otel_metrics
from opentelemetry.metrics import Meter

from neurosphere_core.classification import (
    CREDENTIAL_CATEGORIES,
    DetectorSet,
    Finding,
    Redacted,
    RedactionConfig,
    RedactionFailed,
    default_detector_set,
    redact,
)
from neurosphere_core.crypto import KEY_HOST_REFUSED, KEY_WRAP_UNAVAILABLE, EnvelopeError
from neurosphere_core.interactions.blob_content import ContentBackend, content_blob_name
from neurosphere_core.interactions.cosmos_index import IndexBackend
from neurosphere_core.interactions.models import (
    CONTENT_NOT_SECRET_FREE,
    CONTENT_RETENTION_NOT_ENABLED,
    INTERACTION_EXISTS,
    InteractionStoreError,
    format_timestamp,
)
from neurosphere_core.payload.guard import is_body_field, normalize_field_name

__all__ = [
    "AUDIT_OP_CAPTURE",
    "AUDIT_OP_CAPTURE_DROPPED",
    "CAPTURE_SOURCE_OTLP_ATTRIBUTES",
    "DEFAULT_MAX_CONTENT_CHARS",
    "DEFAULT_QUEUE_CAPACITY",
    "DEFAULT_SHED_PERCENT",
    "MAX_PART_CHARS",
    "CaptureAuditEvent",
    "CaptureAuditWriter",
    "CaptureEvent",
    "CapturePipeline",
    "CaptureRateLimiter",
    "CaptureStats",
    "CaptureStore",
    "CaptureTarget",
    "ExtractedBody",
    "ExtractedPart",
    "FailureReason",
    "MinuteRateLimiter",
    "extract_body_parts",
    "interaction_pointer",
    "redaction_config_for",
]

#: PRP-99 ``ContentEnvelope`` / ``SecretFreeText`` per-part limit.
MAX_PART_CHARS: Final = 32768
#: PRP-99 ``InteractionCaptureSetting.max_content_chars_per_interaction`` default.
DEFAULT_MAX_CONTENT_CHARS: Final = 65536
#: PRP-99 ``InteractionCaptureSetting.shed_capture_at_queue_percent`` default.
DEFAULT_SHED_PERCENT: Final = 80
#: ``NS_INTERACTION_CAPTURE_QUEUE_CAPACITY`` default (PRP-103 Interfaces provided).
DEFAULT_QUEUE_CAPACITY: Final = 64

CAPTURE_SOURCE_OTLP_ATTRIBUTES: Final = "otlp_attributes"
AUDIT_OP_CAPTURE: Final = "interaction.capture"
AUDIT_OP_CAPTURE_DROPPED: Final = "interaction.capture_dropped"
POINTER_PREFIX: Final = "interaction:"

_RECORD_SCHEMA_VERSION: Final = "1.2.0"
_CONTENT_SCHEMA_VERSION: Final = "1.2.0"
_ENVELOPE_SCHEMA_VERSION: Final = "1.2.0"
_METER_NAME: Final = "neurosphere_core.interactions.capture"
#: PRP-99 ``CapturePolicy.redaction_mode``. Both redact every detection except the policy's
#: kept, non-credential categories; an unknown mode fails closed.
_REDACTION_MODES: Final = frozenset({"redact_all_detections", "redact_listed"})

PartName = Literal["prompt", "response", "system_instructions"]
#: Part order: also the order the per-interaction budget is spent in.
_PART_ORDER: Final[tuple[PartName, ...]] = ("prompt", "response", "system_instructions")

_PROMPT_NAMES: Final = frozenset({"prompt", "gen_ai.prompt", "gen_ai.input.messages", "messages"})
_RESPONSE_NAMES: Final = frozenset(
    {"response", "completion", "gen_ai.completion", "gen_ai.output.messages"}
)
_SYSTEM_NAMES: Final = frozenset({"gen_ai.system_instructions"})

#: Characters the ContentEnvelope pattern forbids (controls except tab, LF, CR) and lone
#: surrogates (not encodable as UTF-8); both become a space / U+FFFD so offsets stay stable.
_CONTROL: Final = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SURROGATE: Final = re.compile("[\ud800-\udfff]")
_REPLACEMENT_CHAR: Final = chr(0xFFFD)

FailureReason = Literal[
    "detection_failed",
    "redaction_failed",
    "detector_set_mismatch",
    "content_rejected",
    "retention_not_enabled",
    "key_wrap_failed",
    "key_host_refused",
    "storage_failed",
    "audit_failed",
]


def interaction_pointer(interaction_id: str) -> str:
    """The ``payload_ref.pointer`` scheme PRP-104 resolves."""
    return f"{POINTER_PREFIX}{interaction_id}"


# --- extraction ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtractedPart:
    """One extracted content part. ``text`` is secret-grade and never shown in ``repr``."""

    part: PartName
    text: str = field(repr=False)
    truncated: bool = False

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass(frozen=True, slots=True)
class ExtractedBody:
    """The body parts of one span or telemetry item, at most one per kind, in part order.

    ``field_count`` is how many body fields were found; ``skipped`` how many could not be
    serialised (counted, never echoed).
    """

    parts: tuple[ExtractedPart, ...]
    field_count: int = 0
    skipped: int = 0

    def __repr__(self) -> str:
        kinds = ",".join(f"{p.part}:{p.char_count}" for p in self.parts)
        return f"ExtractedBody(parts=[{kinds}], field_count={self.field_count})"

    def to_envelope(
        self,
        *,
        cloud: str,
        source_id: str,
        event_id: str,
        trace_id: str,
        occurred_at: str,
        span_id: str | None = None,
    ) -> ContentEnvelope:
        """The PRP-99 ``ContentEnvelope`` (needs a trace id, which telemetry items may lack)."""
        return ContentEnvelope.model_validate(
            {
                "schema_version": _ENVELOPE_SCHEMA_VERSION,
                "cloud": cloud,
                "source_id": source_id,
                "event_id": event_id,
                "trace_id": trace_id,
                "span_id": span_id,
                "occurred_at": occurred_at,
                "parts": [
                    {"part": p.part, "text": p.text, "truncated": p.truncated} for p in self.parts
                ],
            }
        )

    @classmethod
    def from_envelope(cls, envelope: ContentEnvelope) -> ExtractedBody:
        """Adapt a ``ContentEnvelope`` (``edge_push``, PRP-111) to the pipeline input."""
        parts: list[ExtractedPart] = []
        for item in envelope.parts:
            kind = item.part.root
            if kind not in _PART_ORDER:
                continue  # tool parts arrive with PRP-111
            parts.append(ExtractedPart(kind, _sanitize(item.text), bool(item.truncated)))
        return cls(tuple(parts), field_count=len(envelope.parts))


def _part_for(name: str) -> PartName | None:
    """Content part for a normalized body-field name (Clarification 6)."""
    if name in _SYSTEM_NAMES:
        return "system_instructions"
    if name in _PROMPT_NAMES:
        return "prompt"
    if name in _RESPONSE_NAMES:
        return "response"
    last = name.rsplit(".", 1)[-1]
    if last == "prompt":
        return "prompt"
    if last == "response":
        return "response"
    return None


def _escape_pointer(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


_SCALAR_KEYS: Final = ("stringValue", "intValue", "doubleValue", "boolValue", "bytesValue")


def _decode_any_value(value: Any) -> Any:
    """OTLP/JSON ``AnyValue`` -> plain JSON value. Iterative; unknown shapes become ``None``."""
    holder: list[Any] = [None]
    stack: list[tuple[Any, Any, Any]] = [(value, holder, 0)]
    while stack:
        src, dst, slot = stack.pop()
        if not isinstance(src, Mapping):
            dst[slot] = None
            continue
        array = src.get("arrayValue")
        kvlist = src.get("kvlistValue")
        if isinstance(array, Mapping):
            values = array.get("values")
            items = values if isinstance(values, list) else []
            out: list[Any] = [None] * len(items)
            dst[slot] = out
            stack.extend((item, out, index) for index, item in enumerate(items))
        elif isinstance(kvlist, Mapping):
            values = kvlist.get("values")
            obj: dict[str, Any] = {}
            dst[slot] = obj
            for kv in values if isinstance(values, list) else []:
                if isinstance(kv, Mapping) and isinstance(kv.get("key"), str):
                    obj[kv["key"]] = None
                    stack.append((kv.get("value"), obj, kv["key"]))
        else:
            dst[slot] = next((src[k] for k in _SCALAR_KEYS if k in src), None)
    return holder[0]


def _serialize(value: Any) -> str | None:
    """Deterministic text for a body value; ``None`` when there is nothing to keep."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sanitize(text: str) -> str:
    return _SURROGATE.sub(_REPLACEMENT_CHAR, _CONTROL.sub(" ", text))


def _cut(text: str, limit: int) -> tuple[str, bool]:
    """At most ``limit`` characters, cut at the last whitespace so no token is split."""
    if len(text) <= limit:
        return text, False
    if limit <= 0:
        return "", True
    end = limit
    if not text[end].isspace():
        while end > 0 and not text[end - 1].isspace():
            end -= 1
    return text[:end].rstrip(), True


def _find_body_values(item: Any) -> list[tuple[str, str, Any]]:
    """``(json_pointer, normalized_name, value)`` for each body field. Mirrors ``guard.py``.

    Dict keys and OTLP attribute items (``{"key": name, "value": AnyValue}``) are found at any
    depth; a body field's value is not searched further (the guard drops it whole).
    """
    found: list[tuple[str, str, Any]] = []
    stack: list[tuple[Any, str]] = [(item, "")]
    while stack:
        node, path = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                child_path = f"{path}/{_escape_pointer(str(key))}"
                if isinstance(key, str) and is_body_field(key):
                    found.append((child_path, normalize_field_name(key), value))
                elif isinstance(value, (dict, list)):
                    stack.append((value, child_path))
        elif isinstance(node, list):
            for index, element in enumerate(node):
                child_path = f"{path}/{index}"
                if isinstance(element, dict) and "value" in element:
                    key = element.get("key")
                    if isinstance(key, str) and is_body_field(key):
                        found.append(
                            (
                                child_path,
                                normalize_field_name(key),
                                _decode_any_value(element["value"]),
                            )
                        )
                        continue
                if isinstance(element, (dict, list)):
                    stack.append((element, child_path))
    found.sort(key=lambda entry: entry[0])
    return found


def extract_body_parts(
    item: Any,
    *,
    max_part_chars: int = MAX_PART_CHARS,
    max_content_chars: int = DEFAULT_MAX_CONTENT_CHARS,
) -> ExtractedBody | None:
    """The body parts of one OTLP span or CloudEvent telemetry item; ``None`` without a body.

    Pure and iterative. ``item`` is not changed. Several fields of one kind are joined with a
    newline in JSON-pointer order. Each part is capped at ``min(max_part_chars, 32768)`` and the
    interaction at ``max_content_chars`` (spent in prompt, response, system-instructions
    order); a cut part is ``truncated``. Errors never carry a value.
    """
    if not isinstance(item, (dict, list)):
        return None
    per_part = max(0, min(int(max_part_chars), MAX_PART_CHARS))
    budget = max(0, int(max_content_chars))
    texts: dict[PartName, list[str]] = {}
    field_count = 0
    skipped = 0
    for _path, name, value in _find_body_values(item):
        part = _part_for(name)
        if part is None:  # pragma: no cover - every body-field name maps to a part
            continue
        field_count += 1
        try:
            text = _serialize(value)
        except (TypeError, ValueError):
            skipped += 1
            continue
        if text:
            texts.setdefault(part, []).append(text)
    if not texts:
        return None
    parts: list[ExtractedPart] = []
    for kind in _PART_ORDER:
        chunks = texts.get(kind)
        if not chunks:
            continue
        joined = _sanitize("\n".join(chunks))
        capped, cut_part = _cut(joined, per_part)
        capped, cut_total = _cut(capped, budget)
        if not capped.strip():
            continue
        budget -= len(capped)
        parts.append(ExtractedPart(kind, capped, cut_part or cut_total))
    if not parts:
        return None
    return ExtractedBody(tuple(parts), field_count=field_count, skipped=skipped)


# --- pipeline inputs -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CaptureTarget:
    """What a matched capture policy decides (item 1's ``CaptureDecision`` adapts to this)."""

    policy_id: str
    policy_version: int
    domain_id: str
    source_id: str
    detector_set_version: str
    retention_days: int
    max_per_minute: int
    redaction_mode: str = "redact_all_detections"
    kept_categories: frozenset[str] = frozenset()
    parts: frozenset[str] = frozenset(_PART_ORDER)
    max_part_chars: int = 8192
    retention_class: str = "interaction_default"
    customer_dictionary_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CaptureEvent:
    """Identity of the telemetry event that carried the body (ids only)."""

    cloud: str
    customer_id: str
    domain_id: str
    source_id: str
    event_id: str
    correlation_id: str
    occurred_at: str
    trace_id: str | None = None
    span_id: str | None = None


@dataclass(frozen=True, slots=True)
class CaptureAuditEvent:
    """One capture audit event: ids, a state or reason code and counts. Never content."""

    operation: Literal["interaction.capture", "interaction.capture_dropped"]
    customer_id: str
    domain_id: str
    source_id: str
    event_id: str
    correlation_id: str
    interaction_id: str
    capture_policy_id: str
    capture_policy_version: int
    detector_set_version: str
    redaction_state: Literal["redacted", "not_required", "redaction_failed"]
    reason: str | None
    part_count: int
    finding_count: int
    detected_category_count: int

    def details(self) -> dict[str, str | int]:
        """Flat, metadata-only details (no key the audit content guard forbids)."""
        out: dict[str, str | int] = {
            "interaction_id": self.interaction_id,
            "capture_policy_id": self.capture_policy_id,
            "capture_policy_version": self.capture_policy_version,
            "detector_set_version": self.detector_set_version,
            "redaction_state": self.redaction_state,
            "part_count": self.part_count,
            "finding_count": self.finding_count,
            "detected_category_count": self.detected_category_count,
        }
        if self.reason is not None:
            out["reason"] = self.reason
        return out


#: Appends one audit event on the domain chain; raising means the write failed.
CaptureAuditWriter = Callable[[CaptureAuditEvent], Awaitable[object]]


@runtime_checkable
class CaptureRateLimiter(Protocol):
    """Per-policy rate limit (``sampling.max_per_minute``); ``False`` sheds the capture."""

    def try_acquire(self, policy_id: str, max_per_minute: int) -> bool: ...


class MinuteRateLimiter:
    """Default token bucket per policy: ``max_per_minute`` tokens, refilled continuously."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}

    def try_acquire(self, policy_id: str, max_per_minute: int) -> bool:
        if max_per_minute <= 0:
            return False
        now = self._clock()
        tokens, last = self._buckets.get(policy_id, (float(max_per_minute), now))
        tokens = min(float(max_per_minute), tokens + (now - last) * max_per_minute / 60.0)
        if tokens < 1.0:
            self._buckets[policy_id] = (tokens, now)
            return False
        self._buckets[policy_id] = (tokens - 1.0, now)
        return True


@runtime_checkable
class CaptureStore(Protocol):
    """What the pipeline needs from PRP-102's ``EncryptedInteractionStore``."""

    @property
    def index(self) -> IndexBackend: ...

    @property
    def content(self) -> ContentBackend: ...

    async def put(
        self, record: InteractionRecord, content: RedactedContent, *, capture_retention_days: int
    ) -> InteractionRecord: ...

    async def delete(self, customer_id: str, domain_id: str, interaction_id: str) -> bool: ...


@dataclass(slots=True)
class CaptureStats:
    """In-process capture counters (the meter carries the same signal).

    ``capture_skipped_no_policy`` is counted by the caller (the edge) through
    :meth:`skipped_no_policy` when the matcher declines.
    """

    captured: int = 0
    capture_skipped_no_policy: int = 0
    capture_failed: Counter[str] = field(default_factory=Counter)
    capture_shed: int = 0
    shed_reasons: Counter[str] = field(default_factory=Counter)
    audit_write_failed: int = 0
    failure_record_failed: int = 0
    cleanup_failed: int = 0

    def skipped_no_policy(self, count: int = 1) -> None:
        self.capture_skipped_no_policy += count

    @property
    def capture_failed_total(self) -> int:
        return sum(self.capture_failed.values())

    def snapshot(self) -> dict[str, Any]:
        """JSON-ready counters (reason codes and integers only)."""
        return {
            "captured": self.captured,
            "capture_skipped_no_policy": self.capture_skipped_no_policy,
            "capture_failed": dict(sorted(self.capture_failed.items())),
            "capture_failed_total": self.capture_failed_total,
            "capture_shed": self.capture_shed,
            "shed_reasons": dict(sorted(self.shed_reasons.items())),
            "audit_write_failed": self.audit_write_failed,
            "failure_record_failed": self.failure_record_failed,
            "cleanup_failed": self.cleanup_failed,
        }


def redaction_config_for(kept_categories: Iterable[str]) -> RedactionConfig:
    """Redact every detection except the policy's kept, non-credential categories (GD-4).

    ``payment_card`` and every other category default to ``redact``; a credential category is
    never kept whatever the policy says.
    """
    modes = {c: "keep" for c in sorted(set(kept_categories)) if c not in CREDENTIAL_CATEGORIES}
    return RedactionConfig.model_validate({"default_mode": "redact", "modes": modes})


# --- the pipeline --------------------------------------------------------------------------------


class _CaptureFailed(Exception):  # noqa: N818 - internal control flow; carries a code only
    def __init__(self, reason: FailureReason) -> None:
        super().__init__(reason)
        self.reason: FailureReason = reason


@dataclass(slots=True)
class _Outcome:
    parts: list[dict[str, Any]]
    findings: list[Finding]
    state: Literal["redacted", "not_required", "redaction_failed"]


def _store_failure_reason(exc: Exception) -> FailureReason:
    if isinstance(exc, InteractionStoreError):
        if exc.reason == CONTENT_RETENTION_NOT_ENABLED:
            return "retention_not_enabled"
        if exc.reason == CONTENT_NOT_SECRET_FREE:
            return "content_rejected"
        return "storage_failed"
    if isinstance(exc, EnvelopeError):
        if exc.reason == KEY_WRAP_UNAVAILABLE:
            return "key_wrap_failed"
        if exc.reason == KEY_HOST_REFUSED:
            return "key_host_refused"
        return "storage_failed"
    return "storage_failed"


def _part_sizes(body: ExtractedBody) -> list[dict[str, Any]]:
    return [
        {"part": p.part, "char_count": p.char_count, "truncated": p.truncated} for p in body.parts
    ]


def _cap_redacted(text: str, limit: int) -> tuple[str, bool]:
    """Cap redacted text; whitespace cut, so a placeholder is never split."""
    return _cut(text, limit)


def _detection_finding(finding: Finding, text_len: int) -> dict[str, Any]:
    return {
        "category": finding.category,
        "part": finding.part,
        "detector_id": finding.detector_id,
        "detector_version": finding.detector_version,
        "count": finding.count,
        "action": finding.action,
        "confidence": finding.confidence,
        "spans": [{"start": s, "end": e} for s, e in finding.offsets if e <= text_len],
    }


class CapturePipeline:
    """Redact, encrypt and store one interaction; return the event's ``payload_ref``.

    ``queue_capacity`` bounds concurrent captures; a capture is shed (``None``, no
    ``payload_ref``) once the in-flight count reaches ``shed_at_percent`` of it, or when the
    rate limiter refuses the policy. Nothing is ever queued.
    """

    def __init__(
        self,
        store: CaptureStore,
        *,
        queue_capacity: int = DEFAULT_QUEUE_CAPACITY,
        shed_at_percent: int = DEFAULT_SHED_PERCENT,
        rate_limiter: CaptureRateLimiter | None = None,
        detector_set_for: Callable[[CaptureTarget], DetectorSet] | None = None,
        stats: CaptureStats | None = None,
        now: Callable[[], datetime] | None = None,
        meter: Meter | None = None,
    ) -> None:
        if queue_capacity < 1:
            raise ValueError("queue_capacity must be at least 1")
        if not 1 <= shed_at_percent <= 100:
            raise ValueError("shed_at_percent must be from 1 to 100")
        self._store = store
        self._capacity = queue_capacity
        self._shed_percent = shed_at_percent
        self._limiter: CaptureRateLimiter = rate_limiter or MinuteRateLimiter()
        default_set = default_detector_set()
        self._detector_set_for = detector_set_for or (lambda _target: default_set)
        self.stats = stats or CaptureStats()
        self._now = now or (lambda: datetime.now(UTC))
        self._in_flight = 0
        meter = meter or otel_metrics.get_meter(_METER_NAME)
        self._captured_counter = meter.create_counter("ns.interactions.captured", unit="{item}")
        self._failed_counter = meter.create_counter("ns.interactions.capture_failed", unit="{item}")
        self._shed_counter = meter.create_counter("ns.interactions.capture_shed", unit="{item}")

    @property
    def in_flight(self) -> int:
        return self._in_flight

    @property
    def shed_threshold(self) -> int:
        """In-flight count at which captures are shed."""
        return max(1, math.ceil(self._capacity * self._shed_percent / 100))

    def _shed(self, reason: str) -> None:
        self.stats.capture_shed += 1
        self.stats.shed_reasons[reason] += 1
        self._shed_counter.add(1, {"ns.reason": reason})

    async def capture(
        self,
        body: ExtractedBody,
        target: CaptureTarget,
        event: CaptureEvent,
        *,
        audit: CaptureAuditWriter,
    ) -> PayloadRef | None:
        """Capture ``body`` under ``target``; ``None`` when shed or nothing is capturable."""
        if event.domain_id != target.domain_id or event.source_id != target.source_id:
            self.stats.skipped_no_policy()
            return None
        allowed = ExtractedBody(
            tuple(p for p in body.parts if p.part in target.parts),
            field_count=body.field_count,
            skipped=body.skipped,
        )
        if not allowed.parts:
            return None
        # Admission: no await between the check and the increment, so this is atomic on the
        # event loop; nothing waits, nothing is queued.
        if self._in_flight >= self.shed_threshold:
            self._shed("queue")
            return None
        if not self._limiter.try_acquire(target.policy_id, target.max_per_minute):
            self._shed("rate")
            return None
        self._in_flight += 1
        try:
            return await self._capture(allowed, target, event, audit)
        finally:
            self._in_flight -= 1

    async def _capture(
        self,
        body: ExtractedBody,
        target: CaptureTarget,
        event: CaptureEvent,
        audit: CaptureAuditWriter,
    ) -> PayloadRef:
        interaction_id = str(uuid.uuid4())
        captured_at = self._now()
        try:
            outcome = self._redact(body, target)
        except _CaptureFailed as failure:
            reason = failure.reason
        else:
            try:
                await self._store_content(interaction_id, captured_at, outcome, target, event)
            except _CaptureFailed as failure:
                reason = failure.reason
            else:
                ok = await self._audit(
                    audit,
                    self._audit_event(
                        AUDIT_OP_CAPTURE, interaction_id, target, event, outcome, None
                    ),
                )
                if ok:
                    self.stats.captured += 1
                    self._captured_counter.add(1)
                    return self._payload_ref(interaction_id, target, outcome)
                await self._discard(event, interaction_id, captured_at)
                reason = "audit_failed"
        return await self._fail(reason, interaction_id, captured_at, body, target, event, audit)

    def _redact(self, body: ExtractedBody, target: CaptureTarget) -> _Outcome:
        try:
            detector_set = self._detector_set_for(target)
        except Exception:
            raise _CaptureFailed("detection_failed") from None
        if detector_set.version != target.detector_set_version:
            raise _CaptureFailed("detector_set_mismatch")
        if target.redaction_mode not in _REDACTION_MODES:
            raise _CaptureFailed("redaction_failed")
        try:
            config = redaction_config_for(target.kept_categories)
        except Exception:
            raise _CaptureFailed("redaction_failed") from None
        limit = max(1, min(target.max_part_chars, MAX_PART_CHARS))
        parts: list[dict[str, Any]] = []
        findings: list[Finding] = []
        for item in body.parts:
            source, cut_in = _cut(item.text, limit)
            if not source.strip():
                continue
            result = redact(source, part=item.part, config=config, detector_set=detector_set)
            if isinstance(result, RedactionFailed):
                raise _CaptureFailed(
                    "detection_failed" if result.reason == "detector_error" else "redaction_failed"
                )
            if not isinstance(result, Redacted):  # pragma: no cover - redact has two outcomes
                raise _CaptureFailed("redaction_failed")
            text, cut_out = _cap_redacted(result.text, limit)
            parts.append(
                {
                    "part": item.part,
                    "text": text,
                    "truncated": item.truncated or cut_in or cut_out,
                    "findings": [_detection_finding(f, len(text)) for f in result.findings],
                }
            )
            findings.extend(result.findings)
        if not parts:
            raise _CaptureFailed("redaction_failed")
        replaced = any(f.action == "replaced" for f in findings)
        return _Outcome(parts, findings, "redacted" if replaced else "not_required")

    def _record(
        self,
        interaction_id: str,
        captured_at: datetime,
        target: CaptureTarget,
        event: CaptureEvent,
        *,
        state: Literal["redacted", "not_required", "redaction_failed"],
        parts: Sequence[Mapping[str, Any]],
        findings: Sequence[Finding],
    ) -> InteractionRecord:
        summary: Counter[tuple[str, str]] = Counter()
        sensitivities: set[str] = set()
        for finding in findings:
            summary[(finding.category, finding.action)] += finding.count
            if finding.sensitivity_category is not None:
                sensitivities.add(finding.sensitivity_category)
        expires = captured_at + timedelta(days=target.retention_days)
        return InteractionRecord.model_validate(
            {
                "schema_version": _RECORD_SCHEMA_VERSION,
                "interaction_id": interaction_id,
                "cloud": event.cloud,
                "customer_id": event.customer_id,
                "domain_id": event.domain_id,
                "source_id": event.source_id,
                "event_id": event.event_id,
                "trace_id": event.trace_id,
                "span_id": event.span_id,
                "correlation_id": event.correlation_id,
                "capture_source": CAPTURE_SOURCE_OTLP_ATTRIBUTES,
                "occurred_at": event.occurred_at,
                "captured_at": format_timestamp(captured_at),
                "capture_policy_id": target.policy_id,
                "capture_policy_version": target.policy_version,
                "detector_set_version": target.detector_set_version,
                "redaction_state": state,
                "parts": [
                    {
                        "part": p["part"],
                        "char_count": p.get("char_count", len(p.get("text", ""))),
                        "truncated": bool(p["truncated"]),
                    }
                    for p in parts
                ],
                "content_ref": None,
                "findings_summary": [
                    {"category": c, "count": min(n, 100_000), "action": a}
                    for (c, a), n in sorted(summary.items())
                ][:64],
                "sensitivity_categories": sorted(sensitivities),
                "retention_class": target.retention_class,
                "expires_at": format_timestamp(expires),
            }
        )

    async def _store_content(
        self,
        interaction_id: str,
        captured_at: datetime,
        outcome: _Outcome,
        target: CaptureTarget,
        event: CaptureEvent,
    ) -> None:
        try:
            record = self._record(
                interaction_id,
                captured_at,
                target,
                event,
                state=outcome.state,
                parts=outcome.parts,
                findings=outcome.findings,
            )
            content = RedactedContent.model_validate(
                {
                    "schema_version": _CONTENT_SCHEMA_VERSION,
                    "interaction_id": interaction_id,
                    "redaction_state": outcome.state,
                    "detector_set_version": target.detector_set_version,
                    "parts": outcome.parts,
                }
            )
        except Exception:
            raise _CaptureFailed("content_rejected") from None
        try:
            await self._store.put(record, content, capture_retention_days=target.retention_days)
        except Exception as exc:
            reason = _store_failure_reason(exc)
        else:
            return
        # Belt and braces: the store removes its own orphan, but no blob may outlive a failure.
        await self._delete_blob(event, interaction_id, captured_at)
        raise _CaptureFailed(reason)

    async def _delete_blob(self, event: CaptureEvent, interaction_id: str, at: datetime) -> None:
        try:
            name = content_blob_name(event.customer_id, event.domain_id, at, interaction_id)
            await self._store.content.delete(name)
        except Exception:
            self.stats.cleanup_failed += 1

    async def _discard(self, event: CaptureEvent, interaction_id: str, at: datetime) -> None:
        """Remove stored content after a failed audit write (blob, then index document)."""
        try:
            await self._store.delete(event.customer_id, event.domain_id, interaction_id)
        except Exception:
            self.stats.cleanup_failed += 1
            await self._delete_blob(event, interaction_id, at)

    async def _write_failure_record(self, record: InteractionRecord) -> None:
        try:
            await self._store.index.create(record)
        except InteractionStoreError as exc:
            if exc.reason != INTERACTION_EXISTS:
                raise
            await self._store.index.replace(record)

    async def _fail(
        self,
        reason: FailureReason,
        interaction_id: str,
        captured_at: datetime,
        body: ExtractedBody,
        target: CaptureTarget,
        event: CaptureEvent,
        audit: CaptureAuditWriter,
    ) -> PayloadRef:
        self.stats.capture_failed[reason] += 1
        self._failed_counter.add(1, {"ns.reason": reason})
        sizes = _part_sizes(body)
        try:
            record = self._record(
                interaction_id,
                captured_at,
                target,
                event,
                state="redaction_failed",
                parts=sizes,
                findings=(),
            )
            await self._write_failure_record(record)
        except Exception:
            self.stats.failure_record_failed += 1
        outcome = _Outcome(sizes, [], "redaction_failed")
        await self._audit(
            audit,
            self._audit_event(
                AUDIT_OP_CAPTURE_DROPPED, interaction_id, target, event, outcome, reason
            ),
        )
        return self._payload_ref(interaction_id, target, outcome)

    async def _audit(self, audit: CaptureAuditWriter, entry: CaptureAuditEvent) -> bool:
        try:
            await audit(entry)
        except Exception:
            self.stats.audit_write_failed += 1
            return False
        return True

    @staticmethod
    def _audit_event(
        operation: Literal["interaction.capture", "interaction.capture_dropped"],
        interaction_id: str,
        target: CaptureTarget,
        event: CaptureEvent,
        outcome: _Outcome,
        reason: str | None,
    ) -> CaptureAuditEvent:
        return CaptureAuditEvent(
            operation=operation,
            customer_id=event.customer_id,
            domain_id=event.domain_id,
            source_id=event.source_id,
            event_id=event.event_id,
            correlation_id=event.correlation_id,
            interaction_id=interaction_id,
            capture_policy_id=target.policy_id,
            capture_policy_version=target.policy_version,
            detector_set_version=target.detector_set_version,
            redaction_state=outcome.state,
            reason=reason,
            part_count=len(outcome.parts),
            finding_count=sum(f.count for f in outcome.findings),
            detected_category_count=len({f.category for f in outcome.findings}),
        )

    @staticmethod
    def _payload_ref(interaction_id: str, target: CaptureTarget, outcome: _Outcome) -> PayloadRef:
        categories = sorted({f.category for f in outcome.findings})
        return PayloadRef.model_validate(
            {
                "pointer": interaction_pointer(interaction_id),
                "redaction_state": outcome.state,
                "interaction_id": interaction_id,
                "capture_policy_id": target.policy_id,
                "capture_policy_version": target.policy_version,
                "detector_set_version": target.detector_set_version,
                "detected_categories": categories[:32],
                "content_parts": [
                    {
                        "part": p["part"],
                        "char_count": p.get("char_count", len(p.get("text", ""))),
                        "truncated": bool(p["truncated"]),
                    }
                    for p in outcome.parts
                ],
            }
        )

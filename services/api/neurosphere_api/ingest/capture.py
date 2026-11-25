"""Ingest-edge capture adapter (PRP-103 item 3).

:class:`EdgeCapture` is what :meth:`IngestService.attach_capture` takes: the capture matcher
(PRP-103 item 1), the capture pipeline (item 2) and the audit writer for the domain chain. The
ingest service calls it only on the OTLP traces and CloudEvents telemetry paths, and only while
:attr:`EdgeCapture.active` is true (some policy can match); otherwise the edge is unchanged.

Per request the service (1) extracts body parts from the parsed document BEFORE
``drop_body_fields`` (:meth:`EdgeCapture.collect`, at most ``max_items_per_request`` items with a
body; the rest are counted, never captured), (2) maps and validates each item as today, (3) asks
the matcher per item, keyed on the stamped registered source and the payload ``domain_id`` (no
domain, no capture: GD-46), and (4) runs the bounded pipeline, which returns the ``payload_ref``
the service puts on the mapped ``TelemetryEvent`` (copy with update) before the hub message is
built. A shed or failure never fails the telemetry item: the event is published without a
``payload_ref`` (shed) or with ``redaction_state: redaction_failed`` (failure).

Captured values are secret-grade. Nothing here logs, raises with, labels a metric with, or
audits a value: only ids, reason codes and counts leave this module.
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from collections import Counter
from collections.abc import Awaitable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.audit import AuditDraft, make_subject, sha256_digest
from neurosphere_core.audit.builders import AuditContext, build_after
from neurosphere_core.audit.chains import domain_audit_chain_id
from neurosphere_core.interactions import (
    AUDIT_OP_CAPTURE,
    CaptureAuditEvent,
    CaptureAuditWriter,
    CaptureDecision,
    CaptureEvent,
    CaptureMatcher,
    CaptureOffReason,
    CapturePipeline,
    CaptureTarget,
    ExtractedBody,
    extract_body_parts,
    interaction_pointer,
)
from neurosphere_core.payload.guard import find_body_fields, is_body_field

from neurosphere_api.ingest import otlp_mapping as om

__all__ = [
    "DEFAULT_MAX_ITEMS_PER_REQUEST",
    "EDGE_ACTOR",
    "EDGE_SCOPE_HASH",
    "ENV_MAX_ITEMS_PER_REQUEST",
    "INTERACTION_ENTITY_TYPE",
    "AuditAppender",
    "CaptureJob",
    "EdgeCapture",
    "EdgeCaptureStats",
    "capture_audit_draft",
    "capture_target_for",
    "domain_audit_writer",
    "edge_correlation_id",
    "max_items_per_request_from_env",
    "surviving_items",
]

#: Per-request cap on items that are captured (PRP-103 Interfaces provided).
ENV_MAX_ITEMS_PER_REQUEST: Final = "NS_INTERACTION_CAPTURE_MAX_ITEMS_PER_REQUEST"
DEFAULT_MAX_ITEMS_PER_REQUEST: Final = 100
#: ``TargetRef.entity_type`` of a captured interaction in audit records.
INTERACTION_ENTITY_TYPE: Final = "interaction"
#: Actor of capture audit records: the platform's ingest edge, never the producer.
EDGE_ACTOR: Final = Actor(
    principal_pseudonym="svc.neurosphere-ingest",
    principal_kind="service_principal",
    on_behalf_of=None,
)
#: Scope hash of edge-originated capture records: a fixed digest, never a user's scope.
EDGE_SCOPE_HASH: Final = sha256_digest({"system_scope": "neurosphere.ingest.capture"})
#: Edge-only failure reason: the pipeline raised instead of returning (never expected).
EDGE_ERROR: Final = "edge_error"
#: Edge-only failure reason: extraction raised (never expected; extraction is pure).
EXTRACTION_FAILED: Final = "extraction_failed"

_CORRELATION: Final = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def max_items_per_request_from_env(environ: Mapping[str, str] | None = None) -> int:
    """``NS_INTERACTION_CAPTURE_MAX_ITEMS_PER_REQUEST`` (default 100; 0 captures nothing).

    Raises ``ValueError`` (naming the variable, not echoing the value) when it is not a
    non-negative integer, so a misconfiguration is reported at startup.
    """
    env = os.environ if environ is None else environ
    raw = env.get(ENV_MAX_ITEMS_PER_REQUEST)
    if raw is None or not raw.strip():
        return DEFAULT_MAX_ITEMS_PER_REQUEST
    try:
        value = int(raw.strip())
    except ValueError:
        raise ValueError(f"{ENV_MAX_ITEMS_PER_REQUEST} must be a non-negative integer") from None
    if value < 0:
        raise ValueError(f"{ENV_MAX_ITEMS_PER_REQUEST} must be a non-negative integer")
    return value


def edge_correlation_id(request_correlation_id: str | None = None) -> str:
    """Audit-safe correlation id for one ingest request.

    The request's correlation id (``x-correlation-id``) when given, in the ``corr-<hex>`` form
    the audit content guard accepts (a dashed GUID outside the allowed slots is refused); else
    a fresh ``ingest-<hex>`` id shared by every item of the request.
    """
    if request_correlation_id:
        candidate = "corr-" + request_correlation_id.replace("-", "")
        if _CORRELATION.fullmatch(candidate):
            return candidate
    return "ingest-" + uuid.uuid4().hex


def _is_dropped_item(item: Any) -> bool:
    """True when ``drop_body_fields`` removes ``item`` whole from a list (OTLP attribute item)."""
    if isinstance(item, dict) and "value" in item:
        key = item.get("key")
        return isinstance(key, str) and is_body_field(key)
    return False


def surviving_items(items: Any) -> list[Any]:
    """The elements of a raw list that ``drop_body_fields`` keeps, in order (index-aligned with
    the dropped document). Anything that is not a list yields nothing."""
    if not isinstance(items, list):
        return []
    return [item for item in items if not _is_dropped_item(item)]


def capture_target_for(decision: CaptureDecision, *, source_id: str) -> CaptureTarget:
    """The pipeline input for a matched policy; ``source_id`` is the stamped registered source
    the matcher matched on (one of the policy's ``source_ids``)."""
    policy = decision.policy
    return CaptureTarget(
        policy_id=policy.policy_id,
        policy_version=policy.version,
        domain_id=policy.domain,
        source_id=source_id,
        detector_set_version=policy.detector_set_version,
        retention_days=policy.retention_days if policy.retention_days is not None else 90,
        max_per_minute=policy.sampling.max_per_minute,
        redaction_mode=policy.redaction_mode or "redact_all_detections",
        kept_categories=frozenset(c.root for c in policy.kept_categories or []),
        parts=frozenset(p.root for p in policy.parts),
        max_part_chars=policy.max_part_chars if policy.max_part_chars is not None else 8192,
        retention_class=policy.retention_class,
        customer_dictionary_ids=tuple(d.root for d in policy.customer_dictionary_ids or []),
    )


def capture_audit_draft(entry: CaptureAuditEvent, *, cloud: str) -> AuditDraft:
    """``interaction.capture`` / ``interaction.capture_dropped`` as an ``after`` record.

    Ids, a state or reason code and a digest of the metadata only. The interaction id is a
    UUID, so the ``interaction:<id>`` pointer sits in ``subject.snapshot_ref`` (a GUID-allowed
    slot of the audit content guard) and in the target canonical id (not a person type).
    """
    ctx = AuditContext.model_validate(
        {
            "actor": EDGE_ACTOR.model_dump(mode="json"),
            "scope_hash": EDGE_SCOPE_HASH,
            "correlation_id": entry.correlation_id,
            "operation": entry.operation,
            "channel": "rest",
            "intent_id": None,
        }
    )
    subject = make_subject(
        f"{cloud}:{entry.customer_id}:neurosphere:{INTERACTION_ENTITY_TYPE}:{entry.interaction_id}",
        INTERACTION_ENTITY_TYPE,
        target_version=str(entry.capture_policy_version),
        state=entry.details(),
        snapshot_ref=interaction_pointer(entry.interaction_id),
    )
    captured = entry.operation == AUDIT_OP_CAPTURE
    detail = (
        f"redaction_state={entry.redaction_state}"
        if captured
        else f"reason={entry.reason or 'redaction_failed'}"
    )
    return build_after(
        ctx,
        subject,
        result="succeeded" if captured else "failed",
        verified=captured,
        detail=detail,
    )


class AuditAppender(Protocol):
    """What the writer needs from :class:`neurosphere_core.audit.AuditRepository`."""

    def append(self, chain_id: str, draft: AuditDraft) -> Awaitable[object]: ...


def domain_audit_writer(repository: AuditAppender, *, cloud: str) -> CaptureAuditWriter:
    """A :data:`CaptureAuditWriter` appending to the event domain's audit chain.

    Any failure (an unencodable domain, the content guard, the store) propagates, so the
    pipeline keeps no content for that capture.
    """

    async def write(entry: CaptureAuditEvent) -> object:
        chain_id = domain_audit_chain_id(entry.customer_id, entry.domain_id)
        return await repository.append(chain_id, capture_audit_draft(entry, cloud=cloud))

    return write


@dataclass(slots=True)
class EdgeCaptureStats:
    """Counters for ``app.state.interaction_capture_stats`` (integers and reason codes only).

    ``captured``, ``capture_failed{reason}`` and ``capture_shed`` are the pipeline's
    :class:`~neurosphere_core.interactions.CaptureStats`; the edge adds
    ``capture_skipped_no_policy`` (through the same stats object), the per-reason breakdown of
    those skips and ``capture_skipped_item_cap``.
    """

    pipeline: CapturePipeline
    capture_skipped_item_cap: int = 0
    skipped_reasons: Counter[str] = field(default_factory=Counter[str])

    @property
    def captured(self) -> int:
        return self.pipeline.stats.captured

    @property
    def capture_skipped_no_policy(self) -> int:
        return self.pipeline.stats.capture_skipped_no_policy

    @property
    def capture_failed(self) -> Counter[str]:
        return self.pipeline.stats.capture_failed

    @property
    def capture_shed(self) -> int:
        return self.pipeline.stats.capture_shed

    def snapshot(self) -> dict[str, Any]:
        out = self.pipeline.stats.snapshot()
        out["capture_skipped_item_cap"] = self.capture_skipped_item_cap
        out["skipped_reasons"] = dict(sorted(self.skipped_reasons.items()))
        out["in_flight"] = self.pipeline.in_flight
        return out


@dataclass(frozen=True, slots=True)
class CaptureJob:
    """One telemetry item to capture: where its message sits, its scope, event and body."""

    slot: int
    scope: om.Scope
    event: TelemetryEvent
    body: ExtractedBody = field(repr=False)
    cost_center: str | None = None


class EdgeCapture:
    """Matcher + pipeline + audit writer, attached to the ingest service (item 4 builds it).

    ``matcher`` can be swapped with :meth:`replace_matcher` (a refreshed policy snapshot).
    """

    def __init__(
        self,
        matcher: CaptureMatcher,
        pipeline: CapturePipeline,
        audit: CaptureAuditWriter,
        *,
        max_items_per_request: int = DEFAULT_MAX_ITEMS_PER_REQUEST,
    ) -> None:
        if max_items_per_request < 0:
            raise ValueError("max_items_per_request must be non-negative")
        self._matcher = matcher
        self._pipeline = pipeline
        self._audit = audit
        self.max_items_per_request = max_items_per_request
        self.stats = EdgeCaptureStats(pipeline)

    @property
    def matcher(self) -> CaptureMatcher:
        return self._matcher

    @property
    def pipeline(self) -> CapturePipeline:
        return self._pipeline

    def replace_matcher(self, matcher: CaptureMatcher) -> None:
        self._matcher = matcher

    def status(self) -> CaptureOffReason | None:
        """The deployment-wide off reason, or ``None`` when some policy can match."""
        return self._matcher.status()

    @property
    def active(self) -> bool:
        """True when some policy can match (the service's only per-request check)."""
        return self._matcher.status() is None

    # -- per request -------------------------------------------------------------------------
    def collect(self, items: Iterable[Any]) -> list[ExtractedBody | None]:
        """Body parts per item, index-aligned with ``items``; ``None`` for no body or past the
        per-request cap (counted in ``capture_skipped_item_cap``)."""
        out: list[ExtractedBody | None] = []
        taken = 0
        for item in items:
            if taken >= self.max_items_per_request:
                if find_body_fields(item):
                    self.stats.capture_skipped_item_cap += 1
                out.append(None)
                continue
            try:
                body = extract_body_parts(item)
            except Exception:
                # Pure code; a failure here is a bug. The item is not captured (counted).
                self.count_failure(EXTRACTION_FAILED)
                body = None
            if body is not None:
                taken += 1
            out.append(body)
        return out

    def count_failure(self, reason: str) -> None:
        """Count an edge-side failure under ``capture_failed{reason}`` (a reason code only)."""
        self._pipeline.stats.capture_failed[reason] += 1

    def _decide(self, scope: om.Scope, event: TelemetryEvent) -> CaptureDecision | None:
        domain = event.domain_id.root if event.domain_id is not None else None
        match = self._matcher.evaluate(scope.source_id, domain, event.event_id.root)
        decision = match.decision
        reason: str | None = match.off_reason
        if decision is not None and (
            decision.policy.customer != scope.customer_id
            or decision.policy.cloud.root != scope.cloud
        ):
            # Defence in depth: a policy of another tenant never captures this producer's data.
            decision, reason = None, "domain_mismatch"
        if decision is None:
            self._pipeline.stats.skipped_no_policy()
            self.stats.skipped_reasons[reason or "no_policy"] += 1
        return decision

    async def _capture_one(self, job: CaptureJob, correlation_id: str) -> TelemetryEvent | None:
        """Never raises (except cancellation): an exception escaping here would fail the whole
        request through ``gather`` while sibling captures kept running detached, storing
        content for telemetry that is never published."""
        try:
            return await self._try_capture(job, correlation_id)
        except Exception:
            # Never expected (the pipeline turns failures into redaction_failed). The exception
            # is dropped unlogged: it may carry captured text. Telemetry is still accepted.
            self.count_failure(EDGE_ERROR)
            return None

    async def _try_capture(self, job: CaptureJob, correlation_id: str) -> TelemetryEvent | None:
        decision = self._decide(job.scope, job.event)
        if decision is None:
            return None
        event = job.event
        domain = event.domain_id.root if event.domain_id is not None else ""
        target = capture_target_for(decision, source_id=job.scope.source_id)
        capture_event = CaptureEvent(
            cloud=job.scope.cloud,
            customer_id=job.scope.customer_id,
            domain_id=domain,
            source_id=job.scope.source_id,
            event_id=event.event_id.root,
            correlation_id=correlation_id,
            occurred_at=event.event_time.root,
            trace_id=event.trace_id.root if event.trace_id is not None else None,
            span_id=event.span_id.root if event.span_id is not None else None,
        )
        ref = await self._pipeline.capture(job.body, target, capture_event, audit=self._audit)
        if ref is None:
            return None
        return event.model_copy(update={"payload_ref": ref})

    async def run(
        self, jobs: Sequence[CaptureJob], correlation_id: str
    ) -> list[tuple[CaptureJob, TelemetryEvent]]:
        """Capture every job concurrently (the pipeline bounds in-flight work and sheds the
        rest); return the jobs whose event now carries a ``payload_ref``."""
        results = await asyncio.gather(*(self._capture_one(job, correlation_id) for job in jobs))
        return [(job, event) for job, event in zip(jobs, results, strict=True) if event is not None]

"""Action-plane audit port and its default implementation over the PRP-06 audit store.

Every state transition (a ``before`` record written BEFORE the store write and an ``after``
record once it is durable), every refusal (``denied``) and every executor phase is recorded as
an :class:`ActionAuditEvent`. :class:`AuditRepositoryActionAuditor` maps events onto the PRP-01
``AuditRecord`` contract and appends them to the domain's hash chain
(``<customer_id>.<domain name>``, the ``audit_mount`` convention). Records carry the actor
pseudonym, target id/version, a digest of the intent document and machine codes only; the real
principal id, the diff body and connector payloads never reach the audit log (the PRP-06
content guard rejects anything else at seal time).

Fail closed: when an audit append fails the auditor raises (``dependency_transient``,
``audit_write_failed``) and the service aborts the transition before the intent is written.
"""

from __future__ import annotations

from typing import Final, Literal, Protocol, runtime_checkable

from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from pydantic import BaseModel, ConfigDict

from neurosphere_core.actions.models import CallerChannel, ExecutionPhase
from neurosphere_core.audit import (
    AuditDraft,
    AuditRepository,
    assert_metadata_only,
    make_subject,
)
from neurosphere_core.audit.builders import DenialCode, OutcomeResult

__all__ = [
    "ActionAuditEvent",
    "ActionAuditor",
    "AuditRepositoryActionAuditor",
    "RecordingActionAuditor",
    "action_audit_chain_id",
]

_DETAIL_MAX: Final = 128


class ActionAuditEvent(BaseModel):
    """One audit fact about an intent. ``state_digest`` is a digest, never a body.

    * transition: ``from_state``/``to_state`` set; ``kind`` ``before`` then ``after``.
    * denial: ``kind`` ``denied`` with ``denial_code`` (taxonomy code) and ``reason``.
    * execution phase: ``phase`` set; ``state_digest`` is the TARGET state digest the executor
      captured (before apply / after verify), ``result``/``verified`` on ``after`` records.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["before", "after", "denied"]
    operation: str
    actor: Actor
    scope_hash: str
    correlation_id: str
    channel: CallerChannel | None
    customer_id: str
    domain_id: str
    intent_id: str | None
    target: TargetRef
    target_version: str | None
    state_digest: str | None = None
    from_state: str | None = None
    to_state: str | None = None
    phase: ExecutionPhase | None = None
    result: OutcomeResult | None = None
    verified: bool = False
    denial_code: DenialCode | None = None
    reason: str | None = None


@runtime_checkable
class ActionAuditor(Protocol):
    async def record(self, event: ActionAuditEvent) -> None:
        """Durably record ``event`` or raise (fail closed)."""
        ...


def action_audit_chain_id(customer_id: str, domain_id: str) -> str:
    """Audit chain of a domain: ``<customer>.<domain name>``.

    Mirrors ``neurosphere_api.catalog.service.audit_chain_for`` (core cannot import the API), so
    action records land in the chain the audit read API exposes for that domain.
    """
    return f"{customer_id}.{domain_id.rsplit(':', 1)[-1]}"


def _detail(event: ActionAuditEvent) -> str | None:
    parts: list[str] = []
    if event.from_state is not None or event.to_state is not None:
        parts.append(f"transition={event.from_state or 'none'}:{event.to_state or 'none'}")
    if event.phase is not None:
        parts.append(f"phase={event.phase}")
    if event.reason is not None and event.kind != "denied":
        parts.append(f"reason={event.reason}")
    if not parts:
        return None
    return ".".join(parts)[:_DETAIL_MAX]


def _to_draft(event: ActionAuditEvent) -> AuditDraft:
    subject = make_subject(
        event.target.canonical_id,
        event.target.entity_type,
        target_version=event.target_version,
        state_digest=event.state_digest,
    )
    outcome = None
    denial = None
    if event.kind == "denied":
        denial = {"code": event.denial_code or "forbidden", "reason": event.reason or "denied"}
    elif event.kind == "after":
        outcome = {
            "result": event.result or "succeeded",
            "verified": event.verified,
            "detail": _detail(event),
        }
    return AuditDraft.model_validate(
        {
            "kind": event.kind,
            "actor": event.actor.model_dump(mode="json"),
            "scope_hash": event.scope_hash,
            "correlation_id": event.correlation_id,
            "operation": event.operation,
            "channel": event.channel,
            "intent_id": event.intent_id,
            "subject": subject.model_dump(mode="json"),
            "outcome": outcome,
            "denial": denial,
        }
    )


class AuditRepositoryActionAuditor:
    """Default :class:`ActionAuditor`: appends to the PRP-06 hash-chained audit repository."""

    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    async def record(self, event: ActionAuditEvent) -> None:
        await self._repository.append(
            action_audit_chain_id(event.customer_id, event.domain_id), _to_draft(event)
        )


class RecordingActionAuditor:
    """In-memory auditor for tests: keeps events in order; ``fail_with`` simulates an outage.

    Each event is also converted to an ``AuditDraft`` so a test cannot record an event the real
    auditor would reject.
    """

    def __init__(self) -> None:
        self.events: list[ActionAuditEvent] = []
        self.error: Exception | None = None

    def fail_with(self, error: Exception | None) -> None:
        self.error = error

    async def record(self, event: ActionAuditEvent) -> None:
        if self.error is not None:
            raise self.error
        assert_metadata_only(_to_draft(event).model_dump(mode="json"))
        self.events.append(event)

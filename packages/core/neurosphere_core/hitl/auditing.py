"""Audit wiring shared by the HITL service, decision log, notifier stubs and timer worker.

Chain convention (same as catalog/curation): one hash chain per domain, ``<customer>.<name>``
where ``name`` is the last segment of the canonical domain id. A review item is addressed in
audit records as ``<cloud>:<customer>:hitl:review_item:<item_id>``; its state appears only as a
digest, never as a body (PRP-06 metadata-only guard).
"""

from __future__ import annotations

from typing import Final

from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_contracts.audit.v1.audit_record import Subject

from neurosphere_core.audit import AuditContext, make_subject, sha256_digest
from neurosphere_core.audit.builders import Channel
from neurosphere_core.errors import NeuroSphereError
from neurosphere_core.hitl.models import ReviewItem

__all__ = [
    "ENTITY_TYPE",
    "SYSTEM_ACTOR",
    "SYSTEM_SCOPE_HASH",
    "audit_chain_for",
    "audit_context",
    "item_subject",
    "refusal_code",
]

ENTITY_TYPE: Final = "review_item"

#: Actor for records written by the platform itself (timers, notifier stubs, queue intake).
SYSTEM_ACTOR: Final = Actor(
    principal_pseudonym="svc.neurosphere-hitl",
    principal_kind="service_principal",
    on_behalf_of=None,
)
#: Scope hash for system-originated records: a fixed digest, never a user's scope.
SYSTEM_SCOPE_HASH: Final = sha256_digest({"system_scope": "neurosphere.hitl"})


def audit_chain_for(customer_id: str, domain_id: str) -> str:
    return f"{customer_id}.{domain_id.rsplit(':', 1)[-1]}"


def item_subject(item: ReviewItem, *, state_digest: str | None = None) -> Subject:
    """Subject for ``item``: its canonical id, ETag as version, and a digest of its state."""
    digest = state_digest or sha256_digest(
        item.model_dump(
            mode="json",
            exclude={"etag", "maker_principal_id", "maker_on_behalf_of_principal_id"},
        )
    )
    return make_subject(
        f"{item.cloud}:{item.customer_id}:hitl:{ENTITY_TYPE}:{item.item_id}",
        ENTITY_TYPE,
        target_version=item.etag,
        state_digest=digest,
    )


def audit_context(
    *,
    actor: Actor,
    scope_hash: str,
    correlation_id: str,
    operation: str,
    channel: Channel | None,
    intent_id: str | None = None,
) -> AuditContext:
    return AuditContext.model_validate(
        {
            "actor": actor.model_dump(mode="json"),
            "scope_hash": scope_hash,
            "correlation_id": correlation_id,
            "operation": operation,
            "channel": channel,
            "intent_id": intent_id,
        }
    )


def refusal_code(exc: BaseException) -> str:
    """Short machine code for an audit record: the error's reason, else its code."""
    if isinstance(exc, NeuroSphereError):
        reason = getattr(exc, "reason", None)
        return reason if isinstance(reason, str) and reason else exc.code
    return "error"

"""Allow / deny / before / after record builders over the PRP-01 ``AuditRecord`` contract.

A builder returns an unsealed :class:`AuditDraft`; the repository assigns ``audit_id``,
``chain_id``, ``sequence``, ``previous_hash``, ``recorded_at`` and ``record_hash`` at append.

Mapping to the contract (which has exactly three kinds: ``before``, ``after``, ``denied``):

* deny   -> ``denied``  with a taxonomy code and a snake_case reason code.
* before -> ``before``  intent recorded before a change, with the target and its state digest.
* after  -> ``after``   outcome of a change, with the target and its new state digest.
* allow  -> ``after``   for a permitted non-mutating operation (read/query/export): outcome
  ``succeeded``, ``verified=False`` (nothing was changed, so nothing was read back) and
  ``detail="decision=allow"``. The contract has no ``allowed`` kind; this is the documented
  representation until a contract revision adds one.

Actor and scope hash come from the server-derived ``IdentityScope``
(:meth:`AuditContext.from_scope`), never from request input. Target state is recorded as a
digest only; bodies are never stored.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Literal

from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_contracts.audit.v1.audit_record import Denial, Outcome, Sha256Hash, Subject, Uuid
from pydantic import BaseModel, ConfigDict

from neurosphere_core.audit.canonical import sha256_digest
from neurosphere_core.scope import IdentityScope

ALLOW_DETAIL: Final = "decision=allow"

Kind = Literal["before", "after", "denied"]
Channel = Literal["button", "chat", "rest", "mcp", "websocket", "worker"]
DenialCode = Literal[
    "unauthorized",
    "forbidden",
    "capability_unavailable",
    "stale_version",
    "rate_limited",
    "invalid_schema",
    "dependency_transient",
]
OutcomeResult = Literal["succeeded", "failed", "rolled_back"]


class AuditDraft(BaseModel):
    """The caller-supplied half of an ``AuditRecord`` (no chain or hash fields)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Kind
    actor: Actor
    scope_hash: Sha256Hash
    correlation_id: str
    operation: str
    channel: Channel | None
    intent_id: Uuid | None
    subject: Subject | None
    outcome: Outcome | None
    denial: Denial | None


class AuditContext(BaseModel):
    """Who/what/where for one request. Prefer :meth:`from_scope` (server-derived identity)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actor: Actor
    scope_hash: Sha256Hash
    correlation_id: str
    operation: str
    channel: Channel | None
    intent_id: Uuid | None = None

    @classmethod
    def from_scope(
        cls,
        scope: IdentityScope,
        *,
        correlation_id: str,
        operation: str,
        channel: Channel | None,
        intent_id: str | None = None,
        on_behalf_of: str | None = None,
    ) -> AuditContext:
        """Actor pseudonym, principal kind and scope hash taken from the verified scope."""
        contract = scope.to_contract()
        return cls.model_validate(
            {
                "actor": {
                    "principal_pseudonym": contract.principal.principal_pseudonym,
                    "principal_kind": contract.principal.principal_kind,
                    "on_behalf_of": on_behalf_of,
                },
                "scope_hash": contract.scope_hash,
                "correlation_id": correlation_id,
                "operation": operation,
                "channel": channel,
                "intent_id": intent_id,
            }
        )


def make_subject(
    canonical_id: str,
    entity_type: str,
    *,
    target_version: str | None = None,
    state: Mapping[str, Any] | None = None,
    state_digest: str | None = None,
    snapshot_ref: str | None = None,
) -> Subject:
    """Target reference plus a digest of its state. ``state`` is hashed and discarded."""
    if state is not None and state_digest is not None:
        raise ValueError("pass state or state_digest, not both")
    digest = sha256_digest(dict(state)) if state is not None else state_digest
    return Subject.model_validate(
        {
            "target": {"canonical_id": canonical_id, "entity_type": entity_type},
            "target_version": target_version,
            "state_digest": digest,
            "snapshot_ref": snapshot_ref,
        }
    )


def _draft(
    ctx: AuditContext,
    kind: Kind,
    *,
    subject: Subject | None,
    outcome: Outcome | None = None,
    denial: Denial | None = None,
) -> AuditDraft:
    return AuditDraft(
        kind=kind,
        actor=ctx.actor,
        scope_hash=ctx.scope_hash,
        correlation_id=ctx.correlation_id,
        operation=ctx.operation,
        channel=ctx.channel,
        intent_id=ctx.intent_id,
        subject=subject,
        outcome=outcome,
        denial=denial,
    )


def build_before(ctx: AuditContext, subject: Subject) -> AuditDraft:
    """Intent and pre-change target state, written BEFORE the mutation runs."""
    return _draft(ctx, "before", subject=subject)


def build_after(
    ctx: AuditContext,
    subject: Subject,
    *,
    result: OutcomeResult,
    verified: bool,
    detail: str | None = None,
) -> AuditDraft:
    """Outcome and post-change target state. ``detail`` must be a short machine code."""
    outcome = Outcome(result=result, verified=verified, detail=detail)
    return _draft(ctx, "after", subject=subject, outcome=outcome)


def build_allowed(ctx: AuditContext, subject: Subject) -> AuditDraft:
    """A permitted non-mutating operation (see module docstring for the contract mapping)."""
    outcome = Outcome(result="succeeded", verified=False, detail=ALLOW_DETAIL)
    return _draft(ctx, "after", subject=subject, outcome=outcome)


def build_denied(
    ctx: AuditContext,
    *,
    code: DenialCode,
    reason: str,
    subject: Subject | None = None,
) -> AuditDraft:
    """A refused request. ``subject`` is optional (the target may not have been resolved)."""
    denial = Denial(code=code, reason=reason)
    return _draft(ctx, "denied", subject=subject, denial=denial)


def is_allow_record(kind: str, detail: str | None) -> bool:
    """True for records produced by :func:`build_allowed`."""
    return kind == "after" and detail == ALLOW_DETAIL

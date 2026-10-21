"""Server-side action models: the ``StoredIntent`` envelope (PRP-17 delta D2) and friends.

``ActionIntent.actor`` carries only a pseudonym, so the store keeps the contract intent inside a
server-only envelope with the real ``principal_id`` (used for maker checks, self-approval,
permission rechecks and idempotency), the partition (``customer_id``, ``domain_id``), the store
ETag, the ``payload_digest`` used for idempotency-key reuse detection and the executor's
:class:`ExecutionRecord`. The envelope never leaves the server: API views expose ``intent`` and
derived flags only. ``principal_id`` is excluded from ``repr`` so it cannot reach a log line by
accident.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal

from neurosphere_contracts.actions.v1.action_intent import (
    ActionIntent,
    EvidenceRef,
    ProposedDiff,
)
from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from neurosphere_core.actions.hashing import diff_to_wire, intent_to_wire
from neurosphere_core.audit.canonical import sha256_digest
from neurosphere_core.scope import IdentityScope

__all__ = [
    "PHASE_ORDER",
    "ActionCaller",
    "CallerChannel",
    "CanaryOutcome",
    "CreateOutcome",
    "DraftRequest",
    "ExecutionPhase",
    "ExecutionRecord",
    "IntentChannel",
    "IntentKey",
    "StoredIntent",
    "compute_payload_digest",
    "format_expiry",
    "format_timestamp",
    "idempotency_lookup_id",
    "parse_timestamp",
]

SHA256_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"
REASON_PATTERN: Final = r"^[a-z][a-z0-9_]{0,63}$"
CUSTOMER_PATTERN: Final = r"^[a-z0-9._-]{1,128}$"

IntentChannel = Literal["button", "chat", "rest", "mcp"]
CallerChannel = Literal["button", "chat", "rest", "mcp", "websocket", "worker"]

ExecutionPhase = Literal[
    "pending",
    "rechecked",
    "dry_run_done",
    "applying",
    "applied",
    "canary",
    "verifying",
    "rolling_back",
    "done",
]
#: Executor phases in their normal order. ``rolling_back`` follows a failed canary or verify.
PHASE_ORDER: Final[tuple[str, ...]] = (
    "pending",
    "rechecked",
    "dry_run_done",
    "applying",
    "applied",
    "canary",
    "verifying",
    "rolling_back",
    "done",
)
_APPLY_TOUCHED: Final = frozenset(
    {"applying", "applied", "canary", "verifying", "rolling_back", "done"}
)
CanaryOutcome = Literal["passed", "failed", "verify_only"]


# -- timestamps ---------------------------------------------------------------------------------


def _utc(instant: datetime) -> datetime:
    if instant.tzinfo is None:
        raise ValueError("action timestamps must be timezone-aware")
    return instant.astimezone(UTC)


def format_timestamp(instant: datetime) -> str:
    """Contract ``UtcTimestamp`` with fixed microsecond precision (sorts lexically)."""
    utc = _utc(instant)
    return utc.strftime("%Y-%m-%dT%H:%M:%S") + f".{utc.microsecond:06d}Z"


def format_expiry(instant: datetime) -> str:
    """Whole-second ``UtcTimestamp`` used for ``confirmation_expires_at`` (as in the vector)."""
    return _utc(instant).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timestamp(value: str) -> datetime:
    """Parse a contract ``UtcTimestamp`` (``Z`` suffix, up to 9 fractional digits)."""
    text = value.removesuffix("Z")
    if "." in text:
        head, fraction = text.split(".", 1)
        text = f"{head}.{fraction[:6].ljust(6, '0')}"
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


# -- caller ---------------------------------------------------------------------------------------


class ActionCaller(BaseModel):
    """Who is calling the action service, for one request. Build it from the verified scope.

    ``principal_id`` is the real canonical principal id (never from a request body or a model);
    ``actor`` is the pseudonymous contract actor written to intents and audit records.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    principal_id: Annotated[str, Field(min_length=1, max_length=512, repr=False)]
    actor: Actor
    scope_hash: Annotated[str, Field(pattern=SHA256_PATTERN)]
    correlation_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")]
    channel: CallerChannel | None

    @classmethod
    def from_scope(
        cls,
        scope: IdentityScope,
        *,
        correlation_id: str,
        channel: CallerChannel | None,
        on_behalf_of: str | None = None,
    ) -> ActionCaller:
        contract = scope.to_contract()
        principal = contract.principal
        return cls.model_validate(
            {
                "principal_id": principal.principal_id.root,
                "actor": {
                    "principal_pseudonym": principal.principal_pseudonym,
                    "principal_kind": principal.principal_kind,
                    "on_behalf_of": on_behalf_of,
                },
                "scope_hash": contract.scope_hash,
                "correlation_id": correlation_id,
                "channel": channel,
            }
        )

    @classmethod
    def for_worker(cls, stored: StoredIntent, *, correlation_id: str | None = None) -> ActionCaller:
        """The executor acting on the maker's confirmed intent (audit channel ``worker``)."""
        return cls(
            principal_id=stored.principal_id,
            actor=stored.intent.actor,
            scope_hash=stored.scope_hash,
            correlation_id=correlation_id or stored.intent.correlation_id.root,
            channel="worker",
        )


# -- draft request -----------------------------------------------------------------------------


class DraftRequest(BaseModel):
    """What a surface supplies to draft an intent (wire contract ``POST .../intents`` body).

    Identity, scope, ids, timestamps and state are server-assigned; nothing here is trusted for
    authorization.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_kind: str
    target: TargetRef
    target_version: str
    proposed_diff: ProposedDiff
    evidence: list[EvidenceRef] = Field(default_factory=list[EvidenceRef])
    idempotency_key: str
    channel: IntentChannel = "rest"
    dry_run: bool = False


def compute_payload_digest(request: DraftRequest, *, customer_id: str, domain_id: str) -> str:
    """Digest of the logical draft payload, for idempotency-key reuse detection.

    Covers partition, kind, target, version, diff, evidence and ``dry_run``. ``channel`` is
    excluded on purpose: a retry of the same change through another surface is the same request
    (the confirmation hash is channel-free for the same reason).
    """
    return sha256_digest(
        {
            "customer_id": customer_id,
            "domain_id": domain_id,
            "action_kind": request.action_kind,
            "target": request.target.model_dump(mode="json"),
            "target_version": request.target_version,
            "proposed_diff": diff_to_wire(request.proposed_diff),
            "evidence": [e.model_dump(mode="json") for e in request.evidence],
            "dry_run": request.dry_run,
        }
    )


def idempotency_lookup_id(principal_id: str, idempotency_key: str) -> str:
    """Deterministic, opaque id of the ``(principal_id, idempotency_key)`` scope."""
    material = f"{principal_id}\x1f{idempotency_key}".encode()
    return "idem-" + hashlib.sha256(material).hexdigest()


# -- execution record ---------------------------------------------------------------------------


class ExecutionRecord(BaseModel):
    """Durable executor progress for one intent in ``executing`` (owned by PRP-17 item 2).

    It is the crash-safety record: a restarted worker reads it and resumes; it never repeats a
    non-idempotent apply. Field semantics:

    * ``phase`` - last phase the executor durably reached (see :data:`PHASE_ORDER`):
      ``pending`` (handed over, nothing done), ``rechecked`` (permission, target version and
      emergency disable rechecked), ``dry_run_done``, ``applying`` (written BEFORE the connector
      apply call; from here on the apply may have happened), ``applied`` (apply returned),
      ``canary`` (canary probe running), ``verifying`` (read-back running), ``rolling_back``,
      ``done`` (outcome recorded, final transition pending or written).
    * ``attempts`` - number of times an executor claimed the intent (:meth:`ActionService.
      begin_execution`); > 1 means a recovery.
    * ``lease_owner`` / ``lease_expires_at`` - the worker holding the intent; another worker may
      claim it only after the lease lapses.
    * ``rechecked_at`` - when the execution-time recheck last passed.
    * ``dry_run_result`` / ``apply_result`` / ``rollback_result`` - the connector results as
      plain JSON (core stays connector-agnostic). Metadata only: never secrets, tokens or bodies.
    * ``apply_started_at`` / ``apply_finished_at`` - bracket the apply call.
    * ``canary`` - ``passed``, ``failed`` or ``verify_only`` (no traffic-split canary, D4).
    * ``verify_matched`` - True only when the actual target state was read back and matched;
      ``None`` until verification ran. ``succeeded`` requires True (no pretend changes).
    * ``rolled_back`` - True once a rollback completed; ``rolled_back`` state requires it.
    * ``last_error`` - snake_case reason of the last failure (no free text).
    * ``details`` - extension point for executor-specific JSON metadata.
    * ``updated_at`` - last write.

    New fields must have defaults so stored records stay readable.
    """

    model_config = ConfigDict(extra="forbid")

    phase: ExecutionPhase = "pending"
    attempts: Annotated[int, Field(ge=0)] = 0
    lease_owner: Annotated[str | None, Field(max_length=256)] = None
    lease_expires_at: AwareDatetime | None = None
    rechecked_at: AwareDatetime | None = None
    dry_run_result: dict[str, Any] | None = None
    apply_started_at: AwareDatetime | None = None
    apply_finished_at: AwareDatetime | None = None
    apply_result: dict[str, Any] | None = None
    canary: CanaryOutcome | None = None
    verify_matched: bool | None = None
    rolled_back: bool = False
    rollback_result: dict[str, Any] | None = None
    last_error: Annotated[str | None, Field(pattern=REASON_PATTERN)] = None
    details: dict[str, Any] = Field(default_factory=dict[str, Any])
    updated_at: AwareDatetime | None = None

    def apply_may_have_happened(self) -> bool:
        """True once ``applying`` was recorded: recovery must verify, never re-apply."""
        return self.phase in _APPLY_TOUCHED or self.apply_started_at is not None


# -- stored intent -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IntentKey:
    """Address of one intent: its partition plus id."""

    customer_id: str
    domain_id: str
    intent_id: str


class StoredIntent(BaseModel):
    """Server-only envelope around the contract ``ActionIntent`` (delta D2).

    * ``principal_id`` - the maker's real canonical principal id.
    * ``customer_id`` / ``domain_id`` - partition (hierarchical key in Cosmos).
    * ``scope_hash`` - scope hash the maker drafted under (audit records written by workers).
    * ``payload_digest`` - :func:`compute_payload_digest` of the draft request.
    * ``advisory`` - the write connector reported advisory at validation: never executes.
    * ``requires_approval`` - set at confirmation from the action policy.
    * ``review_item_id`` - maker-checker review item linked by the HITL layer, if any.
    * ``due_at`` - instant the current non-terminal state lapses (expiry sweep); ``None`` for
      ``executing`` and terminal states.
    * ``execution`` - :class:`ExecutionRecord` once the intent entered ``executing``.
    * ``etag`` - store concurrency token; ``None`` until stored.
    """

    model_config = ConfigDict(extra="forbid")

    intent: ActionIntent
    principal_id: Annotated[str, Field(min_length=1, max_length=512, repr=False)]
    customer_id: Annotated[str, Field(pattern=CUSTOMER_PATTERN)]
    domain_id: Annotated[str, Field(min_length=1, max_length=512)]
    scope_hash: Annotated[str, Field(pattern=SHA256_PATTERN)]
    payload_digest: Annotated[str, Field(pattern=SHA256_PATTERN)]
    advisory: bool = False
    requires_approval: bool = False
    review_item_id: Annotated[str | None, Field(max_length=256)] = None
    due_at: AwareDatetime | None = None
    execution: ExecutionRecord | None = None
    etag: str | None = None

    @property
    def key(self) -> IntentKey:
        return IntentKey(self.customer_id, self.domain_id, self.intent.intent_id.root)

    @property
    def intent_id(self) -> str:
        return self.intent.intent_id.root

    @property
    def state(self) -> str:
        return self.intent.state.root

    def to_document(self) -> dict[str, Any]:
        """Plain JSON for storage (the intent in its schema-valid wire form; no ``etag``)."""
        body = self.model_dump(mode="json", exclude={"intent", "etag"})
        body["intent"] = intent_to_wire(self.intent)
        return body

    @classmethod
    def from_document(cls, document: dict[str, Any], *, etag: str | None) -> StoredIntent:
        return cls.model_validate({**document, "etag": etag})


@dataclass(frozen=True, slots=True)
class CreateOutcome:
    """Result of an idempotent create: the stored intent and whether this call created it."""

    stored: StoredIntent
    created: bool

"""Request bodies and views of the governance policy routes (PRP-105 item 6).

The engine documents (PRP-99 ``PolicyDefinition``, ``PolicyViolation``, ``PolicyException``,
``EnforcementBinding``, core ``EvaluationStatus``) are returned as their JSON form under one key of
a view, never as the contract classes themselves: those share class names (``TargetRef``...) with
other contract areas already in the OpenAPI document, and reusing them as response models would
rename existing components.

Bodies carry only what the caller may choose. Identity, customer, cloud, domain (the path),
versions, status, timestamps and ``content_sha256`` are set by the server; ``extra="forbid"`` at
every level, so an ``expression``, ``query`` or ``template`` field is refused, never ignored.

No ``from __future__ import annotations``: FastAPI inspects these models.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "BindingList",
    "BindingView",
    "ExceptionList",
    "ExceptionRequestBody",
    "ExceptionRequestView",
    "ExceptionView",
    "GovernanceStatusView",
    "PointCapabilityView",
    "PolicyCreateBody",
    "PolicyDraftBody",
    "PolicyList",
    "PolicyStageBody",
    "PolicyView",
    "PublishRefusalView",
    "RuleKindStatusView",
    "RunStatusView",
    "VersionList",
    "ViolationList",
    "ViolationView",
]

_SLUG = r"^[a-z0-9][a-z0-9._-]{0,63}$"
_REASON_CODE = r"^[a-z][a-z0-9_]{0,63}$"
_IDEMPOTENCY = r"^[A-Za-z0-9._:-]{16,128}$"


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PolicyDraftBody(_Body):
    """``PUT .../draft``: the content of the open draft (the policy id comes from the path).

    Each rule is ``{rule_id, kind, severity?, applies_to, params}`` from the PRP-99 closed kind
    list; the server validates every rule against its kind's parameter model (422
    ``invalid_schema`` otherwise) and stamps ``content_sha256``.
    """

    display_name: Annotated[str, Field(min_length=1, max_length=128)]
    document_url: Annotated[str, Field(max_length=512)] | None = None
    mode: Literal["off", "audit", "enforce"] = "audit"
    severity: Literal["low", "medium", "high", "critical"]
    rules: Annotated[list[dict[str, Any]], Field(min_length=1, max_length=32)]


class PolicyCreateBody(PolicyDraftBody):
    """``POST .../policies``: a new policy (version 1) or the next draft of an existing one."""

    policy_id: Annotated[str, Field(pattern=_SLUG)]


class PolicyStageBody(_Body):
    """``POST .../publish`` and ``.../retire``: the exact version the maker confirms.

    Target, target version and diff (with ``test /policy_digest``) are built by the server.
    """

    version: Annotated[int, Field(ge=1)]
    idempotency_key: Annotated[str, Field(pattern=_IDEMPOTENCY)]
    channel: Literal["button", "chat", "rest", "mcp"] = "rest"


class ExceptionRequestBody(_Body):
    """``POST .../exception-requests``: a reason code, bounded text and a time-boxed expiry.

    Only the SHA-256 of ``justification_text`` is kept (in the audit record); the expiry must be
    in the future and at most ``NS_GOVPOLICY_EXCEPTION_MAX_DAYS`` days away.
    """

    justification_code: Annotated[str, Field(pattern=_REASON_CODE)]
    justification_text: Annotated[str, Field(min_length=1, max_length=1000)]
    expires_at: datetime


class PublishRefusalView(BaseModel):
    """One reason the version cannot be published here (the publish dry run)."""

    reason: str
    pointer: str


class PolicyView(BaseModel):
    """One policy version: the PRP-99 ``PolicyDefinition`` JSON, its ETag and digest.

    ``publish_refusals`` is the publish dry run against this deployment's evaluators (empty for
    a publishable draft, and for a version that is not a draft).
    """

    policy: dict[str, Any]
    etag: str
    policy_digest: str
    publish_refusals: list[PublishRefusalView] = Field(default_factory=list[PublishRefusalView])


class PolicyList(BaseModel):
    """The latest version of each policy in the domain, ordered by policy id."""

    items: list[PolicyView]
    next_cursor: str | None = None


class VersionList(BaseModel):
    """Every version of one policy, oldest first."""

    items: list[PolicyView]


class ViolationView(BaseModel):
    """One PRP-99 ``PolicyViolation`` (ids, counts and evidence references; no content)."""

    violation: dict[str, Any]
    etag: str


class ViolationList(BaseModel):
    items: list[ViolationView]
    next_cursor: str | None = None


class ExceptionView(BaseModel):
    """One PRP-99 ``PolicyException``."""

    exception: dict[str, Any]
    etag: str


class ExceptionList(BaseModel):
    items: list[ExceptionView]
    next_cursor: str | None = None


class ExceptionRequestView(BaseModel):
    """The requested exception and the HITL ``policy_exception`` review item it opened."""

    exception: dict[str, Any]
    etag: str
    review_item_id: str


class PointCapabilityView(BaseModel):
    """What an enforcement point can block, and which PRP builds it."""

    point: str
    can_block: bool
    what_it_blocks: str
    owning_prp: str


class BindingView(BaseModel):
    """One PRP-99 ``EnforcementBinding`` with its ``admin_config`` ETag and version."""

    binding: dict[str, Any]
    etag: str
    version: int
    retired: bool
    capability: PointCapabilityView | None = None


class BindingList(BaseModel):
    items: list[BindingView]


class RuleKindStatusView(BaseModel):
    """Whether this deployment can evaluate a rule kind; ``reason`` when it cannot."""

    kind: str
    status: Literal["available", "evaluator_unavailable"]
    reason: str | None = None


class RunStatusView(BaseModel):
    """The latest evaluation run filed under one readable domain (``status`` null: none yet)."""

    domain_id: str
    status: dict[str, Any] | None = None


class GovernanceStatusView(BaseModel):
    """``GET /status``: evaluator availability per rule kind and the latest run per domain.

    ``runs_truncated`` is true when the caller can read more domains than one status read
    covers. ``points`` is the fixed enforcement point capability table (detective evaluation
    blocks nothing).
    """

    rule_kinds: list[RuleKindStatusView]
    runs: list[RunStatusView]
    runs_truncated: bool = False
    points: list[PointCapabilityView]

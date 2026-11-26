"""Policy engine stores: protocols, typed errors and the shared store logic (PRP-105 item 1).

Containers (declared by PRP-102 in :mod:`neurosphere_core.stores.containers`, partition key
``/customer_id`` + ``/domain_id``): ``policy_definitions`` (policy versions and, as
``doc_kind: evaluation_status``, run-status documents; clarification 9), ``policy_violations``
and ``policy_exceptions``. Enforcement bindings are ``admin_config`` documents of
``admin_kind: enforcement_binding`` through the shipped :class:`AdminConfigRepository`.

Rules every implementation shares. They live HERE, in the ``Document*Store`` classes written
once over a small :class:`DocumentBackend` (create-only, read, ETag replace, upsert, a
structured query), so the in-memory (:mod:`.memory_store`) and Cosmos (:mod:`.cosmos_store`)
stores cannot drift:

* every create is create-only and every change is a replace under the stored ETag; an ``if_match``
  that is not the current ETag, or a concurrent writer, is ``stale_version``
  (:class:`GovernancePolicyStaleError`); nothing is retried silently except the documented
  violation upsert race;
* a published (or retired) policy version is immutable: ``replace_draft`` on it is
  :class:`PolicyPublishedError` (``stale_version``, reason ``policy_published``);
* drafts pass :func:`~.validation.validate_draft` first; a failure is ``invalid_schema`` and
  nothing is stored;
* a missing record is ``not_found`` (:class:`GovernancePolicyNotFoundError`) on writes and
  ``None`` on reads; outages are ``dependency_transient`` and a stored document that fails
  validation is ``dependency_transient`` with ``upstream_invalid``;
* queries carry fixed clause text and parameters only, ORDER BY one property (``sort_key``):
  Cosmos refuses a multi-property ORDER BY without a composite index (none is declared).

Violations carry ids, counts and category names only, never content.
"""

from __future__ import annotations

import base64
import binascii
import builtins
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal, Protocol, get_args, runtime_checkable

from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from pydantic import ValidationError

from neurosphere_core.admin.store import AdminConfigRepository
from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    NotFoundError,
    StaleVersionError,
    ValidationIssue,
)
from neurosphere_core.governance.policy.ids import (
    binding_id_for,
    dedup_key,
    evaluation_status_id,
    policy_document_id,
    violation_id_for,
)
from neurosphere_core.governance.policy.models import (
    POINTS_BY_RULE_KIND,
    POLICY_SCHEMA_VERSION,
    EnforcementBinding,
    EnforcementModeName,
    EnforcementPointName,
    EvaluationStatus,
    ExceptionStatusName,
    PolicyDefinition,
    PolicyException,
    PolicyViolation,
    PolicyViolationEvidence,
    RuleKindName,
    TargetRef,
    ViolationStatusName,
)
from neurosphere_core.governance.policy.validation import validate_draft, validate_policy
from neurosphere_core.paging import Page, PageRequest

__all__ = [
    "BINDING_ADMIN_KIND",
    "BINDING_MODIFIED",
    "BINDING_NOT_FOUND",
    "CONDITION_CLEARED",
    "DEFAULT_CONTAINERS",
    "DOC_KIND_EVALUATION_STATUS",
    "DOC_KIND_EXCEPTION",
    "DOC_KIND_POLICY",
    "DOC_KIND_VIOLATION",
    "ENFORCE_REQUIRES_MODE_CHANGE",
    "EVALUATOR_VERSION",
    "EXCEPTION_EXISTS",
    "EXCEPTION_MODIFIED",
    "EXCEPTION_NOT_FOUND",
    "GOVPOLICY_RECORD_INVALID",
    "GOVPOLICY_STORE_UNAVAILABLE",
    "GOVPOLICY_THROTTLED",
    "INVALID_EXCEPTION_TRANSITION",
    "MAX_DOMAIN_FILTER",
    "MAX_VERSIONS",
    "PARTITION_KEY_PATHS",
    "POINT_NOT_APPLICABLE",
    "POLICY_DEFINITIONS_CONTAINER",
    "POLICY_DRAFT_EXISTS",
    "POLICY_EXCEPTIONS_CONTAINER",
    "POLICY_EXISTS",
    "POLICY_MODIFIED",
    "POLICY_NOT_FOUND",
    "POLICY_NOT_PUBLISHED",
    "POLICY_PUBLISHED",
    "POLICY_RETIRED",
    "POLICY_VIOLATIONS_CONTAINER",
    "QUERY_EQ_FIELDS",
    "QUERY_IN_FIELDS",
    "QUERY_NE_FIELDS",
    "VIOLATION_MODIFIED",
    "VIOLATION_NOT_FOUND",
    "VIOLATION_RESOLVED",
    "BindingStore",
    "DocumentBackend",
    "DocumentConflictError",
    "DocumentEvaluationStatusStore",
    "DocumentExceptionStore",
    "DocumentExistsError",
    "DocumentPolicyDefinitionStore",
    "DocumentQuery",
    "DocumentViolationStore",
    "EvaluationStatusStore",
    "ExceptionFilters",
    "ExceptionStore",
    "GovernancePolicyNotFoundError",
    "GovernancePolicyStaleError",
    "ObservedViolation",
    "PolicyDefinitionStore",
    "PolicyPublishedError",
    "ResolveReport",
    "StoredBinding",
    "StoredEvaluationStatus",
    "StoredException",
    "StoredPolicy",
    "StoredViolation",
    "ViolationFilters",
    "ViolationObservation",
    "ViolationStore",
    "decode_cursor",
    "encode_cursor",
    "record_invalid",
    "store_unavailable",
]

POLICY_DEFINITIONS_CONTAINER: Final = "policy_definitions"
POLICY_VIOLATIONS_CONTAINER: Final = "policy_violations"
POLICY_EXCEPTIONS_CONTAINER: Final = "policy_exceptions"
DEFAULT_CONTAINERS: Final = (
    POLICY_DEFINITIONS_CONTAINER,
    POLICY_VIOLATIONS_CONTAINER,
    POLICY_EXCEPTIONS_CONTAINER,
)
PARTITION_KEY_PATHS: Final = ("/customer_id", "/domain_id")
BINDING_ADMIN_KIND: Final = "enforcement_binding"

DOC_KIND_POLICY: Final = "policy_definition"
DOC_KIND_EVALUATION_STATUS: Final = "evaluation_status"
DOC_KIND_VIOLATION: Final = "policy_violation"
DOC_KIND_EXCEPTION: Final = "policy_exception"

#: Version stamped on violations this engine writes (``PolicyViolation.evaluator_version``).
EVALUATOR_VERSION: Final = "1.0.0"
#: Resolution reason when a complete run no longer sees the condition.
CONDITION_CLEARED: Final = "condition_cleared"
MAX_VERSIONS: Final = 1000
MAX_DOMAIN_FILTER: Final = 500
_MAX_GENERATIONS: Final = 1000
_MAX_RESOLVE: Final = 1000
#: ``resolve_missing`` reads at most this many batches of ``_MAX_RESOLVE`` rows per call.
_MAX_RESOLVE_BATCHES: Final = 50
_UPSERT_ATTEMPTS: Final = 3

# --- reason codes -------------------------------------------------------------------------------
POLICY_NOT_FOUND: Final = "policy_not_found"
POLICY_EXISTS: Final = "policy_exists"
POLICY_DRAFT_EXISTS: Final = "policy_draft_exists"
POLICY_MODIFIED: Final = "policy_modified"
POLICY_PUBLISHED: Final = "policy_published"
POLICY_RETIRED: Final = "policy_retired"
POLICY_NOT_PUBLISHED: Final = "policy_not_published"
VIOLATION_NOT_FOUND: Final = "violation_not_found"
VIOLATION_MODIFIED: Final = "violation_modified"
VIOLATION_RESOLVED: Final = "violation_resolved"
EXCEPTION_NOT_FOUND: Final = "exception_not_found"
EXCEPTION_EXISTS: Final = "exception_exists"
EXCEPTION_MODIFIED: Final = "exception_modified"
INVALID_EXCEPTION_TRANSITION: Final = "invalid_exception_transition"
BINDING_NOT_FOUND: Final = "binding_not_found"
BINDING_MODIFIED: Final = "binding_modified"
ENFORCE_REQUIRES_MODE_CHANGE: Final = "enforce_requires_mode_change"
POINT_NOT_APPLICABLE: Final = "point_not_applicable"
GOVPOLICY_STORE_UNAVAILABLE: Final = "govpolicy_store_unavailable"
GOVPOLICY_RECORD_INVALID: Final = "govpolicy_record_invalid"
GOVPOLICY_THROTTLED: Final = "govpolicy_throttled"

#: Fields a structured query may test for equality (each has one fixed clause in the backends).
QUERY_EQ_FIELDS: Final = frozenset(
    {
        "doc_kind",
        "policy_id",
        "policy_version",
        "status",
        "superseded",
        "rule_id",
        "dedup_key",
        "subject_id",
        "severity",
        "violation_id",
    }
)
#: Fields a structured query may test for membership in a list of values.
QUERY_IN_FIELDS: Final = frozenset({"domain_id", "status"})
#: Fields a structured query may test for inequality. A document whose field is missing or
#: null never matches (Cosmos compares across types as undefined, which filters the row out).
QUERY_NE_FIELDS: Final = frozenset({"last_run_id"})

_EXCEPTION_TRANSITIONS: Final[Mapping[str, frozenset[str]]] = {
    "requested": frozenset({"approved", "rejected", "expired", "revoked"}),
    "approved": frozenset({"expired", "revoked"}),
}
_ACTIVE_VIOLATION: Final = ("open", "excepted")
_POINTS: Final = frozenset(get_args(EnforcementPointName))
_BINDING_STATES: Final = frozenset({"pending", "applied", "failed", "drifted", "not_supported"})
_MODES: Final = frozenset({"off", "audit", "enforce"})


# --- typed errors -------------------------------------------------------------------------------


class GovernancePolicyNotFoundError(NotFoundError):
    """The named policy, violation, exception or binding does not exist (404)."""

    def __init__(self, reason: str, detail: str = "no such governance policy record") -> None:
        super().__init__(detail, reason=reason)


class GovernancePolicyStaleError(StaleVersionError):
    """``stale_version`` (409): the ETag moved, a record exists, or a transition is refused."""

    def __init__(self, reason: str, detail: str = "record changed since it was read") -> None:
        super().__init__(detail, reason=reason)


class PolicyPublishedError(GovernancePolicyStaleError):
    """A published or retired policy version is immutable (``stale_version``,
    ``policy_published``)."""

    def __init__(self) -> None:
        super().__init__(POLICY_PUBLISHED, "a published policy version cannot be changed")


def store_unavailable() -> DependencyTransientError:
    return DependencyTransientError(
        "governance policy store is unavailable", reason=GOVPOLICY_STORE_UNAVAILABLE
    )


def record_invalid() -> DependencyTransientError:
    return DependencyTransientError(
        "stored governance policy record failed validation",
        reason=GOVPOLICY_RECORD_INVALID,
        upstream_invalid=True,
    )


def _invalid(reason: str, pointer: str, detail: str) -> InvalidSchemaError:
    return InvalidSchemaError(detail, errors=[ValidationIssue(pointer, detail)], reason=reason)


# --- time and cursors ---------------------------------------------------------------------------


def _timestamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise _invalid("invalid_timestamp", "/now", "timestamps must be timezone-aware")
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def encode_cursor(sort_key: str) -> str:
    """Opaque page cursor for a ``sort_key`` position."""
    return base64.urlsafe_b64encode(sort_key.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> str:
    """The ``sort_key`` a cursor names; ``invalid_schema`` ``invalid_cursor`` when malformed."""
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeError, ValueError):
        raise _invalid("invalid_cursor", "/cursor", "invalid cursor") from None
    if not decoded or len(decoded) > 512 or "|" not in decoded:
        raise _invalid("invalid_cursor", "/cursor", "invalid cursor")
    return decoded


# --- the document backend -----------------------------------------------------------------------


class DocumentExistsError(Exception):
    """Backend signal: a create-only write hit an existing id."""


class DocumentConflictError(Exception):
    """Backend signal: an ETag replace found a different ETag or no document."""


@dataclass(frozen=True, slots=True)
class DocumentQuery:
    """A structured query: no SQL text leaves the backend that owns it.

    ``domain_id`` set = one partition; otherwise cross-partition inside ``customer_id``.
    Rows come back ordered by ``sort_key`` (ascending, or descending when ``descending``).
    """

    customer_id: str
    limit: int
    domain_id: str | None = None
    equals: tuple[tuple[str, Any], ...] = ()
    any_of: tuple[tuple[str, tuple[Any, ...]], ...] = ()
    not_equals: tuple[tuple[str, Any], ...] = ()
    after: str | None = None
    descending: bool = False

    def __post_init__(self) -> None:
        for name, _ in self.equals:
            if name not in QUERY_EQ_FIELDS:
                raise ValueError(f"field {name!r} is not queryable")
        for name, values in self.any_of:
            if name not in QUERY_IN_FIELDS or not values:
                raise ValueError(f"field {name!r} is not queryable by membership")
        for name, _ in self.not_equals:
            if name not in QUERY_NE_FIELDS:
                raise ValueError(f"field {name!r} is not queryable by inequality")
        names = (
            [n for n, _ in self.equals]
            + [n for n, _ in self.any_of]
            + [n for n, _ in self.not_equals]
        )
        if len(names) != len(set(names)):
            raise ValueError("a field may be tested once per query")
        if not 1 <= self.limit <= MAX_VERSIONS + 1:
            raise ValueError("limit out of range")


class DocumentBackend(Protocol):
    """Storage primitives over ONE container (partition ``/customer_id`` + ``/domain_id``).

    Returned rows include the store ETag as ``_etag``.
    """

    async def create(self, document: Mapping[str, Any]) -> dict[str, Any]:
        """Create-only; an existing id raises :class:`DocumentExistsError`."""
        ...

    async def read(self, customer_id: str, domain_id: str, doc_id: str) -> dict[str, Any] | None:
        """Point read in one partition."""
        ...

    async def replace(self, document: Mapping[str, Any], *, if_match: str) -> dict[str, Any]:
        """Replace under ``if_match``; a mismatch or missing id raises
        :class:`DocumentConflictError`."""
        ...

    async def upsert(self, document: Mapping[str, Any]) -> dict[str, Any]: ...

    async def query(self, query: DocumentQuery) -> builtins.list[dict[str, Any]]: ...


def _strip(row: Mapping[str, Any], *extra: str) -> dict[str, Any]:
    drop = {"id", "doc_kind", "sort_key", *extra}
    return {k: v for k, v in row.items() if not k.startswith("_") and k not in drop}


def _etag(row: Mapping[str, Any]) -> str:
    value = row.get("_etag")
    if not isinstance(value, str) or not value:
        raise record_invalid()
    return value


# --- stored records -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoredPolicy:
    """A stored policy version and the ETag that guards its next write."""

    policy: PolicyDefinition
    etag: str


@dataclass(frozen=True, slots=True)
class StoredViolation:
    violation: PolicyViolation
    etag: str
    #: The evaluation run that last observed it (store metadata, not part of the contract).
    last_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class StoredException:
    exception: PolicyException
    etag: str


@dataclass(frozen=True, slots=True)
class StoredEvaluationStatus:
    status: EvaluationStatus
    etag: str


@dataclass(frozen=True, slots=True)
class StoredBinding:
    """An enforcement binding, its ``admin_config`` ETag, version and status."""

    binding: EnforcementBinding
    etag: str
    version: int
    retired: bool = False


@dataclass(frozen=True, slots=True)
class ViolationObservation:
    """One observed breach from an evaluator: ids, category names and evidence refs only."""

    cloud: Literal["commercial", "government"]
    customer_id: str
    domain_id: str
    policy_id: str
    policy_version: int
    rule_id: str
    rule_kind: RuleKindName
    severity: Literal["low", "medium", "high", "critical"]
    subject: TargetRef
    evidence_class: str
    evidence: tuple[PolicyViolationEvidence, ...]
    run_id: str
    correlation_id: str
    evaluator_version: str = EVALUATOR_VERSION


@dataclass(frozen=True, slots=True)
class ObservedViolation:
    """Result of :meth:`ViolationStore.upsert_observed`: ``created`` is False on a repeat."""

    stored: StoredViolation
    created: bool


@dataclass(frozen=True, slots=True)
class ResolveReport:
    """Result of :meth:`ViolationStore.resolve_missing_report`.

    ``truncated`` is True when the batch cap stopped the pass before every stale violation was
    read: the rest stay active and the caller reports the rule ``truncated``.
    """

    resolved: tuple[StoredViolation, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class ViolationFilters:
    """``domain_ids`` is required (the caller's in-scope domains); the rest narrow it."""

    domain_ids: tuple[str, ...]
    status: ViolationStatusName | None = None
    policy_id: str | None = None
    rule_id: str | None = None
    subject_id: str | None = None
    severity: Literal["low", "medium", "high", "critical"] | None = None


@dataclass(frozen=True, slots=True)
class ExceptionFilters:
    domain_ids: tuple[str, ...]
    status: ExceptionStatusName | None = None
    policy_id: str | None = None
    rule_id: str | None = None
    subject_id: str | None = None
    violation_id: str | None = None


# --- protocols ----------------------------------------------------------------------------------


@runtime_checkable
class PolicyDefinitionStore(Protocol):
    """Versioned policy documents. ``customer_id`` comes from the server-derived scope."""

    async def create_draft(self, policy: PolicyDefinition | Mapping[str, Any]) -> StoredPolicy:
        """Validate and create a new draft version (1, or latest + 1 after a non-draft)."""
        ...

    async def replace_draft(
        self, policy: PolicyDefinition | Mapping[str, Any], *, if_match: str
    ) -> StoredPolicy:
        """Replace a draft version under its ETag; a published version is immutable."""
        ...

    async def get(
        self, customer_id: str, policy_id: str, *, version: int | None = None
    ) -> StoredPolicy | None:
        """One version, or the latest when ``version`` is None."""
        ...

    async def list(
        self, customer_id: str, domain_ids: Sequence[str], page: PageRequest
    ) -> Page[StoredPolicy]:
        """The latest version of each policy in ``domain_ids``, ordered by policy id."""
        ...

    async def list_published(
        self,
        customer_id: str,
        domain_ids: Sequence[str] | None = None,
        *,
        limit: int = MAX_VERSIONS,
    ) -> builtins.list[StoredPolicy]:
        """Published versions (highest per policy), ordered by policy id."""
        ...

    async def versions(
        self, customer_id: str, policy_id: str, *, limit: int = 100
    ) -> builtins.list[StoredPolicy]:
        """Every version of one policy, oldest first."""
        ...

    async def mark_published(
        self,
        customer_id: str,
        policy_id: str,
        version: int,
        *,
        if_match: str,
        published_at: datetime,
        intent_id: str,
        audit_id: str,
    ) -> StoredPolicy:
        """draft -> published with the approved intent and audit ids (PolicyLifecycle only)."""
        ...

    async def mark_retired(
        self, customer_id: str, policy_id: str, version: int, *, if_match: str
    ) -> StoredPolicy:
        """published -> retired (PolicyLifecycle only)."""
        ...


@runtime_checkable
class EvaluationStatusStore(Protocol):
    """Run-status documents (``doc_kind: evaluation_status`` in ``policy_definitions``)."""

    async def record(self, status: EvaluationStatus) -> StoredEvaluationStatus: ...

    async def get(
        self, customer_id: str, domain_id: str, run_id: str
    ) -> StoredEvaluationStatus | None: ...

    async def latest(self, customer_id: str, domain_id: str) -> StoredEvaluationStatus | None: ...

    async def recent(
        self, customer_id: str, domain_id: str, *, limit: int = 20
    ) -> builtins.list[StoredEvaluationStatus]: ...


@runtime_checkable
class ViolationStore(Protocol):
    async def upsert_observed(
        self, dedup_key: str, observation: ViolationObservation, *, now: datetime
    ) -> ObservedViolation:
        """Create the open violation for ``dedup_key``, or bump ``last_seen_at`` and
        ``occurrence_count`` of the open (or excepted) one. Never two active records."""
        ...

    async def resolve_missing(
        self,
        customer_id: str,
        domain_ids: Sequence[str],
        *,
        run_id: str,
        policy_id: str,
        rule_id: str,
        now: datetime,
    ) -> builtins.list[StoredViolation]:
        """Resolve active violations of the rule that run ``run_id`` did not observe. Call only
        after a COMPLETE (not truncated, not failed) run of that rule over ``domain_ids``."""
        ...

    async def resolve_missing_report(
        self,
        customer_id: str,
        domain_ids: Sequence[str],
        *,
        run_id: str,
        policy_id: str,
        rule_id: str,
        now: datetime,
    ) -> ResolveReport:
        """:meth:`resolve_missing` plus whether the batch cap left stale violations unread."""
        ...

    async def set_exception(
        self,
        customer_id: str,
        domain_id: str,
        violation_id: str,
        exception_id: str | None,
        *,
        if_match: str,
    ) -> StoredViolation:
        """Mark ``excepted`` under ``exception_id``, or back to ``open`` with ``None``."""
        ...

    async def get(
        self, customer_id: str, domain_id: str, violation_id: str
    ) -> StoredViolation | None: ...

    async def list(
        self, customer_id: str, filters: ViolationFilters, page: PageRequest
    ) -> Page[StoredViolation]:
        """Newest first (``first_seen_at``)."""
        ...


@runtime_checkable
class ExceptionStore(Protocol):
    async def request(self, exception: PolicyException) -> StoredException:
        """Create-only, status ``requested``."""
        ...

    async def set_state(
        self,
        customer_id: str,
        domain_id: str,
        exception_id: str,
        status: ExceptionStatusName,
        *,
        if_match: str,
        decided_by: str | None = None,
        decided_at: datetime | None = None,
        audit_id: str | None = None,
    ) -> StoredException: ...

    async def get(
        self, customer_id: str, domain_id: str, exception_id: str
    ) -> StoredException | None: ...

    async def active_for(
        self,
        customer_id: str,
        domain_id: str,
        *,
        subject_id: str,
        policy_id: str,
        rule_id: str,
        now: datetime,
    ) -> StoredException | None:
        """The approved, unexpired exception for (subject, rule), latest expiry first."""
        ...

    async def list(
        self, customer_id: str, filters: ExceptionFilters, page: PageRequest
    ) -> Page[StoredException]:
        """Newest first (``requested_at``)."""
        ...


# --- shared helpers -----------------------------------------------------------------------------


def _check_domains(domain_ids: Sequence[str]) -> tuple[str, ...]:
    domains = tuple(dict.fromkeys(domain_ids))
    if len(domains) > MAX_DOMAIN_FILTER:
        raise _invalid("invalid_query", "/domain_ids", f"at most {MAX_DOMAIN_FILTER} domains")
    return domains


def _check_limit(limit: int, ceiling: int = MAX_VERSIONS) -> int:
    if not 1 <= limit <= ceiling:
        raise _invalid("invalid_query", "/limit", f"limit must be 1..{ceiling}")
    return limit


def _page[T](rows: builtins.list[T], keys: builtins.list[str], size: int) -> Page[T]:
    head = rows[:size]
    cursor = encode_cursor(keys[size - 1]) if len(rows) > size else None
    return Page[T](items=tuple(head), next_cursor=cursor)


# --- policy definitions -------------------------------------------------------------------------


class DocumentPolicyDefinitionStore:
    """:class:`PolicyDefinitionStore` written once over a :class:`DocumentBackend`."""

    def __init__(self, backend: DocumentBackend) -> None:
        self._backend = backend

    @staticmethod
    def _sort_key(policy: PolicyDefinition) -> str:
        return f"{policy.policy_id.root}|{policy.policy_version:010d}"

    def _document(self, policy: PolicyDefinition, *, superseded: bool) -> dict[str, Any]:
        body = policy.model_dump(mode="json")
        body["id"] = policy_document_id(policy.policy_id.root, policy.policy_version)
        body["doc_kind"] = DOC_KIND_POLICY
        body["sort_key"] = self._sort_key(policy)
        body["superseded"] = superseded
        return body

    @staticmethod
    def _load(row: Mapping[str, Any]) -> StoredPolicy:
        try:
            policy = validate_policy(_strip(row, "superseded"))
        except InvalidSchemaError:
            raise record_invalid() from None
        return StoredPolicy(policy=policy, etag=_etag(row))

    async def _query(self, query: DocumentQuery) -> builtins.list[dict[str, Any]]:
        return await self._backend.query(query)

    async def _latest_row(self, customer_id: str, policy_id: str) -> dict[str, Any] | None:
        rows = await self._query(
            DocumentQuery(
                customer_id=customer_id,
                limit=1,
                equals=(("doc_kind", DOC_KIND_POLICY), ("policy_id", policy_id)),
                descending=True,
            )
        )
        return rows[0] if rows else None

    async def _version_row(
        self, customer_id: str, policy_id: str, version: int
    ) -> dict[str, Any] | None:
        rows = await self._query(
            DocumentQuery(
                customer_id=customer_id,
                limit=2,
                equals=(
                    ("doc_kind", DOC_KIND_POLICY),
                    ("policy_id", policy_id),
                    ("policy_version", version),
                ),
            )
        )
        return rows[0] if rows else None

    async def create_draft(self, policy: PolicyDefinition | Mapping[str, Any]) -> StoredPolicy:
        draft = validate_draft(policy)
        customer, policy_id = draft.customer_id.root, draft.policy_id.root
        latest_row = await self._latest_row(customer, policy_id)
        if latest_row is None:
            if draft.policy_version != 1 or draft.previous_version is not None:
                raise GovernancePolicyStaleError(POLICY_MODIFIED, "a new policy starts at 1")
        else:
            latest = self._load(latest_row).policy
            if latest.domain_id.root != draft.domain_id.root:
                raise GovernancePolicyStaleError(POLICY_EXISTS, "policy id is already used")
            if latest.status == "draft":
                raise GovernancePolicyStaleError(
                    POLICY_DRAFT_EXISTS, "the policy already has an open draft"
                )
            if (
                draft.policy_version != latest.policy_version + 1
                or draft.previous_version != latest.policy_version
            ):
                raise GovernancePolicyStaleError(POLICY_MODIFIED, "version is not latest + 1")
        try:
            row = await self._backend.create(self._document(draft, superseded=False))
        except DocumentExistsError:
            raise GovernancePolicyStaleError(POLICY_MODIFIED) from None
        if latest_row is not None:
            previous = self._load(latest_row).policy
            try:
                await self._backend.replace(
                    self._document(previous, superseded=True), if_match=_etag(latest_row)
                )
            except DocumentConflictError:
                pass  # list() also keeps only the highest version per policy
        return self._load(row)

    async def _current(
        self, customer_id: str, domain_id: str, policy_id: str, version: int
    ) -> dict[str, Any]:
        row = await self._backend.read(
            customer_id, domain_id, policy_document_id(policy_id, version)
        )
        if row is None or row.get("doc_kind") != DOC_KIND_POLICY:
            raise GovernancePolicyNotFoundError(POLICY_NOT_FOUND)
        return row

    async def replace_draft(
        self, policy: PolicyDefinition | Mapping[str, Any], *, if_match: str
    ) -> StoredPolicy:
        draft = validate_draft(policy)
        row = await self._current(
            draft.customer_id.root,
            draft.domain_id.root,
            draft.policy_id.root,
            draft.policy_version,
        )
        current = self._load(row)
        if current.policy.status != "draft":
            raise PolicyPublishedError()
        if current.etag != if_match:
            raise GovernancePolicyStaleError(POLICY_MODIFIED)
        if draft.previous_version != current.policy.previous_version:
            raise GovernancePolicyStaleError(POLICY_MODIFIED, "previous_version cannot change")
        kept = draft.model_copy(
            update={
                "created_by": current.policy.created_by,
                "created_at": current.policy.created_at,
            }
        )
        try:
            stored = await self._backend.replace(
                self._document(kept, superseded=bool(row.get("superseded"))), if_match=if_match
            )
        except DocumentConflictError:
            raise GovernancePolicyStaleError(POLICY_MODIFIED) from None
        return self._load(stored)

    async def get(
        self, customer_id: str, policy_id: str, *, version: int | None = None
    ) -> StoredPolicy | None:
        if version is None:
            row = await self._latest_row(customer_id, policy_id)
        else:
            row = await self._version_row(customer_id, policy_id, version)
        return None if row is None else self._load(row)

    async def list(
        self, customer_id: str, domain_ids: Sequence[str], page: PageRequest
    ) -> Page[StoredPolicy]:
        domains = _check_domains(domain_ids)
        if not domains:
            return Page[StoredPolicy](items=(), next_cursor=None)
        rows = await self._query(
            DocumentQuery(
                customer_id=customer_id,
                limit=page.page_size + 1,
                equals=(("doc_kind", DOC_KIND_POLICY), ("superseded", False)),
                any_of=(("domain_id", domains),),
                after=decode_cursor(page.cursor) if page.cursor else None,
            )
        )
        # De-duplicate versions over every fetched row (the look-ahead row included, so a newer
        # version just past the page drops the stale one here and is listed on the next page),
        # but page on the RAW rows: a stale ``superseded=False`` version dropped by the de-dup
        # must not end the listing early (review A, PRP-105 item 3).
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            seen = latest.get(row["policy_id"])
            if seen is None or row["policy_version"] > seen["policy_version"]:
                latest[row["policy_id"]] = row
        head = rows[: page.page_size]
        kept = [r for r in head if latest[r["policy_id"]] is r]
        cursor = (
            encode_cursor(head[-1]["sort_key"]) if len(rows) > page.page_size and head else None
        )
        return Page[StoredPolicy](items=tuple(self._load(r) for r in kept), next_cursor=cursor)

    async def list_published(
        self,
        customer_id: str,
        domain_ids: Sequence[str] | None = None,
        *,
        limit: int = MAX_VERSIONS,
    ) -> builtins.list[StoredPolicy]:
        _check_limit(limit)
        any_of: tuple[tuple[str, tuple[Any, ...]], ...] = ()
        if domain_ids is not None:
            domains = _check_domains(domain_ids)
            if not domains:
                return []
            any_of = (("domain_id", domains),)
        rows = await self._query(
            DocumentQuery(
                customer_id=customer_id,
                limit=limit,
                equals=(("doc_kind", DOC_KIND_POLICY), ("status", "published")),
                any_of=any_of,
            )
        )
        best: dict[str, StoredPolicy] = {}
        for row in rows:
            stored = self._load(row)
            key = stored.policy.policy_id.root
            if key not in best or stored.policy.policy_version > best[key].policy.policy_version:
                best[key] = stored
        return [best[k] for k in sorted(best)]

    async def versions(
        self, customer_id: str, policy_id: str, *, limit: int = 100
    ) -> builtins.list[StoredPolicy]:
        _check_limit(limit)
        rows = await self._query(
            DocumentQuery(
                customer_id=customer_id,
                limit=limit,
                equals=(("doc_kind", DOC_KIND_POLICY), ("policy_id", policy_id)),
            )
        )
        return [self._load(r) for r in rows]

    async def _transition(
        self, row: Mapping[str, Any], update: Mapping[str, Any], if_match: str
    ) -> StoredPolicy:
        current = self._load(row).policy
        checked = validate_policy({**current.model_dump(mode="json"), **update})
        try:
            stored = await self._backend.replace(
                self._document(checked, superseded=bool(row.get("superseded"))),
                if_match=if_match,
            )
        except DocumentConflictError:
            raise GovernancePolicyStaleError(POLICY_MODIFIED) from None
        return self._load(stored)

    async def mark_published(
        self,
        customer_id: str,
        policy_id: str,
        version: int,
        *,
        if_match: str,
        published_at: datetime,
        intent_id: str,
        audit_id: str,
    ) -> StoredPolicy:
        row = await self._version_row(customer_id, policy_id, version)
        if row is None:
            raise GovernancePolicyNotFoundError(POLICY_NOT_FOUND)
        current = self._load(row)
        if current.policy.status == "published":
            raise PolicyPublishedError()
        if current.policy.status == "retired":
            raise GovernancePolicyStaleError(POLICY_RETIRED, "a retired version stays retired")
        if current.etag != if_match:
            raise GovernancePolicyStaleError(POLICY_MODIFIED)
        update = {
            "status": "published",
            "published_at": _timestamp(published_at),
            "published_intent_id": intent_id,
            "published_audit_id": audit_id,
        }
        return await self._transition(row, update, if_match)

    async def mark_retired(
        self, customer_id: str, policy_id: str, version: int, *, if_match: str
    ) -> StoredPolicy:
        row = await self._version_row(customer_id, policy_id, version)
        if row is None:
            raise GovernancePolicyNotFoundError(POLICY_NOT_FOUND)
        current = self._load(row)
        if current.policy.status == "retired":
            raise GovernancePolicyStaleError(POLICY_RETIRED, "already retired")
        if current.policy.status != "published":
            raise GovernancePolicyStaleError(POLICY_NOT_PUBLISHED, "only a published version")
        if current.etag != if_match:
            raise GovernancePolicyStaleError(POLICY_MODIFIED)
        return await self._transition(row, {"status": "retired"}, if_match)


# --- evaluation status --------------------------------------------------------------------------


class DocumentEvaluationStatusStore:
    """:class:`EvaluationStatusStore` over the ``policy_definitions`` backend."""

    def __init__(self, backend: DocumentBackend) -> None:
        self._backend = backend

    @staticmethod
    def _load(row: Mapping[str, Any]) -> StoredEvaluationStatus:
        try:
            status = EvaluationStatus.model_validate(_strip(row))
        except ValidationError:
            raise record_invalid() from None
        return StoredEvaluationStatus(status=status, etag=_etag(row))

    async def record(self, status: EvaluationStatus) -> StoredEvaluationStatus:
        body = status.model_dump(mode="json")
        body["id"] = evaluation_status_id(status.run_id)
        body["doc_kind"] = DOC_KIND_EVALUATION_STATUS
        body["sort_key"] = f"{status.started_at}|{status.run_id}"
        return self._load(await self._backend.upsert(body))

    async def get(
        self, customer_id: str, domain_id: str, run_id: str
    ) -> StoredEvaluationStatus | None:
        row = await self._backend.read(customer_id, domain_id, evaluation_status_id(run_id))
        if row is None or row.get("doc_kind") != DOC_KIND_EVALUATION_STATUS:
            return None
        return self._load(row)

    async def latest(self, customer_id: str, domain_id: str) -> StoredEvaluationStatus | None:
        found = await self.recent(customer_id, domain_id, limit=1)
        return found[0] if found else None

    async def recent(
        self, customer_id: str, domain_id: str, *, limit: int = 20
    ) -> builtins.list[StoredEvaluationStatus]:
        _check_limit(limit, 500)
        rows = await self._backend.query(
            DocumentQuery(
                customer_id=customer_id,
                domain_id=domain_id,
                limit=limit,
                equals=(("doc_kind", DOC_KIND_EVALUATION_STATUS),),
                descending=True,
            )
        )
        return [self._load(r) for r in rows]


# --- violations ---------------------------------------------------------------------------------


class DocumentViolationStore:
    """:class:`ViolationStore` written once over a :class:`DocumentBackend`.

    ``resolve_batch`` rows are read per ``resolve_missing`` query and at most
    ``resolve_max_batches`` queries run per call; past that the report says ``truncated``.
    """

    def __init__(
        self,
        backend: DocumentBackend,
        *,
        resolve_batch: int = _MAX_RESOLVE,
        resolve_max_batches: int = _MAX_RESOLVE_BATCHES,
    ) -> None:
        if not 1 <= resolve_batch <= MAX_VERSIONS:
            raise ValueError("resolve_batch out of range")
        if resolve_max_batches < 1:
            raise ValueError("resolve_max_batches must be at least 1")
        self._backend = backend
        self._resolve_batch = resolve_batch
        self._resolve_max_batches = resolve_max_batches

    @staticmethod
    def _document(violation: PolicyViolation, last_run_id: str | None) -> dict[str, Any]:
        body = violation.model_dump(mode="json")
        body["id"] = violation.violation_id.root
        body["doc_kind"] = DOC_KIND_VIOLATION
        body["sort_key"] = f"{violation.first_seen_at.root}|{violation.violation_id.root}"
        body["subject_id"] = violation.subject.canonical_id
        body["last_run_id"] = last_run_id
        return body

    @staticmethod
    def _load(row: Mapping[str, Any]) -> StoredViolation:
        try:
            violation = PolicyViolation.model_validate(_strip(row, "subject_id", "last_run_id"))
        except ValidationError:
            raise record_invalid() from None
        run = row.get("last_run_id")
        return StoredViolation(
            violation=violation, etag=_etag(row), last_run_id=run if isinstance(run, str) else None
        )

    async def upsert_observed(
        self, dedup_key: str, observation: ViolationObservation, *, now: datetime
    ) -> ObservedViolation:
        expected = _observation_key(observation)
        if dedup_key != expected:
            raise _invalid("dedup_key_mismatch", "/dedup_key", "dedup key does not match")
        if not 1 <= len(observation.evidence) <= 50:
            raise _invalid("invalid_evidence", "/evidence", "1 to 50 evidence references")
        seen_at = _timestamp(now)
        for _ in range(_UPSERT_ATTEMPTS):
            rows = await self._backend.query(
                DocumentQuery(
                    customer_id=observation.customer_id,
                    domain_id=observation.domain_id,
                    limit=_MAX_GENERATIONS,
                    equals=(("doc_kind", DOC_KIND_VIOLATION), ("dedup_key", dedup_key)),
                )
            )
            active = [r for r in rows if r.get("status") in _ACTIVE_VIOLATION]
            try:
                if active:
                    return ObservedViolation(
                        stored=await self._bump(active[0], observation, seen_at), created=False
                    )
                return ObservedViolation(
                    stored=await self._create(dedup_key, observation, seen_at, len(rows) + 1),
                    created=True,
                )
            except (DocumentExistsError, DocumentConflictError):
                continue  # a concurrent writer won; re-read and apply on top of its write
        raise GovernancePolicyStaleError(VIOLATION_MODIFIED, "violation kept changing")

    async def _create(
        self, key: str, observation: ViolationObservation, seen_at: str, generation: int
    ) -> StoredViolation:
        violation = PolicyViolation.model_validate(
            {
                "schema_version": POLICY_SCHEMA_VERSION,
                "violation_id": violation_id_for(key, generation),
                "cloud": observation.cloud,
                "customer_id": observation.customer_id,
                "domain_id": observation.domain_id,
                "policy_id": observation.policy_id,
                "policy_version": observation.policy_version,
                "rule_id": observation.rule_id,
                "rule_kind": observation.rule_kind,
                "severity": observation.severity,
                "subject": observation.subject.model_dump(mode="json"),
                "status": "open",
                "dedup_key": key,
                "first_seen_at": seen_at,
                "last_seen_at": seen_at,
                "occurrence_count": 1,
                "evidence": [e.model_dump(mode="json") for e in observation.evidence],
                "exception_id": None,
                "resolution": None,
                "correlation_id": observation.correlation_id,
                "evaluator_version": observation.evaluator_version,
            }
        )
        row = await self._backend.create(self._document(violation, observation.run_id))
        return self._load(row)

    async def _bump(
        self, row: Mapping[str, Any], observation: ViolationObservation, seen_at: str
    ) -> StoredViolation:
        current = self._load(row).violation
        updated = PolicyViolation.model_validate(
            {
                **current.model_dump(mode="json"),
                "policy_version": observation.policy_version,
                "severity": observation.severity,
                "last_seen_at": max(seen_at, current.last_seen_at.root),
                "occurrence_count": current.occurrence_count + 1,
                "evidence": [e.model_dump(mode="json") for e in observation.evidence],
                "correlation_id": observation.correlation_id,
                "evaluator_version": observation.evaluator_version,
            }
        )
        stored = await self._backend.replace(
            self._document(updated, observation.run_id), if_match=_etag(row)
        )
        return self._load(stored)

    async def resolve_missing(
        self,
        customer_id: str,
        domain_ids: Sequence[str],
        *,
        run_id: str,
        policy_id: str,
        rule_id: str,
        now: datetime,
    ) -> builtins.list[StoredViolation]:
        domains = _check_domains(domain_ids)
        if not domains:
            return []
        report = await self.resolve_missing_report(
            customer_id,
            domains,
            run_id=run_id,
            policy_id=policy_id,
            rule_id=rule_id,
            now=now,
        )
        return builtins.list(report.resolved)

    async def resolve_missing_report(
        self,
        customer_id: str,
        domain_ids: Sequence[str],
        *,
        run_id: str,
        policy_id: str,
        rule_id: str,
        now: datetime,
    ) -> ResolveReport:
        domains = _check_domains(domain_ids)
        if not domains:
            return ResolveReport(resolved=(), truncated=False)
        resolved_at = _timestamp(now)
        resolved: builtins.list[StoredViolation] = []
        after: str | None = None
        for batch in range(self._resolve_max_batches):
            # Rows this run already observed are excluded by the query itself, so they never
            # count against the batch; ``after`` pages past rows left active by a lost race.
            rows = await self._backend.query(
                DocumentQuery(
                    customer_id=customer_id,
                    limit=self._resolve_batch,
                    equals=(
                        ("doc_kind", DOC_KIND_VIOLATION),
                        ("policy_id", policy_id),
                        ("rule_id", rule_id),
                    ),
                    any_of=(("domain_id", domains), ("status", _ACTIVE_VIOLATION)),
                    not_equals=(("last_run_id", run_id),),
                    after=after,
                )
            )
            resolved.extend(await self._resolve_rows(rows, run_id, resolved_at))
            if len(rows) < self._resolve_batch:
                return ResolveReport(resolved=tuple(resolved), truncated=False)
            if batch + 1 < self._resolve_max_batches:
                after = str(rows[-1]["sort_key"])
        return ResolveReport(resolved=tuple(resolved), truncated=True)

    async def _resolve_rows(
        self, rows: Sequence[Mapping[str, Any]], run_id: str, resolved_at: str
    ) -> builtins.list[StoredViolation]:
        resolved: builtins.list[StoredViolation] = []
        for row in rows:
            if row.get("last_run_id") == run_id:
                continue
            current = self._load(row)
            updated = PolicyViolation.model_validate(
                {
                    **current.violation.model_dump(mode="json"),
                    "status": "resolved",
                    "resolution": {
                        "resolved_at": resolved_at,
                        "reason_code": CONDITION_CLEARED,
                        "intent_id": None,
                        "audit_id": None,
                    },
                }
            )
            try:
                stored = await self._backend.replace(
                    self._document(updated, current.last_run_id), if_match=current.etag
                )
            except DocumentConflictError:
                continue  # changed under us (re-observed or excepted): leave it for next run
            resolved.append(self._load(stored))
        return resolved

    async def set_exception(
        self,
        customer_id: str,
        domain_id: str,
        violation_id: str,
        exception_id: str | None,
        *,
        if_match: str,
    ) -> StoredViolation:
        row = await self._backend.read(customer_id, domain_id, violation_id)
        if row is None or row.get("doc_kind") != DOC_KIND_VIOLATION:
            raise GovernancePolicyNotFoundError(VIOLATION_NOT_FOUND)
        current = self._load(row)
        if current.violation.status not in _ACTIVE_VIOLATION:
            raise GovernancePolicyStaleError(VIOLATION_RESOLVED, "violation is no longer active")
        if current.etag != if_match:
            raise GovernancePolicyStaleError(VIOLATION_MODIFIED)
        updated = PolicyViolation.model_validate(
            {
                **current.violation.model_dump(mode="json"),
                "status": "excepted" if exception_id is not None else "open",
                "exception_id": exception_id,
            }
        )
        try:
            stored = await self._backend.replace(
                self._document(updated, current.last_run_id), if_match=if_match
            )
        except DocumentConflictError:
            raise GovernancePolicyStaleError(VIOLATION_MODIFIED) from None
        return self._load(stored)

    async def get(
        self, customer_id: str, domain_id: str, violation_id: str
    ) -> StoredViolation | None:
        row = await self._backend.read(customer_id, domain_id, violation_id)
        if row is None or row.get("doc_kind") != DOC_KIND_VIOLATION:
            return None
        return self._load(row)

    async def list(
        self, customer_id: str, filters: ViolationFilters, page: PageRequest
    ) -> Page[StoredViolation]:
        domains = _check_domains(filters.domain_ids)
        if not domains:
            return Page[StoredViolation](items=(), next_cursor=None)
        equals: builtins.list[tuple[str, Any]] = [("doc_kind", DOC_KIND_VIOLATION)]
        for name in ("status", "policy_id", "rule_id", "subject_id", "severity"):
            value = getattr(filters, name)
            if value is not None:
                equals.append((name, value))
        rows = await self._backend.query(
            DocumentQuery(
                customer_id=customer_id,
                limit=page.page_size + 1,
                equals=tuple(equals),
                any_of=(("domain_id", domains),),
                after=decode_cursor(page.cursor) if page.cursor else None,
                descending=True,
            )
        )
        return _page([self._load(r) for r in rows], [r["sort_key"] for r in rows], page.page_size)


def _observation_key(observation: ViolationObservation) -> str:
    return dedup_key(
        observation.policy_id,
        observation.rule_id,
        observation.subject.canonical_id,
        observation.evidence_class,
    )


# --- exceptions ---------------------------------------------------------------------------------


class DocumentExceptionStore:
    """:class:`ExceptionStore` written once over a :class:`DocumentBackend`."""

    def __init__(self, backend: DocumentBackend) -> None:
        self._backend = backend

    @staticmethod
    def _document(exception: PolicyException) -> dict[str, Any]:
        body = exception.model_dump(mode="json")
        body["id"] = exception.exception_id.root
        body["doc_kind"] = DOC_KIND_EXCEPTION
        body["sort_key"] = f"{exception.requested_at.root}|{exception.exception_id.root}"
        body["subject_id"] = exception.subject.canonical_id
        return body

    @staticmethod
    def _load(row: Mapping[str, Any]) -> StoredException:
        try:
            exception = PolicyException.model_validate(_strip(row, "subject_id"))
        except ValidationError:
            raise record_invalid() from None
        return StoredException(exception=exception, etag=_etag(row))

    async def request(self, exception: PolicyException) -> StoredException:
        if exception.status != "requested":
            raise _invalid("invalid_exception", "/status", "a new exception is requested")
        if exception.decided_by is not None or exception.decided_at is not None:
            raise _invalid("invalid_exception", "/decided_by", "a request is not decided")
        if _parse_timestamp(exception.expires_at.root) <= _parse_timestamp(
            exception.requested_at.root
        ):
            raise _invalid("invalid_exception", "/expires_at", "expiry is after the request")
        try:
            row = await self._backend.create(self._document(exception))
        except DocumentExistsError:
            raise GovernancePolicyStaleError(EXCEPTION_EXISTS, "exception already exists") from None
        return self._load(row)

    async def set_state(
        self,
        customer_id: str,
        domain_id: str,
        exception_id: str,
        status: ExceptionStatusName,
        *,
        if_match: str,
        decided_by: str | None = None,
        decided_at: datetime | None = None,
        audit_id: str | None = None,
    ) -> StoredException:
        row = await self._backend.read(customer_id, domain_id, exception_id)
        if row is None or row.get("doc_kind") != DOC_KIND_EXCEPTION:
            raise GovernancePolicyNotFoundError(EXCEPTION_NOT_FOUND)
        current = self._load(row)
        if status not in _EXCEPTION_TRANSITIONS.get(current.exception.status, frozenset()):
            raise GovernancePolicyStaleError(INVALID_EXCEPTION_TRANSITION, "transition refused")
        if status in ("approved", "rejected") and (decided_by is None or decided_at is None):
            raise _invalid("invalid_exception", "/decided_by", "a decision names its reviewer")
        if current.etag != if_match:
            raise GovernancePolicyStaleError(EXCEPTION_MODIFIED)
        update: dict[str, Any] = {"status": status}
        if decided_by is not None:
            update["decided_by"] = decided_by
        if decided_at is not None:
            update["decided_at"] = _timestamp(decided_at)
        if audit_id is not None:
            update["audit_id"] = audit_id
        try:
            updated = PolicyException.model_validate(
                {**current.exception.model_dump(mode="json"), **update}
            )
        except ValidationError as exc:
            raise _invalid("invalid_exception", "", f"{len(exc.errors())} invalid fields") from None
        try:
            stored = await self._backend.replace(self._document(updated), if_match=if_match)
        except DocumentConflictError:
            raise GovernancePolicyStaleError(EXCEPTION_MODIFIED) from None
        return self._load(stored)

    async def get(
        self, customer_id: str, domain_id: str, exception_id: str
    ) -> StoredException | None:
        row = await self._backend.read(customer_id, domain_id, exception_id)
        if row is None or row.get("doc_kind") != DOC_KIND_EXCEPTION:
            return None
        return self._load(row)

    async def active_for(
        self,
        customer_id: str,
        domain_id: str,
        *,
        subject_id: str,
        policy_id: str,
        rule_id: str,
        now: datetime,
    ) -> StoredException | None:
        rows = await self._backend.query(
            DocumentQuery(
                customer_id=customer_id,
                domain_id=domain_id,
                limit=100,
                equals=(
                    ("doc_kind", DOC_KIND_EXCEPTION),
                    ("subject_id", subject_id),
                    ("policy_id", policy_id),
                    ("rule_id", rule_id),
                    ("status", "approved"),
                ),
            )
        )
        if now.tzinfo is None:
            raise _invalid("invalid_timestamp", "/now", "timestamps must be timezone-aware")
        live = [
            self._load(r)
            for r in rows
            if _parse_timestamp(str(r.get("expires_at", ""))) > now.astimezone(UTC)
        ]
        live.sort(key=lambda s: (s.exception.expires_at.root, s.exception.exception_id.root))
        return live[-1] if live else None

    async def list(
        self, customer_id: str, filters: ExceptionFilters, page: PageRequest
    ) -> Page[StoredException]:
        domains = _check_domains(filters.domain_ids)
        if not domains:
            return Page[StoredException](items=(), next_cursor=None)
        equals: builtins.list[tuple[str, Any]] = [("doc_kind", DOC_KIND_EXCEPTION)]
        for name in ("status", "policy_id", "rule_id", "subject_id", "violation_id"):
            value = getattr(filters, name)
            if value is not None:
                equals.append((name, value))
        rows = await self._backend.query(
            DocumentQuery(
                customer_id=customer_id,
                limit=page.page_size + 1,
                equals=tuple(equals),
                any_of=(("domain_id", domains),),
                after=decode_cursor(page.cursor) if page.cursor else None,
                descending=True,
            )
        )
        return _page([self._load(r) for r in rows], [r["sort_key"] for r in rows], page.page_size)


# --- enforcement bindings -----------------------------------------------------------------------


class BindingStore:
    """Enforcement bindings as ``admin_config`` documents (``admin_kind: enforcement_binding``).

    Over either :class:`~neurosphere_core.admin.store.InMemoryAdminConfigRepository` or the Cosmos
    repository, so the memory and Cosmos behaviour is the shipped repository's. Rules:

    * :meth:`ensure_bindings` creates missing bindings at ``audit`` (or ``off``) and state
      ``pending``; ``enforce`` is refused ``enforce_requires_mode_change`` (GD-7). An existing
      binding is returned unchanged: publish never resets a mode set by an approved action.
    * :meth:`set_mode` is the ONLY path that can set ``enforce``; it is what PRP-108's
      ``enforcement_mode_change`` handler calls after approval. A mode change resets ``state`` to
      ``pending`` (the new mode is not applied until verified).
    * ``target`` ``None`` = every target of the point in the domain.
    """

    def __init__(self, repository: AdminConfigRepository, *, list_limit: int = 1000) -> None:
        self.repository = repository
        self.list_limit = list_limit

    @staticmethod
    def _load(document: AdminConfigDocument) -> StoredBinding:
        body = document.body
        if not isinstance(body, EnforcementBinding):
            raise record_invalid()
        return StoredBinding(
            binding=body,
            etag=document.etag.root,
            version=document.version.root,
            retired=document.status == "retired",
        )

    async def ensure_bindings(
        self,
        policy: PolicyDefinition,
        points: Iterable[str],
        mode: str,
        *,
        updated_by: str,
        target: TargetRef | None = None,
    ) -> builtins.list[StoredBinding]:
        if mode not in ("audit", "off"):
            raise _invalid(
                ENFORCE_REQUIRES_MODE_CHANGE,
                "/mode",
                "a binding starts in audit or off; enforce needs an approved mode change",
            )
        allowed = {p for rule in policy.rules for p in POINTS_BY_RULE_KIND[rule.kind.root]}
        wanted = list(dict.fromkeys(points))
        for point in wanted:
            if point not in _POINTS:
                raise _invalid("unknown_enforcement_point", "/point", "unknown point")
            if point not in allowed:
                raise _invalid(POINT_NOT_APPLICABLE, "/point", "no rule of the policy binds here")
        customer = policy.customer_id.root
        out: builtins.list[StoredBinding] = []
        for point in wanted:
            binding_id = binding_id_for(
                customer,
                policy.policy_id.root,
                point,
                target.canonical_id if target is not None else None,
            )
            existing = await self.repository.get(customer, BINDING_ADMIN_KIND, binding_id)
            if existing is not None:
                out.append(self._load(existing))
                continue
            body = EnforcementBinding.model_validate(
                {
                    "schema_version": POLICY_SCHEMA_VERSION,
                    "binding_id": binding_id,
                    "cloud": policy.cloud.root,
                    "customer_id": customer,
                    "domain_id": policy.domain_id.root,
                    "policy_id": policy.policy_id.root,
                    "point": point,
                    "target": target.model_dump(mode="json") if target is not None else None,
                    "mode": mode,
                    "state": "pending",
                }
            )
            try:
                created = await self.repository.create(
                    customer, BINDING_ADMIN_KIND, binding_id, body, updated_by=updated_by
                )
            except StaleVersionError:
                again = await self.repository.get(customer, BINDING_ADMIN_KIND, binding_id)
                if again is None:
                    raise
                created = again
            out.append(self._load(created))
        return out

    async def get(self, customer_id: str, binding_id: str) -> StoredBinding | None:
        document = await self.repository.get(customer_id, BINDING_ADMIN_KIND, binding_id)
        return None if document is None else self._load(document)

    async def list(
        self,
        customer_id: str,
        *,
        point: str | None = None,
        policy_id: str | None = None,
        target: str | None = None,
        include_all_targets: bool = True,
        domain_ids: Sequence[str] | None = None,
        include_retired: bool = False,
    ) -> builtins.list[StoredBinding]:
        """Bindings filtered client-side; ``target`` matches that canonical id and, unless
        ``include_all_targets`` is False, the null-target bindings that cover it."""
        documents = await self.repository.list_by_kind(
            customer_id, BINDING_ADMIN_KIND, include_retired=include_retired, limit=self.list_limit
        )
        domains = None if domain_ids is None else set(domain_ids)
        out: builtins.list[StoredBinding] = []
        for document in documents:
            stored = self._load(document)
            binding = stored.binding
            if point is not None and binding.point.root != point:
                continue
            if policy_id is not None and binding.policy_id.root != policy_id:
                continue
            if domains is not None and binding.domain_id.root not in domains:
                continue
            if target is not None:
                bound = binding.target.canonical_id if binding.target is not None else None
                if bound != target and not (bound is None and include_all_targets):
                    continue
            out.append(stored)
        return out

    async def _replace(
        self,
        customer_id: str,
        binding_id: str,
        update: Mapping[str, Any],
        *,
        if_match: str,
        updated_by: str,
    ) -> StoredBinding:
        current = await self.get(customer_id, binding_id)
        if current is None:
            raise GovernancePolicyNotFoundError(BINDING_NOT_FOUND)
        if current.etag != if_match:
            raise GovernancePolicyStaleError(BINDING_MODIFIED)
        body = EnforcementBinding.model_validate(
            {**current.binding.model_dump(mode="json"), **update}
        )
        try:
            document = await self.repository.replace(
                customer_id,
                BINDING_ADMIN_KIND,
                binding_id,
                body,
                if_match=if_match,
                updated_by=updated_by,
            )
        except NotFoundError:
            raise GovernancePolicyNotFoundError(BINDING_NOT_FOUND) from None
        except StaleVersionError as exc:
            raise GovernancePolicyStaleError(exc.reason or BINDING_MODIFIED) from None
        return self._load(document)

    async def set_mode(
        self,
        customer_id: str,
        binding_id: str,
        mode: EnforcementModeName,
        *,
        if_match: str,
        updated_by: str,
        intent_id: str | None = None,
        audit_id: str | None = None,
    ) -> StoredBinding:
        if mode not in _MODES:
            raise _invalid("unknown_enforcement_mode", "/mode", "unknown mode")
        return await self._replace(
            customer_id,
            binding_id,
            {
                "mode": mode,
                "state": "pending",
                "last_intent_id": intent_id,
                "last_audit_id": audit_id,
            },
            if_match=if_match,
            updated_by=updated_by,
        )

    async def set_state(
        self,
        customer_id: str,
        binding_id: str,
        state: Literal["pending", "applied", "failed", "drifted", "not_supported"],
        *,
        intent_id: str | None,
        audit_id: str | None,
        if_match: str,
        updated_by: str,
        verified_at: datetime | None = None,
    ) -> StoredBinding:
        if state not in _BINDING_STATES:
            raise _invalid("unknown_binding_state", "/state", "unknown state")
        update: dict[str, Any] = {
            "state": state,
            "last_intent_id": intent_id,
            "last_audit_id": audit_id,
        }
        if verified_at is not None:
            update["last_verified_at"] = _timestamp(verified_at)
        return await self._replace(
            customer_id, binding_id, update, if_match=if_match, updated_by=updated_by
        )

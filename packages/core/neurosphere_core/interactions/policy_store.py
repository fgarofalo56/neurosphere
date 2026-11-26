"""Capture policy store and the governed change functions (PRP-103 item 1).

Storage: Cosmos NoSQL container ``interaction_capture_policies`` (partition key
``/customer_id``, declared by PRP-102 in ``neurosphere_core.stores.containers``). One document
per policy: the PRP-99 ``CapturePolicy`` plus ``id`` (= ``capture_policy_id``) and
``doc_type = capture_policy``. The policy carries its own ``version`` (+1 on every change); the
Cosmos ``_etag`` guards each write (create-only for a new policy, ``IfNotModified`` replace
otherwise; a lost race is ``stale_version``). :class:`InMemoryCapturePolicyStore` has the same
semantics for tests and ``NS_ENV=local``. Capture policies are NOT an ``admin_kind`` and this
module is the only code over the container.

Changes (there is no API route that creates or changes a policy):

* :func:`apply_capture_policy_change` is what PRP-108's ``platform-control`` handler calls for an
  approved ``capture_policy_change`` (stages ``propose``, ``activate``, ``suspend``, ``retire``).
  It refuses without an approving audit id, validates the change against the stored version,
  writes the new version with the ETag, reads it back and audits the whole thing through
  :func:`~neurosphere_core.audit.repository.run_audited_mutation` as ``capture_policy.apply`` on
  the policy's domain chain.
* :func:`read_back_capture_policy` returns the stored state for verify.
* :func:`seed_local_capture_policy` writes a policy directly, only when ``NS_ENV=local`` is set
  explicitly (audit operation ``capture_policy.seed_local``); until PRP-108 ships it is the only
  way a policy exists.

Audit records hold ids, versions and a digest of the policy, never content. Errors are reason
codes; no document or SDK text reaches a message.
"""

from __future__ import annotations

import builtins
import os
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal, NoReturn, Protocol, TypeGuard, runtime_checkable

from azure.core import MatchConditions
from azure.cosmos import PartitionKey
from azure.cosmos.aio import ContainerProxy, CosmosClient, DatabaseProxy
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_contracts.audit.v1.audit_record import Subject
from pydantic import BaseModel, ConfigDict, Field

from neurosphere_core.audit.builders import (
    AuditContext,
    AuditDraft,
    build_after,
    build_before,
    build_denied,
    make_subject,
)
from neurosphere_core.audit.chains import domain_audit_chain_id
from neurosphere_core.audit.repository import AuditRepository, run_audited_mutation
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
    NotFoundError,
    RateLimitedError,
    StaleVersionError,
    ValidationIssue,
)
from neurosphere_core.interactions.policy import (
    CAPTURE_POLICY_ENTITY_TYPE,
    CAPTURE_POLICY_SCHEMA_VERSION,
    CapturePolicy,
    capture_policy_canonical_id,
    parse_capture_policy,
)

__all__ = [
    "CAPTURE_POLICY_EXISTS",
    "CAPTURE_POLICY_MODIFIED",
    "CAPTURE_POLICY_NOT_FOUND",
    "CAPTURE_POLICY_STORE_UNAVAILABLE",
    "DEFAULT_CAPTURE_POLICY_CONTAINER",
    "DOC_TYPE",
    "OPERATION_APPLY",
    "OPERATION_SEED_LOCAL",
    "PARTITION_KEY_PATH",
    "CapturePolicyChange",
    "CapturePolicyStage",
    "CapturePolicyStore",
    "CosmosCapturePolicyStore",
    "InMemoryCapturePolicyStore",
    "StoredCapturePolicy",
    "apply_capture_policy_change",
    "create_capture_policy_container",
    "read_back_capture_policy",
    "seed_local_capture_policy",
]

DEFAULT_CAPTURE_POLICY_CONTAINER: Final = "interaction_capture_policies"
PARTITION_KEY_PATH: Final = "/customer_id"
DOC_TYPE: Final = "capture_policy"
OPERATION_APPLY: Final = "capture_policy.apply"
OPERATION_SEED_LOCAL: Final = "capture_policy.seed_local"
DEFAULT_LIST_LIMIT: Final = 100
MAX_LIST_LIMIT: Final = 1000

CAPTURE_POLICY_EXISTS: Final = "capture_policy_exists"
CAPTURE_POLICY_MODIFIED: Final = "capture_policy_modified"
CAPTURE_POLICY_NOT_FOUND: Final = "capture_policy_not_found"
CAPTURE_POLICY_STORE_UNAVAILABLE: Final = "capture_policy_store_unavailable"
CAPTURE_POLICY_RECORD_INVALID: Final = "capture_policy_record_invalid"
CAPTURE_POLICY_READ_BACK_MISMATCH: Final = "capture_policy_read_back_mismatch"
APPROVAL_REQUIRED: Final = "approval_required"
_UUID_PATTERN: Final = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
LOCAL_ONLY: Final = "capture_seed_local_only"

#: Fields the server sets; a proposed body may carry them but they are always overwritten.
_SERVER_FIELDS: Final = frozenset(
    {
        "schema_version",
        "version",
        "previous_version",
        "approved_intent_id",
        "approved_audit_id",
        "effective_from",
        "state",
    }
)
#: Fields that name the policy; a new version may not change them.
_IDENTITY_FIELDS: Final = ("capture_policy_id", "cloud", "customer_id", "domain_id")

CapturePolicyStage = Literal["propose", "activate", "suspend", "retire"]
#: Stage -> states the stored policy may be in (``None`` = no stored policy yet).
_ALLOWED_FROM: Final[Mapping[str, frozenset[str | None]]] = {
    "propose": frozenset({None, "proposed", "active", "suspended"}),
    "activate": frozenset({"proposed", "suspended"}),
    "suspend": frozenset({"active"}),
    "retire": frozenset({"proposed", "active", "suspended"}),
}
_TARGET_STATE: Final[Mapping[str, str]] = {
    "propose": "proposed",
    "activate": "active",
    "suspend": "suspended",
    "retire": "retired",
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unavailable() -> DependencyTransientError:
    return DependencyTransientError(
        "capture policy store is unavailable", reason=CAPTURE_POLICY_STORE_UNAVAILABLE
    )


def _record_invalid() -> DependencyTransientError:
    return DependencyTransientError(
        "stored capture policy failed validation",
        reason=CAPTURE_POLICY_RECORD_INVALID,
        upstream_invalid=True,
    )


def _exists() -> StaleVersionError:
    return StaleVersionError("capture policy already exists", reason=CAPTURE_POLICY_EXISTS)


def _modified() -> StaleVersionError:
    return StaleVersionError(
        "capture policy changed since it was read", reason=CAPTURE_POLICY_MODIFIED
    )


def _invalid(reason: str, pointer: str, detail: str) -> InvalidSchemaError:
    return InvalidSchemaError(detail, errors=[ValidationIssue(pointer, detail)], reason=reason)


@dataclass(frozen=True, slots=True)
class StoredCapturePolicy:
    """A stored policy and the store ETag that guards its next write."""

    policy: CapturePolicy
    etag: str


@runtime_checkable
class CapturePolicyStore(Protocol):
    """Where capture policies live (one current version per policy id and customer)."""

    async def get(
        self, policy_id: str, *, customer_id: str | None = None
    ) -> StoredCapturePolicy | None:
        """The stored policy, or ``None``. Without ``customer_id`` the id must be unique."""
        ...

    async def list(
        self, *, customer_id: str | None = None, limit: int = DEFAULT_LIST_LIMIT
    ) -> builtins.list[StoredCapturePolicy]:
        """At most ``limit`` policies ordered by customer then policy id."""
        ...

    async def create(self, policy: CapturePolicy) -> StoredCapturePolicy:
        """Create-only; an existing policy is ``stale_version`` ``capture_policy_exists``."""
        ...

    async def replace(self, policy: CapturePolicy, *, if_match: str) -> StoredCapturePolicy:
        """Replace when the ETag matches, else ``stale_version`` ``capture_policy_modified``."""
        ...


def _check_limit(limit: int) -> None:
    if not 1 <= limit <= MAX_LIST_LIMIT:
        raise _invalid("invalid_query", "/limit", f"limit must be 1..{MAX_LIST_LIMIT}")


def _ambiguous() -> InvalidSchemaError:
    return _invalid(
        "capture_policy_customer_required",
        "/customer_id",
        "customer_id is required: the policy id exists for more than one customer",
    )


# --- in-memory twin ------------------------------------------------------------------------------


class InMemoryCapturePolicyStore:
    """:class:`CapturePolicyStore` in a dict with the Cosmos semantics (tests, local)."""

    def __init__(self) -> None:
        self._docs: dict[tuple[str, str], tuple[dict[str, Any], str]] = {}
        self._counter = 0

    def _next_etag(self) -> str:
        self._counter += 1
        return f'"{self._counter:08x}"'

    @staticmethod
    def _load(doc: Mapping[str, Any], etag: str) -> StoredCapturePolicy:
        return StoredCapturePolicy(policy=parse_capture_policy(dict(doc)), etag=etag)

    async def get(
        self, policy_id: str, *, customer_id: str | None = None
    ) -> StoredCapturePolicy | None:
        if customer_id is not None:
            hit = self._docs.get((customer_id, policy_id))
            return None if hit is None else self._load(*hit)
        hits = sorted(k for k in self._docs if k[1] == policy_id)
        if len(hits) > 1:
            raise _ambiguous()
        return None if not hits else self._load(*self._docs[hits[0]])

    async def list(
        self, *, customer_id: str | None = None, limit: int = DEFAULT_LIST_LIMIT
    ) -> builtins.list[StoredCapturePolicy]:
        _check_limit(limit)
        keys = sorted(k for k in self._docs if customer_id is None or k[0] == customer_id)
        return [self._load(*self._docs[k]) for k in keys[:limit]]

    async def create(self, policy: CapturePolicy) -> StoredCapturePolicy:
        key = (policy.customer, policy.policy_id)
        if key in self._docs:
            raise _exists()
        etag = self._next_etag()
        self._docs[key] = (policy.model_dump(mode="json"), etag)
        return self._load(*self._docs[key])

    async def replace(self, policy: CapturePolicy, *, if_match: str) -> StoredCapturePolicy:
        key = (policy.customer, policy.policy_id)
        current = self._docs.get(key)
        if current is None or current[1] != if_match:
            raise _modified()
        etag = self._next_etag()
        self._docs[key] = (policy.model_dump(mode="json"), etag)
        return self._load(*self._docs[key])


# --- Cosmos --------------------------------------------------------------------------------------


async def create_capture_policy_container(
    database: DatabaseProxy, container_id: str = DEFAULT_CAPTURE_POLICY_CONTAINER
) -> ContainerProxy:
    """Create (or open) the container (partition key ``/customer_id``)."""
    return await database.create_container_if_not_exists(
        id=container_id, partition_key=PartitionKey(path=PARTITION_KEY_PATH)
    )


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(
            1, "capture policy store throttled the request", reason="capture_policy_throttled"
        ) from exc
    raise _unavailable() from exc


def _from_row(row: Mapping[str, Any]) -> StoredCapturePolicy:
    document = {
        k: v for k, v in row.items() if not k.startswith("_") and k not in {"id", "doc_type"}
    }
    try:
        policy = parse_capture_policy(document)
    except InvalidSchemaError:
        raise _record_invalid() from None
    return StoredCapturePolicy(policy=policy, etag=str(row.get("_etag", "")))


def _body(policy: CapturePolicy) -> dict[str, Any]:
    body = policy.model_dump(mode="json")
    body["id"] = policy.policy_id
    body["doc_type"] = DOC_TYPE
    return body


class CosmosCapturePolicyStore:
    """:class:`CapturePolicyStore` on the ``interaction_capture_policies`` container."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_CAPTURE_POLICY_CONTAINER,
    ) -> CosmosCapturePolicyStore:
        return cls(client.get_database_client(database).get_container_client(container))

    async def get(
        self, policy_id: str, *, customer_id: str | None = None
    ) -> StoredCapturePolicy | None:
        if customer_id is not None:
            try:
                row = await self._container.read_item(item=policy_id, partition_key=customer_id)
            except CosmosResourceNotFoundError:
                return None
            except Exception as exc:
                _raise_mapped(exc)
            return _from_row(row) if row.get("doc_type") == DOC_TYPE else None
        sql = "SELECT TOP 2 * FROM c WHERE c.id = @id AND c.doc_type = @doc_type"
        params: builtins.list[dict[str, Any]] = [
            {"name": "@id", "value": policy_id},
            {"name": "@doc_type", "value": DOC_TYPE},
        ]
        try:
            rows = [row async for row in self._container.query_items(sql, parameters=params)]
        except Exception as exc:
            _raise_mapped(exc)
        if len(rows) > 1:
            raise _ambiguous()
        return _from_row(rows[0]) if rows else None

    async def list(
        self, *, customer_id: str | None = None, limit: int = DEFAULT_LIST_LIMIT
    ) -> builtins.list[StoredCapturePolicy]:
        _check_limit(limit)
        clauses = ["c.doc_type = @doc_type"]
        params: builtins.list[dict[str, Any]] = [
            {"name": "@limit", "value": limit},
            {"name": "@doc_type", "value": DOC_TYPE},
        ]
        if customer_id is not None:
            clauses.append("c.customer_id = @customer_id")
            params.append({"name": "@customer_id", "value": customer_id})
        sql = (
            "SELECT TOP @limit * FROM c WHERE "  # noqa: S608
            + " AND ".join(clauses)
            # One ORDER BY term only: a multi-property ORDER BY needs a composite index the
            # container does not declare (400 on real Cosmos). Customer order is applied below.
            + " ORDER BY c.id ASC"
        )
        try:
            rows = [row async for row in self._container.query_items(sql, parameters=params)]
        except Exception as exc:
            _raise_mapped(exc)
        stored = [_from_row(row) for row in rows]
        stored.sort(key=lambda s: (s.policy.customer, s.policy.policy_id))
        return stored

    async def create(self, policy: CapturePolicy) -> StoredCapturePolicy:
        try:
            row = await self._container.create_item(body=_body(policy))
        except CosmosResourceExistsError:
            raise _exists() from None
        except Exception as exc:
            _raise_mapped(exc)
        return _from_row(row)

    async def replace(self, policy: CapturePolicy, *, if_match: str) -> StoredCapturePolicy:
        try:
            row = await self._container.replace_item(
                item=policy.policy_id,
                body=_body(policy),
                etag=if_match,
                match_condition=MatchConditions.IfNotModified,
            )
        except (CosmosAccessConditionFailedError, CosmosResourceNotFoundError):
            raise _modified() from None
        except Exception as exc:
            _raise_mapped(exc)
        return _from_row(row)


# --- governed change -----------------------------------------------------------------------------


class CapturePolicyChange(BaseModel):
    """One approved ``capture_policy_change`` (PRP-108 defines the action diff that maps here).

    ``base_version`` is the stored version the change was drafted against (``None`` only when
    proposing a new policy). ``policy`` is the full body for ``propose`` and absent otherwise;
    its server-set fields (version, state, approval ids, effective_from) are ignored.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: CapturePolicyStage
    capture_policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    customer_id: str = Field(pattern=r"^[a-z0-9._-]+$", max_length=128)
    base_version: int | None = Field(default=None, ge=1)
    approved_intent_id: str = Field(pattern=_UUID_PATTERN)
    policy: Mapping[str, Any] | None = None


def _valid_audit_id(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and re.fullmatch(_UUID_PATTERN, value) is not None


def _comparable(policy: CapturePolicy) -> dict[str, Any]:
    doc = policy.model_dump(mode="json")
    return {k: v for k, v in doc.items() if k not in _SERVER_FIELDS}


def _next_policy(
    change: CapturePolicyChange,
    current: CapturePolicy | None,
    *,
    approved_audit_id: str,
    now: datetime,
) -> CapturePolicy:
    """The new version, or ``invalid_schema`` / ``stale_version`` naming the rule broken."""
    current_state = None if current is None else current.state
    if current_state == "retired":
        raise _invalid("capture_policy_retired", "/stage", "a retired policy cannot change")
    if current_state not in _ALLOWED_FROM[change.stage]:
        raise _invalid(
            "capture_policy_transition_refused",
            "/stage",
            f"stage {change.stage} is not allowed from the stored state",
        )
    if current is None:
        if change.base_version is not None:
            raise _modified()
    elif change.base_version != current.version:
        raise _modified()

    if change.stage == "propose":
        if change.policy is None:
            raise _invalid("capture_policy_body_required", "/policy", "propose needs the policy")
        body = {k: v for k, v in dict(change.policy).items() if k not in _SERVER_FIELDS}
        if body.get("capture_policy_id") != change.capture_policy_id:
            raise _invalid(
                "capture_policy_id_mismatch", "/policy/capture_policy_id", "policy id differs"
            )
        if body.get("customer_id") != change.customer_id:
            raise _invalid(
                "capture_policy_customer_mismatch", "/policy/customer_id", "customer differs"
            )
        approved_intent: str | None = None
        approved_audit: str | None = None
        effective_from: str | None = None
    else:
        if change.policy is not None:
            raise _invalid(
                "capture_policy_body_not_allowed", "/policy", "only propose carries a body"
            )
        if current is None:  # unreachable: _ALLOWED_FROM excludes None for these stages
            raise NotFoundError("capture policy not found", reason=CAPTURE_POLICY_NOT_FOUND)
        body = _comparable(current)
        if change.stage == "activate":
            approved_intent = change.approved_intent_id
            approved_audit = approved_audit_id
            effective_from = _timestamp(now)
        else:
            # suspend / retire keep the activation's approval and start time on the record.
            kept = current.model_dump(mode="json")
            approved_intent = kept["approved_intent_id"]
            approved_audit = kept["approved_audit_id"]
            effective_from = kept["effective_from"]

    if current is not None:
        before = _comparable(current)
        for name in _IDENTITY_FIELDS:
            if body.get(name) != before.get(name):
                raise _invalid(
                    "capture_policy_identity_changed", f"/policy/{name}", f"{name} cannot change"
                )
        if change.stage == "propose" and current.state == "proposed":
            # Re-proposing must change something; compare after defaults are applied.
            candidate = parse_capture_policy(
                {
                    **body,
                    "schema_version": CAPTURE_POLICY_SCHEMA_VERSION,
                    "version": current.version,
                    "state": "proposed",
                }
            )
            if _comparable(candidate) == before:
                raise _invalid("capture_policy_no_change", "/policy", "the change changes nothing")

    version = 1 if current is None else current.version + 1
    return parse_capture_policy(
        {
            **body,
            "schema_version": CAPTURE_POLICY_SCHEMA_VERSION,
            "version": version,
            "previous_version": None if current is None else current.version,
            "state": _TARGET_STATE[change.stage],
            "approved_intent_id": approved_intent,
            "approved_audit_id": approved_audit,
            "effective_from": effective_from,
        }
    )


def _check_scope(cloud: str, customer_id: str, domain_id: str, *, prefix: str) -> None:
    """Cloud and domain must name this customer BEFORE any audit chain is derived from them."""
    if cloud not in {"commercial", "government"}:
        raise _invalid("capture_policy_invalid", f"{prefix}/cloud", "cloud is required")
    if not domain_id.startswith(f"{cloud}:{customer_id}:"):
        raise _invalid(
            "capture_policy_invalid",
            f"{prefix}/domain_id",
            "domain_id must belong to the policy cloud and customer",
        )


def _op_context(
    ctx: AuditContext, operation: str, intent_id: str, *, replace_intent: bool = False
) -> AuditContext:
    """``ctx`` for ``operation``; validated again so ``intent_id`` is a contract ``Uuid``."""
    doc = ctx.model_dump(mode="json")
    doc["operation"] = operation
    if replace_intent or doc.get("intent_id") is None:
        doc["intent_id"] = intent_id
    return AuditContext.model_validate(doc)


def _subject(policy: CapturePolicy | None, cloud: str, customer: str, policy_id: str) -> Subject:
    return make_subject(
        capture_policy_canonical_id(cloud, customer, policy_id),
        CAPTURE_POLICY_ENTITY_TYPE,
        target_version=None if policy is None else str(policy.version),
        state=None if policy is None else policy.model_dump(mode="json"),
    )


def _error_detail(exc: BaseException) -> str:
    if isinstance(exc, NeuroSphereError):
        return exc.reason or exc.code
    return "action_error"


async def _write_and_verify(
    store: CapturePolicyStore, policy: CapturePolicy, current: StoredCapturePolicy | None
) -> CapturePolicy:
    if current is None:
        written = await store.create(policy)
    else:
        written = await store.replace(policy, if_match=current.etag)
    read = await store.get(policy.policy_id, customer_id=policy.customer)
    if read is None or read.policy != policy or written.policy != policy:
        raise DependencyTransientError(
            "capture policy read-back did not match", reason=CAPTURE_POLICY_READ_BACK_MISMATCH
        )
    return read.policy


async def apply_capture_policy_change(
    store: CapturePolicyStore,
    change: CapturePolicyChange,
    approved_audit_id: str | None,
    *,
    audit: AuditRepository,
    ctx: AuditContext,
    clock: Callable[[], datetime] = _utc_now,
) -> CapturePolicy:
    """Apply one approved change: validate, write with the ETag, read back, audit.

    Refusals, in order: no stored policy for a non-``propose`` stage -> ``not_found``; no
    approving audit id -> a ``denied`` record then ``forbidden`` (``approval_required``); the
    stored version differs from ``base_version`` -> ``stale_version``; an invalid
    transition, body or identity change -> ``invalid_schema``. The write runs inside
    ``run_audited_mutation`` (operation ``capture_policy.apply``, the policy's domain chain);
    a failed write or read-back appends a ``failed`` after-record and re-raises.
    """
    current = await store.get(change.capture_policy_id, customer_id=change.customer_id)
    if current is not None:
        cloud, domain = current.policy.cloud.root, current.policy.domain
    elif change.policy is not None:
        cloud = str(change.policy.get("cloud", ""))
        domain = str(change.policy.get("domain_id", ""))
    else:
        raise NotFoundError("capture policy not found", reason=CAPTURE_POLICY_NOT_FOUND)
    _check_scope(cloud, change.customer_id, domain, prefix="/policy")
    chain_id = domain_audit_chain_id(change.customer_id, domain)
    op = _op_context(ctx, OPERATION_APPLY, change.approved_intent_id)
    before_subject = _subject(
        None if current is None else current.policy,
        cloud,
        change.customer_id,
        change.capture_policy_id,
    )
    if not _valid_audit_id(approved_audit_id):
        await audit.append(
            chain_id,
            build_denied(op, code="forbidden", reason=APPROVAL_REQUIRED, subject=before_subject),
        )
        raise ForbiddenError(
            "a capture policy change needs an approving audit id", reason=APPROVAL_REQUIRED
        )
    new_policy = _next_policy(
        change,
        None if current is None else current.policy,
        approved_audit_id=approved_audit_id,
        now=clock(),
    )
    after_subject = _subject(new_policy, cloud, change.customer_id, change.capture_policy_id)

    async def mutate() -> CapturePolicy:
        return await _write_and_verify(store, new_policy, current)

    def failed(exc: BaseException) -> AuditDraft:
        return build_after(
            op, after_subject, result="failed", verified=False, detail=_error_detail(exc)
        )

    return await run_audited_mutation(
        audit,
        chain_id,
        before=build_before(op, before_subject),
        mutate=mutate,
        after=lambda _p: build_after(
            op, after_subject, result="succeeded", verified=True, detail=change.stage
        ),
        on_error=failed,
    )


async def read_back_capture_policy(
    store: CapturePolicyStore, policy_id: str, *, customer_id: str | None = None
) -> CapturePolicy:
    """The stored policy for verify; ``not_found`` when it is absent."""
    stored = await store.get(policy_id, customer_id=customer_id)
    if stored is None:
        raise NotFoundError("capture policy not found", reason=CAPTURE_POLICY_NOT_FOUND)
    return stored.policy


# --- local seed ----------------------------------------------------------------------------------


def _local_env() -> bool:
    """Read the process environment every time; callers cannot supply their own."""
    return os.environ.get("NS_ENV", "").strip() == "local"


async def _own_before_audit_id(audit: AuditRepository, chain_id: str, op: AuditContext) -> str:
    """The audit id of this seed's before-record (the newest matching record on the chain)."""
    tail = await audit.tail(chain_id)
    if tail is not None:
        start = max(0, tail.sequence - 15)
        records = await audit.read_range(chain_id, start=start, limit=tail.sequence - start + 1)
        for record in reversed(records):
            if (
                record.kind == "before"
                and record.operation == OPERATION_SEED_LOCAL
                and record.correlation_id == op.correlation_id
                and record.intent_id is not None
                and op.intent_id is not None
                and record.intent_id.root == op.intent_id.root
            ):
                return record.audit_id.root
    raise DependencyTransientError(
        "seed audit record not found", reason="capture_seed_audit_missing"
    )


async def seed_local_capture_policy(
    store: CapturePolicyStore,
    policy: Mapping[str, Any],
    *,
    audit: AuditRepository,
    ctx: AuditContext,
    clock: Callable[[], datetime] = _utc_now,
) -> CapturePolicy:
    """Write ``policy`` directly, only when the process has ``NS_ENV=local`` set explicitly.

    An unset ``NS_ENV`` is refused too (the settings default of ``local`` is not enough): a
    deployment must opt in to this bypass by name. Nothing is read or written when refused
    (``capability_unavailable`` ``capture_seed_local_only``). The body's state is kept; an
    ``active`` seed records a fresh synthetic intent id (also on the audit records) and the
    audit id of the seed's own before-record as its approval, so the approval points at real
    audit evidence. Version, previous version and ``effective_from`` are set by the server.
    """
    if not _local_env():
        raise CapabilityUnavailableError(
            LOCAL_ONLY, "capture policies can be seeded only when NS_ENV=local"
        )
    body = {k: v for k, v in dict(policy).items() if k not in _SERVER_FIELDS or k == "state"}
    policy_id = str(body.get("capture_policy_id", ""))
    customer_id = str(body.get("customer_id", ""))
    cloud = str(body.get("cloud", ""))
    state = str(body.get("state", "proposed"))
    domain_id = str(body.get("domain_id", ""))
    _check_scope(cloud, customer_id, domain_id, prefix="")
    current = await store.get(policy_id, customer_id=customer_id)
    if current is not None:
        before = _comparable(current.policy)
        for name in _IDENTITY_FIELDS:
            if body.get(name) != before.get(name):
                raise _invalid(
                    "capture_policy_identity_changed", f"/{name}", f"{name} cannot change"
                )
    chain_id = domain_audit_chain_id(customer_id, domain_id)
    # A seed has no action intent: a fresh synthetic one ties the policy to its audit records.
    op = _op_context(ctx, OPERATION_SEED_LOCAL, str(uuid.uuid4()), replace_intent=True)
    version = 1 if current is None else current.policy.version + 1
    base: dict[str, Any] = {
        **body,
        "schema_version": CAPTURE_POLICY_SCHEMA_VERSION,
        "version": version,
        "previous_version": None if current is None else current.policy.version,
        "state": state,
        "approved_intent_id": None,
        "approved_audit_id": None,
        "effective_from": None,
    }
    # Validate everything except the approval before any audit write.
    parse_capture_policy({**base, "state": "proposed"} if state == "active" else base)
    before_subject = _subject(
        None if current is None else current.policy, cloud, customer_id, policy_id
    )
    holder: dict[str, CapturePolicy] = {}

    async def mutate() -> CapturePolicy:
        doc = dict(base)
        if state == "active":
            doc["approved_intent_id"] = None if op.intent_id is None else op.intent_id.root
            doc["approved_audit_id"] = await _own_before_audit_id(audit, chain_id, op)
            doc["effective_from"] = _timestamp(clock())
        new_policy = parse_capture_policy(doc)
        holder["policy"] = new_policy
        return await _write_and_verify(store, new_policy, current)

    def subject_after() -> Subject:
        return _subject(holder.get("policy"), cloud, customer_id, policy_id)

    def failed(exc: BaseException) -> AuditDraft:
        return build_after(
            op, subject_after(), result="failed", verified=False, detail=_error_detail(exc)
        )

    return await run_audited_mutation(
        audit,
        chain_id,
        before=build_before(op, before_subject),
        mutate=mutate,
        after=lambda _p: build_after(
            op, subject_after(), result="succeeded", verified=True, detail="seed_local"
        ),
        on_error=failed,
    )

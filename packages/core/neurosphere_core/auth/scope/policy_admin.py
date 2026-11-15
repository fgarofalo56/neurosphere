"""Write side of the policy store (PRP-65 item 2): the audited admin path's repository.

The read side (:class:`~neurosphere_core.auth.scope.policy.PolicyRepository`, derivation and the
TTL cache) is unchanged. This module writes the SAME documents into the SAME ``policy`` container
(clarification 3), so derivation reads what admin writes with no migration:

* ``put_principal_policy(policy, *, if_match)`` writes one ``PrincipalPolicy`` under an ETag
  precondition (``if_match=None`` means create-only) and bumps the customer's ``PolicyHead``
  ``policy_version`` in the same partition (``/customer_id``). On Cosmos both writes are ONE
  transactional batch, so a crash can never leave a principal change behind an unchanged head
  (the cache is keyed by the head version, PRP-06 C14). A stale principal ETag, or a create that
  finds the document already there, raises ``stale_version``. Every other store failure is
  ``dependency_transient``; nothing is ever reported as written when it was not.
* Pure change functions (:func:`apply_role_change`, :func:`apply_membership_change`,
  :func:`apply_grant_change`, :func:`remove_grant`) turn a PRP-37 ``admin/v1`` change request into
  the next ``PrincipalPolicy``. They refuse a change aimed at another customer (``forbidden``),
  map model rule failures to ``invalid_schema`` (privileged roles without an expiry, a past
  expiry, more members than the document allows) and never echo document content.

Authorization (``policy.manage`` on the right domains, customer-wide where needed) and the audit
record are the caller's job (PRP-39): this layer is storage and pure transformation only.
"""

from __future__ import annotations

import builtins
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from itertools import count
from typing import Any, Final, Protocol, runtime_checkable

from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import CosmosBatchOperationError, CosmosResourceNotFoundError
from neurosphere_contracts.admin.v1.domain_membership_change import DomainMembershipChange
from neurosphere_contracts.admin.v1.resource_grant_change import ResourceGrantChange
from neurosphere_contracts.admin.v1.role_assignment_change import RoleAssignmentChange
from pydantic import ValidationError

from neurosphere_core.auth.scope.cosmos_repository import DEFAULT_POLICY_CONTAINER
from neurosphere_core.auth.scope.memory import InMemoryPolicyRepository
from neurosphere_core.auth.scope.permissions import Role
from neurosphere_core.auth.scope.policy import (
    POLICY_HEAD_ID,
    PolicyGrant,
    PolicyHead,
    PolicyRoleAssignment,
    PrincipalPolicy,
    principal_document_id,
)
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NotFoundError,
    StaleVersionError,
    ValidationIssue,
)

__all__ = [
    "DEFAULT_LIST_LIMIT",
    "FIRST_POLICY_VERSION",
    "MAX_LIST_LIMIT",
    "CosmosPolicyAdminRepository",
    "InMemoryPolicyAdminRepository",
    "PolicyAdminRepository",
    "apply_grant_change",
    "apply_membership_change",
    "apply_role_change",
    "empty_principal_policy",
    "next_policy_version",
    "remove_grant",
]

#: Version written when a customer has no policy head yet.
FIRST_POLICY_VERSION: Final = "admin-1"
DEFAULT_LIST_LIMIT: Final = 200
MAX_LIST_LIMIT: Final = 1000
_MAX_VERSION_LENGTH: Final = 64
_TRAILING_NUMBER: Final = re.compile(r"^(.*?)(\d+)$")
_PRINCIPAL_DOC_TYPE: Final = "principal_policy"
#: Head-only conflicts (another principal written concurrently) are retried this many times.
_HEAD_RETRIES: Final = 3


# ---------------------------------------------------------------------------- versions


def next_policy_version(current: str | None) -> str:
    """The head version after ``current``: its trailing number plus one, prefix kept.

    ``local-3`` -> ``local-4`` (the sandbox writer's form), ``2026.10.01-1`` -> ``2026.10.01-2``,
    ``None`` -> ``admin-1``; a version with no trailing number gains ``-1``. The result always
    differs from ``current`` and matches the ``PolicyHead`` grammar (refused if it would exceed
    64 characters, rather than wrapping back to a version an old cache entry may still carry).
    """
    if current is None:
        return FIRST_POLICY_VERSION
    match = _TRAILING_NUMBER.fullmatch(current)
    candidate = f"{match.group(1)}{int(match.group(2)) + 1}" if match else f"{current}-1"
    if len(candidate) > _MAX_VERSION_LENGTH:
        raise InvalidSchemaError(
            "policy version cannot be advanced",
            errors=[ValidationIssue("/policy_version", "next version exceeds 64 characters")],
            reason="policy_version_exhausted",
        )
    return candidate


# ---------------------------------------------------------------------------- pure changes


def _segments(canonical_id: str) -> tuple[str, str]:
    parts = canonical_id.split(":")
    return parts[0], parts[1]


def _require_customer(customer_id: str, *canonical_ids: str) -> None:
    for cid in canonical_ids:
        if _segments(cid)[1] != customer_id:
            raise ForbiddenError(
                "the change names another customer", reason="cross_customer_change"
            )


def _require_cloud(principal_id: str, *canonical_ids: str) -> None:
    cloud = _segments(principal_id)[0]
    for cid in canonical_ids:
        if _segments(cid)[0] != cloud:
            raise ForbiddenError(
                "the change crosses the cloud boundary", reason="cross_cloud_change"
            )


def _invalid(exc: ValidationError, pointer: str) -> InvalidSchemaError:
    # Pointer plus the pydantic error type only: never the offending value (no echo of content).
    issues = [
        ValidationIssue(pointer + "".join(f"/{p}" for p in err["loc"]), str(err["type"]))
        for err in exc.errors(include_input=False, include_url=False)
    ]
    return InvalidSchemaError("policy change is invalid", errors=issues, reason="policy_invalid")


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _require_future(expires_at: datetime | None, now: datetime | None, pointer: str) -> None:
    if expires_at is not None and now is not None and expires_at <= now:
        raise InvalidSchemaError(
            "expiry is not in the future",
            errors=[ValidationIssue(pointer, "expires_at must be later than now")],
            reason="expiry_in_past",
        )


def empty_principal_policy(customer_id: str, principal_id: str) -> PrincipalPolicy:
    """A principal document with no memberships, roles or grants (the deny-everything shape)."""
    _require_customer(customer_id, principal_id)
    return PrincipalPolicy(
        id=principal_document_id(principal_id), customer_id=customer_id, principal_id=principal_id
    )


def _base(policy: PrincipalPolicy | None, customer_id: str, principal_id: str) -> PrincipalPolicy:
    _require_customer(customer_id, principal_id)
    if policy is None:
        return empty_principal_policy(customer_id, principal_id)
    if policy.customer_id != customer_id or policy.principal_id != principal_id:
        raise ForbiddenError(
            "the change does not belong to this policy document", reason="cross_customer_change"
        )
    return policy


def _rebuild(policy: PrincipalPolicy, **changes: Any) -> PrincipalPolicy:
    data = policy.model_dump()
    data.update(changes)
    try:
        return PrincipalPolicy.model_validate(data)
    except ValidationError as exc:
        raise _invalid(exc, "") from exc


def apply_role_change(
    policy: PrincipalPolicy | None,
    change: RoleAssignmentChange,
    *,
    customer_id: str,
    now: datetime | None = None,
) -> PrincipalPolicy:
    """Next document after ``change``: ``assign`` creates or replaces ``assignment_id``;
    ``remove`` deletes it (``not_found`` when absent). Membership is NOT changed: a role on a
    domain the principal is not a member of is clipped by derivation, exactly as before; the
    caller pairs it with :func:`apply_membership_change` when it means both.
    """
    principal_id = change.principal_id.root
    base = _base(policy, customer_id, principal_id)
    assignment_id = change.assignment_id.root
    others = tuple(a for a in base.role_assignments if a.assignment_id != assignment_id)
    if change.op == "remove":
        if len(others) == len(base.role_assignments):
            raise NotFoundError("no such role assignment", reason="assignment_not_found")
        return _rebuild(base, role_assignments=others)
    if change.role is None or not change.domain_ids:
        raise InvalidSchemaError(
            "assign needs a role and at least one domain",
            errors=[ValidationIssue("/role", "role and domain_ids are required for assign")],
            reason="policy_invalid",
        )
    domains = tuple(d.root for d in change.domain_ids)
    _require_customer(customer_id, *domains)
    _require_cloud(principal_id, *domains)
    expires_at = _parse_ts(change.expires_at.root) if change.expires_at is not None else None
    _require_future(expires_at, now, "/expires_at")
    try:
        assignment = PolicyRoleAssignment(
            assignment_id=assignment_id,
            role=Role(change.role.root),
            domain_ids=domains,
            expires_at=expires_at,
            reason=change.reason.root,
        )
    except ValidationError as exc:
        raise _invalid(exc, "") from exc
    return _rebuild(base, role_assignments=(*others, assignment))


def apply_membership_change(
    policy: PrincipalPolicy | None, change: DomainMembershipChange, *, customer_id: str
) -> PrincipalPolicy:
    """Next document after ``change``: ``add`` is idempotent; ``remove`` of a domain the
    principal is not a member of is ``not_found``. Role assignments are left as they are
    (derivation clips any role on a domain the principal is no longer a member of)."""
    principal_id = change.principal_id.root
    base = _base(policy, customer_id, principal_id)
    domain = change.domain_id.root
    _require_customer(customer_id, domain)
    _require_cloud(principal_id, domain)
    members = tuple(base.domain_memberships)
    if change.op == "add":
        if domain in members:
            return base
        return _rebuild(base, domain_memberships=tuple(sorted((*members, domain))))
    if domain not in members:
        raise NotFoundError("no such domain membership", reason="membership_not_found")
    return _rebuild(base, domain_memberships=tuple(m for m in members if m != domain))


def apply_grant_change(
    policy: PrincipalPolicy | None,
    change: ResourceGrantChange,
    *,
    customer_id: str,
    now: datetime | None = None,
) -> PrincipalPolicy:
    """Next document with grant ``grant_id`` created or replaced. A grant names one resource;
    a domain id is refused (a grant never opens a domain; derivation would drop it anyway)."""
    principal_id = change.principal_id.root
    base = _base(policy, customer_id, principal_id)
    resource_id = change.resource_id.root
    _require_customer(customer_id, resource_id)
    _require_cloud(principal_id, resource_id)
    if resource_id.split(":")[3] == "domain":
        raise InvalidSchemaError(
            "a resource grant cannot target a domain",
            errors=[ValidationIssue("/resource_id", "domain ids are not grant targets")],
            reason="grant_targets_domain",
        )
    expires_at = _parse_ts(change.expires_at.root)
    _require_future(expires_at, now, "/expires_at")
    grant_id = change.grant_id.root
    try:
        grant = PolicyGrant(
            grant_id=grant_id,
            resource_id=resource_id,
            permissions=tuple(p.root for p in change.permissions),
            expires_at=expires_at,
            reason=change.reason.root,
        )
    except ValidationError as exc:
        raise _invalid(exc, "") from exc
    others = tuple(g for g in base.grants if g.grant_id != grant_id)
    return _rebuild(base, grants=(*others, grant))


def remove_grant(policy: PrincipalPolicy, grant_id: str, *, customer_id: str) -> PrincipalPolicy:
    """Next document without grant ``grant_id`` (``not_found`` when absent)."""
    base = _base(policy, customer_id, policy.principal_id)
    others = tuple(g for g in base.grants if g.grant_id != grant_id)
    if len(others) == len(base.grants):
        raise NotFoundError("no such grant", reason="grant_not_found")
    return _rebuild(base, grants=others)


# ---------------------------------------------------------------------------- repository


@runtime_checkable
class PolicyAdminRepository(Protocol):
    """Write side of the policy store. ``customer_id`` is the partition; the caller binds it to
    the server-derived scope's customer, never to request input."""

    async def get_with_etag(
        self, customer_id: str, principal_id: str
    ) -> tuple[PrincipalPolicy, str] | None: ...

    async def list_principals(
        self, customer_id: str, *, limit: int = DEFAULT_LIST_LIMIT
    ) -> builtins.list[PrincipalPolicy]: ...

    async def put_principal_policy(self, policy: PrincipalPolicy, *, if_match: str | None) -> str:
        """Write ``policy`` and bump the head; returns the new principal ETag."""
        ...


def _check_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_LIST_LIMIT:
        raise InvalidSchemaError(
            "limit out of range",
            errors=[ValidationIssue("/limit", f"limit must be 1..{MAX_LIST_LIMIT}")],
            reason="limit_out_of_range",
        )
    return limit


def _stale() -> StaleVersionError:
    return StaleVersionError(
        "the policy document changed since it was read", reason="policy_modified"
    )


def _unavailable() -> DependencyTransientError:
    return DependencyTransientError("policy store unavailable", reason="policy_store_unavailable")


class InMemoryPolicyAdminRepository:
    """Twin of :class:`CosmosPolicyAdminRepository` over an :class:`InMemoryPolicyRepository`.

    Writes land in the wrapped read repository, so a deriver built on ``self.reader`` sees an
    accepted change after the head bump, exactly as derivation over Cosmos does. Tests and the
    local sandbox only; never a production store.
    """

    def __init__(
        self,
        reader: InMemoryPolicyRepository | None = None,
        *,
        etag_factory: Callable[[], str] | None = None,
    ) -> None:
        self.reader = reader if reader is not None else InMemoryPolicyRepository()
        self._etags: dict[tuple[str, str], str] = {}
        counter = count(1)
        self._next_etag = etag_factory or (lambda: f'"mem-{next(counter)}"')
        self.error: BaseException | None = None
        self.writes = 0

    def fail_with(self, error: BaseException | None) -> None:
        """Make every call raise ``error`` (outage simulation); ``None`` restores service."""
        self.error = error

    def _guard(self) -> None:
        if self.error is not None:
            raise self.error

    async def _current(self, customer_id: str, principal_id: str) -> PrincipalPolicy | None:
        # Read the underlying map directly: the reader's counters measure derivation reads.
        return self.reader._principals.get((customer_id, principal_id))  # pyright: ignore[reportPrivateUsage]

    async def get_with_etag(
        self, customer_id: str, principal_id: str
    ) -> tuple[PrincipalPolicy, str] | None:
        self._guard()
        doc = await self._current(customer_id, principal_id)
        if doc is None:
            return None
        key = (customer_id, principal_id)
        etag = self._etags.get(key)
        if etag is None:  # seeded through the reader directly: give it an ETag on first sight
            etag = self._etags[key] = self._next_etag()
        return doc, etag

    async def list_principals(
        self, customer_id: str, *, limit: int = DEFAULT_LIST_LIMIT
    ) -> builtins.list[PrincipalPolicy]:
        self._guard()
        _check_limit(limit)
        docs = [
            doc
            for (cust, _), doc in self.reader._principals.items()  # pyright: ignore[reportPrivateUsage]
            if cust == customer_id
        ]
        docs.sort(key=lambda d: d.id)
        return docs[:limit]

    async def put_principal_policy(self, policy: PrincipalPolicy, *, if_match: str | None) -> str:
        self._guard()
        key = (policy.customer_id, policy.principal_id)
        existing = await self._current(*key)
        if existing is None:
            if if_match is not None:
                raise _stale()
        else:
            current_etag = self._etags.get(key)
            if if_match is None or current_etag is None or if_match != current_etag:
                raise _stale()
        head = self.reader._heads.get(policy.customer_id)  # pyright: ignore[reportPrivateUsage]
        new_head = PolicyHead(
            customer_id=policy.customer_id,
            policy_version=next_policy_version(head.policy_version if head else None),
        )
        etag = self._next_etag()
        # Both writes or neither: nothing above this line mutated state.
        self.reader.put_principal(policy)
        self.reader.put_head(new_head)
        self._etags[key] = etag
        self.writes += 1
        return etag


def _strip_system_properties(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _validated(raw: Mapping[str, Any]) -> PrincipalPolicy:
    try:
        return PrincipalPolicy.model_validate(_strip_system_properties(raw))
    except ValidationError as exc:
        raise DependencyTransientError(
            "policy document failed validation",
            reason="policy_document_invalid",
            upstream_invalid=True,
        ) from exc


class CosmosPolicyAdminRepository:
    """:class:`PolicyAdminRepository` on the ``policy`` container (partition ``/customer_id``).

    The principal write and the head bump are one transactional batch in the customer's
    partition. The head is replaced under its own ETag (or created when absent), so two admins
    writing different principals at once cannot both bump from the same version: the loser's
    batch fails as a whole and is retried (head conflicts only, a bounded number of times). A
    principal precondition failure is never retried: it is ``stale_version`` to the caller.
    """

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls, client: CosmosClient, *, database: str, container: str = DEFAULT_POLICY_CONTAINER
    ) -> CosmosPolicyAdminRepository:
        return cls(client.get_database_client(database).get_container_client(container))

    async def _read_raw(self, item_id: str, customer_id: str) -> dict[str, Any] | None:
        try:
            return await self._container.read_item(item=item_id, partition_key=customer_id)
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            raise _unavailable() from exc

    async def get_with_etag(
        self, customer_id: str, principal_id: str
    ) -> tuple[PrincipalPolicy, str] | None:
        raw = await self._read_raw(principal_document_id(principal_id), customer_id)
        if raw is None:
            return None
        doc = _validated(raw)
        if doc.customer_id != customer_id or doc.principal_id != principal_id:
            raise DependencyTransientError(
                "policy document does not belong to the requested principal",
                reason="policy_document_invalid",
                upstream_invalid=True,
            )
        return doc, str(raw.get("_etag", ""))

    async def list_principals(
        self, customer_id: str, *, limit: int = DEFAULT_LIST_LIMIT
    ) -> builtins.list[PrincipalPolicy]:
        _check_limit(limit)
        sql = "SELECT TOP @limit * FROM c WHERE c.doc_type = @doc_type ORDER BY c.id ASC"
        params: builtins.list[dict[str, Any]] = [
            {"name": "@limit", "value": limit},
            {"name": "@doc_type", "value": _PRINCIPAL_DOC_TYPE},
        ]
        try:
            rows = [
                row
                async for row in self._container.query_items(
                    sql, parameters=params, partition_key=customer_id
                )
            ]
        except Exception as exc:
            raise _unavailable() from exc
        docs = [_validated(row) for row in rows]
        if any(d.customer_id != customer_id for d in docs):
            raise DependencyTransientError(
                "policy document partition mismatch",
                reason="policy_document_invalid",
                upstream_invalid=True,
            )
        return docs

    async def _head(self, customer_id: str) -> tuple[PolicyHead | None, str | None]:
        raw = await self._read_raw(POLICY_HEAD_ID, customer_id)
        if raw is None:
            return None, None
        try:
            head = PolicyHead.model_validate(_strip_system_properties(raw))
        except ValidationError as exc:
            raise DependencyTransientError(
                "policy head failed validation",
                reason="policy_document_invalid",
                upstream_invalid=True,
            ) from exc
        return head, str(raw.get("_etag", "")) or None

    def _operations(
        self,
        policy: PrincipalPolicy,
        if_match: str | None,
        head: PolicyHead,
        head_etag: str | None,
    ) -> Sequence[Any]:
        body = policy.model_dump(mode="json")
        head_body = head.model_dump(mode="json")
        principal_op: tuple[Any, ...] = (
            ("create", (body,))
            if if_match is None
            else ("replace", (policy.id, body), {"if_match_etag": if_match})
        )
        head_op: tuple[Any, ...] = (
            ("create", (head_body,))
            if head_etag is None
            else ("replace", (POLICY_HEAD_ID, head_body), {"if_match_etag": head_etag})
        )
        return [principal_op, head_op]

    async def put_principal_policy(self, policy: PrincipalPolicy, *, if_match: str | None) -> str:
        for _ in range(_HEAD_RETRIES):
            current, head_etag = await self._head(policy.customer_id)
            new_head = PolicyHead(
                customer_id=policy.customer_id,
                policy_version=next_policy_version(current.policy_version if current else None),
            )
            operations = self._operations(policy, if_match, new_head, head_etag)
            try:
                results = await self._container.execute_item_batch(
                    batch_operations=operations, partition_key=policy.customer_id
                )
            except CosmosBatchOperationError as exc:
                if exc.error_index == 0 and exc.status_code in (404, 409, 412):
                    raise _stale() from exc
                if exc.error_index == 1 and exc.status_code in (409, 412):
                    continue  # the head moved under us: re-read it and try again
                raise _unavailable() from exc
            except Exception as exc:
                raise _unavailable() from exc
            etag = str(results[0].get("eTag", "")) if results else ""
            if not etag:
                raise DependencyTransientError(
                    "policy store returned no ETag",
                    reason="policy_document_invalid",
                    upstream_invalid=True,
                )
            return etag
        raise StaleVersionError(
            "the policy head kept changing; retry the request", reason="policy_head_contended"
        )

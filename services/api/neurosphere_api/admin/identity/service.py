"""Identity admin policy operations: read, authorize, audit, write (PRP-39 item 3).

Order of checks for every write (mirrors ``actions/customer_control.py``; each refusal is a 403
recorded through the installed denial recorder, and nothing is written):

1. The route's ``require(policy.manage)`` (held in at least one domain): 401/403/503 as usual.
2. Path and body agree (``principal_id``, record id); else 422 ``path_body_mismatch``.
3. The target principal is in the actor's own cloud and customer; else 403
   ``cross_scope_target``.
4. The actor is not changing their own policy document; else 403
   ``self_modification_forbidden`` (Clarification 3, ASSUMPTION).
5. Concurrency: an existing document needs ``If-Match`` (missing -> 422 ``invalid_schema``
   reason ``precondition_required``; differing -> 409 ``stale_version``); a create must not send
   one. Checked before the domain checks so a stale client never learns more than "re-read".
6. Every domain the change NAMES (new and replaced/removed entries; for a grant, the domain that
   owns the resource) must be one where the actor holds ``policy.manage``; else 403
   ``target_out_of_scope``. A grant resource whose domain cannot be resolved for the actor is
   refused the same way.
7. Privileged changes (assigning or removing ``admin`` / ``security_auditor`` /
   ``interaction_investigator``, the core ``PRIVILEGED_ROLES``) and any change naming the
   customer-control domain need ``permits_customer_wide(actor, policy.manage)``; else 403
   ``customer_scope_required``.
8. An ``interaction_investigator`` assignment expiring more than 7 days from now is 422
   ``invalid_schema`` reason ``role_assignment_too_long`` (GD-16, PRP-104).
9. The pure change function (PRP-65) validates (privileged without expiry -> 422, past expiry ->
   422, cross-customer -> 403) and the write runs under the audit protocol: a ``before`` record
   on EVERY named domain's chain, the write (principal document plus ``PolicyHead`` bump in one
   batch), then an ``after`` record on every chain. A failed before-record aborts the write; a
   failed write appends a ``failed`` after-record and re-raises (``run_audited_mutation``).

Resource-scoped grants use ``policy.manage`` on the owning domain, never ``grant.write``
(Clarification 2). There is no bypass: no role, flag or header skips any step.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from fastapi import Request
from neurosphere_contracts.admin.v1.domain_membership_change import DomainMembershipChange
from neurosphere_contracts.admin.v1.principal_access_summary import PrincipalAccessSummary
from neurosphere_contracts.admin.v1.resource_grant_change import ResourceGrantChange
from neurosphere_contracts.admin.v1.role_assignment_change import RoleAssignmentChange
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    AuditRepository,
    build_after,
    build_before,
    domain_audit_chain_id,
    make_subject,
)
from neurosphere_core.auth.revocation import is_canonical_principal_id
from neurosphere_core.auth.scope import PRIVILEGED_ROLES as CORE_PRIVILEGED_ROLES
from neurosphere_core.auth.scope import (
    Permission,
    PrincipalPolicy,
    Role,
    customer_control_domain_id,
    domains_with_permission,
    permits_customer_wide,
)
from neurosphere_core.auth.scope.policy_admin import (
    MAX_LIST_LIMIT,
    PolicyAdminRepository,
    apply_grant_change,
    apply_membership_change,
    apply_role_change,
    remove_grant,
)
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
    NotFoundError,
    StaleVersionError,
    ValidationIssue,
)
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.common import audit_correlation_id
from neurosphere_api.admin.identity.models import (
    PrincipalPage,
    access_summary,
    revocation_status,
)
from neurosphere_api.admin.identity.plane import IdentityAdminPlane
from neurosphere_api.authz import AuthzState, DeniedAttempt
from neurosphere_api.middleware import correlation_id_of

__all__ = [
    "PRIVILEGED_ROLES",
    "IdentityAdminService",
    "PolicyWriteResult",
]

PRIVILEGED_ROLES: Final = frozenset(role.value for role in CORE_PRIVILEGED_ROLES)
_PERM: Final = Permission.POLICY_MANAGE
#: GD-16 (PRP-104 clarification 8): an investigator assignment lasts at most 7 days.
MAX_INVESTIGATOR_ASSIGNMENT: Final = timedelta(days=7)

OP_ROLE_ASSIGN: Final = "policy.role_assign"
OP_ROLE_REMOVE: Final = "policy.role_remove"
OP_MEMBERSHIP_ADD: Final = "policy.membership_add"
OP_MEMBERSHIP_REMOVE: Final = "policy.membership_remove"
OP_GRANT_PUT: Final = "policy.grant_put"
OP_GRANT_REMOVE: Final = "policy.grant_remove"


@dataclass(frozen=True, slots=True)
class PolicyWriteResult:
    summary: PrincipalAccessSummary
    etag: str


def _mismatch(pointer: str) -> InvalidSchemaError:
    return InvalidSchemaError(
        "the request body does not match the path",
        errors=[ValidationIssue(pointer, "must equal the value in the path")],
        reason="path_body_mismatch",
    )


def _precondition_required() -> InvalidSchemaError:
    return InvalidSchemaError(
        "If-Match is required to change an existing policy document",
        errors=[ValidationIssue("/headers/If-Match", "required")],
        reason="precondition_required",
    )


def _stale() -> StaleVersionError:
    return StaleVersionError(
        "the policy document changed since it was read", reason="policy_modified"
    )


def _principal_not_found() -> NotFoundError:
    return NotFoundError(
        "no such principal in the domains you manage", reason="principal_not_found"
    )


def _quoted(etag: str) -> str:
    return etag if etag.startswith('"') else f'"{etag}"'


def _same_etag(a: str, b: str) -> bool:
    return _quoted(a.strip()) == _quoted(b.strip())


class IdentityAdminService:
    """One request's view of the plane: actor, clock and denial recorder bound."""

    def __init__(
        self,
        plane: IdentityAdminPlane,
        state: AuthzState,
        request: Request,
        actor: IdentityScope,
    ) -> None:
        self._plane = plane
        self._state = state
        self._request = request
        self._actor = actor
        self._now = datetime.fromtimestamp(state.clock(), UTC)

    # ------------------------------------------------------------------ dependencies

    @property
    def now(self) -> datetime:
        return self._now

    def _policy_admin(self) -> PolicyAdminRepository:
        if self._plane.policy_admin is None:
            raise DependencyTransientError(
                "policy administration is not configured", reason="policy_admin_unconfigured"
            )
        return self._plane.policy_admin

    def _audit(self) -> AuditRepository:
        if self._plane.audit is None:
            raise DependencyTransientError(
                "audit store is not configured", reason="audit_store_unconfigured"
            )
        return self._plane.audit

    @property
    def _actor_id(self) -> str:
        return self._actor.to_contract().principal.principal_id.root

    def managed_domains(self) -> frozenset[str]:
        return domains_with_permission(self._actor, _PERM, now=self._now)

    # ------------------------------------------------------------------ denials

    async def _deny(
        self, reason: str, *, domain_id: str | None = None, message: str | None = None
    ) -> ForbiddenError:
        recorder = self._state.denial_recorder
        if recorder is not None:
            attempt = DeniedAttempt(
                scope=self._actor,
                permission=_PERM.value,
                reason=reason,
                method=self._request.method,
                path=self._request.url.path,
                domain_id=domain_id,
                resource_id=None,
                correlation_id=correlation_id_of(self._request.scope),
            )
            try:
                await recorder.record_denial(attempt)
            except Exception as exc:
                if self._request.method.upper() not in ("GET", "HEAD", "OPTIONS"):
                    raise DependencyTransientError(
                        "audit write failed", reason="audit_write_failed"
                    ) from exc
        return ForbiddenError(message or "insufficient scope for this operation", reason=reason)

    async def _check_target(self, principal_id: str) -> None:
        if not is_canonical_principal_id(principal_id):
            raise InvalidSchemaError(
                "invalid principal id",
                errors=[ValidationIssue("/principal_id", "must be a canonical principal id")],
            )
        cloud, customer = principal_id.split(":")[:2]
        if cloud != str(self._actor.cloud) or customer != self._actor.customer_id:
            raise await self._deny("cross_scope_target", message="target is outside your scope")

    async def _check_not_self(self, principal_id: str) -> None:
        if principal_id == self._actor_id:
            raise await self._deny(
                "self_modification_forbidden",
                message="administrators cannot change their own access",
            )

    async def _check_registered(self, domains: Iterable[str]) -> None:
        """PRP-44: a domain an ADD names must be registered once the registry holds a domain.

        Removals never call this (a retired domain's access can always be cleaned up). Without
        the platform plane, or while the registry is empty, behaviour is as before.
        """
        plane = getattr(self._request.app.state, "admin_platform", None)
        if plane is None:
            return
        missing = await plane.admin.registry.unregistered(
            self._actor.customer_id, sorted(set(domains))
        )
        if missing:
            raise InvalidSchemaError(
                "a named domain is not registered",
                errors=[ValidationIssue("/domain_ids", "domain is not registered")],
                reason="domain_not_registered",
            )

    async def _check_domains(self, domains: Iterable[str], *, privileged: bool) -> None:
        named = sorted(set(domains))
        managed = self.managed_domains()
        for domain in named:
            if domain not in managed:
                raise await self._deny("target_out_of_scope", domain_id=domain)
        control = customer_control_domain_id(str(self._actor.cloud), self._actor.customer_id)
        if (privileged or control in named) and not permits_customer_wide(
            self._actor, _PERM, now=self._now
        ):
            raise await self._deny(
                "customer_scope_required",
                domain_id=control,
                message="this change needs customer-level policy.manage",
            )

    def _check_investigator_window(self, change: RoleAssignmentChange) -> None:
        """GD-16: an ``interaction_investigator`` assignment ends at most 7 days from now.

        Refused like the other expiry rules (422 ``invalid_schema``); a missing expiry is left to
        the privileged-role rule in :func:`apply_role_change`.
        """
        if change.role is None or change.role.root != Role.INTERACTION_INVESTIGATOR.value:
            return
        if change.expires_at is None:
            return
        expires_at = datetime.fromisoformat(change.expires_at.root.replace("Z", "+00:00"))
        if expires_at - self._now > MAX_INVESTIGATOR_ASSIGNMENT:
            raise InvalidSchemaError(
                "an interaction investigator assignment may last at most 7 days",
                errors=[ValidationIssue("/expires_at", "expires_at must be within 7 days of now")],
                reason="role_assignment_too_long",
            )

    # ------------------------------------------------------------------ reads

    async def _load(self, principal_id: str) -> tuple[PrincipalPolicy, str] | None:
        return await self._policy_admin().get_with_etag(self._actor.customer_id, principal_id)

    async def _resource_domain(self, resource_id: str) -> str | None:
        resolver = self._plane.resource_domains
        if resolver is None:
            raise DependencyTransientError(
                "resource ownership cannot be resolved", reason="resource_domains_unavailable"
            )
        try:
            return await resolver.domain_of(self._actor, resource_id)
        except NeuroSphereError:
            raise
        except Exception as exc:
            raise DependencyTransientError(
                "resource ownership cannot be resolved", reason="resource_domains_unavailable"
            ) from exc

    async def _visible_grants(self, policy: PrincipalPolicy, managed: frozenset[str]) -> list[str]:
        if not policy.grants:
            return []
        if self._plane.resource_domains is None:
            return []  # without ownership data no grant can be shown as managed
        cache: dict[str, str | None] = {}
        visible: list[str] = []
        for grant in policy.grants:
            if grant.resource_id not in cache:
                cache[grant.resource_id] = await self._resource_domain(grant.resource_id)
            if cache[grant.resource_id] in managed:
                visible.append(grant.grant_id)
        return visible

    async def _policy_version(self) -> str | None:
        reader = self._plane.policy_reader
        if reader is None:
            return None
        head = await reader.get_policy_head(self._actor.customer_id)
        return None if head is None else head.policy_version

    async def _revocation(self, principal_id: str) -> Any:
        service = self._plane.revocation
        if service is None:
            raise DependencyTransientError(
                "revocation service is not configured", reason="revocation_service_unconfigured"
            )
        try:
            entry = await service.store.get(principal_id)
        except NeuroSphereError:
            raise
        except Exception as exc:
            raise DependencyTransientError(
                "revocation store unavailable", reason="revocation_store_unavailable"
            ) from exc
        return revocation_status(
            principal_id, entry, propagation_bound_seconds=service.propagation_bound_seconds
        )

    def _relevant(self, policy: PrincipalPolicy, managed: frozenset[str]) -> bool:
        if any(d in managed for d in policy.domain_memberships):
            return True
        return any(d in managed for a in policy.role_assignments for d in a.domain_ids)

    async def _summary(
        self, policy: PrincipalPolicy, managed: frozenset[str], version: str | None
    ) -> PrincipalAccessSummary:
        return access_summary(
            policy,
            cloud=str(self._actor.cloud),
            managed=managed,
            visible_grant_ids=await self._visible_grants(policy, managed),
            policy_version=version,
            revocation=await self._revocation(policy.principal_id),
            now=self._now,
        )

    async def list_principals(self, *, cursor: str | None, limit: int) -> PrincipalPage:
        if cursor is not None and not is_canonical_principal_id(cursor):
            raise InvalidSchemaError(
                "invalid cursor", errors=[ValidationIssue("/cursor", "not a principal id")]
            )
        managed = self.managed_domains()
        docs = await self._policy_admin().list_principals(
            self._actor.customer_id, limit=MAX_LIST_LIMIT
        )
        docs.sort(key=lambda d: d.principal_id)
        relevant = [
            d
            for d in docs
            if (cursor is None or d.principal_id > cursor) and self._relevant(d, managed)
        ]
        page = relevant[:limit]
        version = await self._policy_version()
        items = [await self._summary(d, managed, version) for d in page]
        more = len(relevant) > limit
        return PrincipalPage(
            items=items,
            next_cursor=page[-1].principal_id if more and page else None,
            truncated=len(docs) >= MAX_LIST_LIMIT,
        )

    async def get_principal(self, principal_id: str) -> PolicyWriteResult:
        await self._check_target(principal_id)
        found = await self._load(principal_id)
        managed = self.managed_domains()
        if found is None or not self._relevant(found[0], managed):
            raise _principal_not_found()
        policy, etag = found
        summary = await self._summary(policy, managed, await self._policy_version())
        return PolicyWriteResult(summary=summary, etag=etag)

    # ------------------------------------------------------------------ writes

    async def _precondition(
        self, found: tuple[PrincipalPolicy, str] | None, if_match: str | None
    ) -> tuple[PrincipalPolicy | None, str | None]:
        if found is None:
            if if_match is not None:
                raise _stale()  # a create must not claim a version that does not exist
            return None, None
        policy, etag = found
        if if_match is None:
            raise _precondition_required()
        if not _same_etag(if_match, etag):
            raise _stale()
        return policy, etag

    def _ctx(self, operation: str) -> AuditContext:
        return AuditContext.from_scope(
            self._actor,
            correlation_id=audit_correlation_id(correlation_id_of(self._request.scope)),
            operation=operation,
            channel="rest",
        )

    async def _write(
        self,
        operation: str,
        domains: Iterable[str],
        before: PrincipalPolicy | None,
        before_etag: str | None,
        after: PrincipalPolicy,
    ) -> str:
        """Audited write on every named domain's chain (module docstring, step 8)."""
        repository = self._audit()
        chains = sorted({domain_audit_chain_id(self._actor.customer_id, d) for d in domains})
        ctx = self._ctx(operation)
        entity_type = after.principal_id.split(":")[3]

        def subject(policy: PrincipalPolicy | None, version: str | None) -> Any:
            state = None if policy is None else policy.model_dump(mode="json")
            return make_subject(
                after.principal_id,
                entity_type,
                target_version=version,
                state=state if state is not None else {"exists": False},
            )

        before_draft = build_before(ctx, subject(before, before_etag))
        for chain in chains:
            await repository.append(chain, before_draft)
        try:
            etag = await self._policy_admin().put_principal_policy(after, if_match=before_etag)
        except Exception as exc:
            code = exc.code if isinstance(exc, NeuroSphereError) else "dependency_transient"
            failed: AuditDraft = build_after(
                ctx, subject(before, before_etag), result="failed", verified=False, detail=code
            )
            for chain in chains:
                await repository.append(chain, failed)
            raise
        # This replica drops its cached copies at once; other replicas see the bumped head within
        # the policy cache TTL (PRP-06 C14). Never raises; no session is closed.
        if self._plane.cache_hooks is not None:
            await self._plane.cache_hooks.invalidate_caches(after.principal_id)
        after_draft = build_after(ctx, subject(after, etag), result="succeeded", verified=True)
        for chain in chains:
            await repository.append(chain, after_draft)
        return etag

    async def _respond(self, policy: PrincipalPolicy, etag: str) -> PolicyWriteResult:
        managed = self.managed_domains()
        summary = await self._summary(policy, managed, await self._policy_version())
        return PolicyWriteResult(summary=summary, etag=etag)

    async def _prepare(
        self, principal_id: str, if_match: str | None
    ) -> tuple[PrincipalPolicy | None, str | None]:
        await self._check_target(principal_id)
        await self._check_not_self(principal_id)
        return await self._precondition(await self._load(principal_id), if_match)

    async def put_role(
        self,
        principal_id: str,
        assignment_id: str,
        change: RoleAssignmentChange,
        if_match: str | None,
    ) -> PolicyWriteResult:
        if change.principal_id.root != principal_id:
            raise _mismatch("/principal_id")
        if change.assignment_id.root != assignment_id:
            raise _mismatch("/assignment_id")
        if change.op != "assign":
            raise InvalidSchemaError(
                "PUT assigns; use DELETE to remove",
                errors=[ValidationIssue("/op", "must be assign")],
                reason="op_not_allowed",
            )
        current, etag = await self._prepare(principal_id, if_match)
        old = _assignment(current, assignment_id)
        domains = [d.root for d in change.domain_ids or ()]
        roles = {change.role.root} if change.role is not None else set()
        if old is not None:
            domains.extend(old.domain_ids)
            roles.add(old.role.value)
        await self._check_domains(domains, privileged=bool(roles & PRIVILEGED_ROLES))
        await self._check_registered(d.root for d in change.domain_ids or ())
        self._check_investigator_window(change)
        updated = apply_role_change(
            current, change, customer_id=self._actor.customer_id, now=self._now
        )
        new_etag = await self._write(OP_ROLE_ASSIGN, domains, current, etag, updated)
        return await self._respond(updated, new_etag)

    async def remove_role(
        self, principal_id: str, assignment_id: str, *, reason: str, if_match: str | None
    ) -> PolicyWriteResult:
        current, etag = await self._prepare(principal_id, if_match)
        old = _assignment(current, assignment_id)
        if current is None or old is None:
            raise NotFoundError("no such role assignment", reason="assignment_not_found")
        await self._check_domains(old.domain_ids, privileged=old.role.value in PRIVILEGED_ROLES)
        change = RoleAssignmentChange.model_validate(
            {
                "schema_version": "1.0.0",
                "op": "remove",
                "principal_id": principal_id,
                "assignment_id": assignment_id,
                "reason": reason,
            }
        )
        updated = apply_role_change(current, change, customer_id=self._actor.customer_id)
        new_etag = await self._write(OP_ROLE_REMOVE, old.domain_ids, current, etag, updated)
        return await self._respond(updated, new_etag)

    async def change_membership(
        self,
        principal_id: str,
        domain_id: str,
        change: DomainMembershipChange,
        if_match: str | None,
    ) -> PolicyWriteResult:
        if change.principal_id.root != principal_id:
            raise _mismatch("/principal_id")
        if change.domain_id.root != domain_id:
            raise _mismatch("/domain_id")
        current, etag = await self._prepare(principal_id, if_match)
        if change.op == "remove" and current is None:
            raise NotFoundError("no such domain membership", reason="membership_not_found")
        await self._check_domains([domain_id], privileged=False)
        if change.op == "add":
            await self._check_registered([domain_id])
        updated = apply_membership_change(current, change, customer_id=self._actor.customer_id)
        operation = OP_MEMBERSHIP_ADD if change.op == "add" else OP_MEMBERSHIP_REMOVE
        new_etag = await self._write(operation, [domain_id], current, etag, updated)
        return await self._respond(updated, new_etag)

    async def put_grant(
        self,
        principal_id: str,
        grant_id: str,
        change: ResourceGrantChange,
        if_match: str | None,
    ) -> PolicyWriteResult:
        if change.principal_id.root != principal_id:
            raise _mismatch("/principal_id")
        if change.grant_id.root != grant_id:
            raise _mismatch("/grant_id")
        current, etag = await self._prepare(principal_id, if_match)
        resources = [change.resource_id.root]
        old = _grant(current, grant_id)
        if old is not None and old.resource_id not in resources:
            resources.append(old.resource_id)
        domains = await self._owning_domains(resources)
        await self._check_domains(domains, privileged=False)
        await self._check_registered(domains[:1])  # the new resource's owning domain
        updated = apply_grant_change(
            current, change, customer_id=self._actor.customer_id, now=self._now
        )
        new_etag = await self._write(OP_GRANT_PUT, domains, current, etag, updated)
        return await self._respond(updated, new_etag)

    async def remove_grant(
        self, principal_id: str, grant_id: str, *, if_match: str | None
    ) -> PolicyWriteResult:
        current, etag = await self._prepare(principal_id, if_match)
        old = _grant(current, grant_id)
        if current is None or old is None:
            raise NotFoundError("no such grant", reason="grant_not_found")
        domains = await self._owning_domains([old.resource_id])
        await self._check_domains(domains, privileged=False)
        updated = remove_grant(current, grant_id, customer_id=self._actor.customer_id)
        new_etag = await self._write(OP_GRANT_REMOVE, domains, current, etag, updated)
        return await self._respond(updated, new_etag)

    async def _owning_domains(self, resources: Iterable[str]) -> list[str]:
        domains: list[str] = []
        for resource_id in resources:
            domain = await self._resource_domain(resource_id)
            if domain is None:
                # Not visible to the actor (or not in the catalog): never assumed managed.
                raise await self._deny("target_out_of_scope")
            domains.append(domain)
        return domains


def _assignment(policy: PrincipalPolicy | None, assignment_id: str) -> Any:
    if policy is None:
        return None
    return next((a for a in policy.role_assignments if a.assignment_id == assignment_id), None)


def _grant(policy: PrincipalPolicy | None, grant_id: str) -> Any:
    if policy is None:
        return None
    return next((g for g in policy.grants if g.grant_id == grant_id), None)

"""Fixed NS-08 role set, the documented role-to-permission map and scope permission checks.

Five roles exist and the set is closed (PRP-06 C6). Their names are the contract literals in
``RoleAssignment.role``. Each role is bound to explicit domains in the policy store; a role never
applies tenant-wide and there is no wildcard, superuser or bypass permission anywhere (C7).

=================  ====================================================================
Role               Permissions (within the domains the assignment names)
=================  ====================================================================
viewer             data.read, grant.read
analyst            viewer + data.export, report.create, action.propose
domain_steward     analyst + catalog.curate, action.approve, action.execute, grant.write
admin              data.read, config.manage, policy.manage, revocation.manage, grant.read,
                   grant.write
security_auditor   audit.read, evidence.read  (no data.read: auditors read evidence, not data)
=================  ====================================================================

"Pro" is an Analyst capability tier (C6), not a role: it confers nothing from the Admin row.
Admin manages configuration within its domains; it does not inherit Steward approval or
Auditor evidence permissions. ``grant.write`` is the one write both Admin and Domain Steward
hold (PRP-33 item 5): it is not admin-only, and Analyst and Viewer never hold it.

``grant.read`` / ``grant.write`` govern catalog Grant documents (gateway access grants of a
principal to a model API, deployment or MCP server; catalog/v1/grant.schema.json). They are
unrelated to resource-scoped grants (``GRANT_PERMISSIONS``), which add a contract permission
on exactly one named resource and never add a role or a domain.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractIdentityScope
from neurosphere_contracts.scope.v1.identity_scope import RoleAssignment

from neurosphere_core.scope import IdentityScope

__all__ = [
    "GRANT_PERMISSIONS",
    "PRIVILEGED_ROLES",
    "ROLE_PERMISSIONS",
    "GrantPermission",
    "Permission",
    "Role",
    "domains_with_permission",
    "permits",
    "role_permissions",
]

GrantPermission = Literal["read", "export", "propose_action", "approve", "execute"]


class Role(StrEnum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    DOMAIN_STEWARD = "domain_steward"
    ADMIN = "admin"
    SECURITY_AUDITOR = "security_auditor"


class Permission(StrEnum):
    DATA_READ = "data.read"
    DATA_EXPORT = "data.export"
    REPORT_CREATE = "report.create"
    ACTION_PROPOSE = "action.propose"
    ACTION_APPROVE = "action.approve"
    ACTION_EXECUTE = "action.execute"
    CATALOG_CURATE = "catalog.curate"
    CONFIG_MANAGE = "config.manage"
    POLICY_MANAGE = "policy.manage"
    REVOCATION_MANAGE = "revocation.manage"
    AUDIT_READ = "audit.read"
    EVIDENCE_READ = "evidence.read"
    GRANT_READ = "grant.read"
    GRANT_WRITE = "grant.write"


_VIEWER = frozenset({Permission.DATA_READ, Permission.GRANT_READ})
_ANALYST = _VIEWER | {Permission.DATA_EXPORT, Permission.REPORT_CREATE, Permission.ACTION_PROPOSE}
_STEWARD = _ANALYST | {
    Permission.CATALOG_CURATE,
    Permission.ACTION_APPROVE,
    Permission.ACTION_EXECUTE,
    Permission.GRANT_WRITE,
}
_ADMIN = frozenset(
    {
        Permission.DATA_READ,
        Permission.CONFIG_MANAGE,
        Permission.POLICY_MANAGE,
        Permission.REVOCATION_MANAGE,
        Permission.GRANT_READ,
        Permission.GRANT_WRITE,
    }
)
_AUDITOR = frozenset({Permission.AUDIT_READ, Permission.EVIDENCE_READ})

ROLE_PERMISSIONS: Final[Mapping[Role, frozenset[Permission]]] = MappingProxyType(
    {
        Role.VIEWER: _VIEWER,
        Role.ANALYST: _ANALYST,
        Role.DOMAIN_STEWARD: _STEWARD,
        Role.ADMIN: _ADMIN,
        Role.SECURITY_AUDITOR: _AUDITOR,
    }
)

#: Contract grant permission -> platform permission. Grants apply to one named resource only.
GRANT_PERMISSIONS: Final[Mapping[GrantPermission, Permission]] = MappingProxyType(
    {
        "read": Permission.DATA_READ,
        "export": Permission.DATA_EXPORT,
        "propose_action": Permission.ACTION_PROPOSE,
        "approve": Permission.ACTION_APPROVE,
        "execute": Permission.ACTION_EXECUTE,
    }
)

#: Roles whose assignments must be time-bound (contract RoleAssignment rule; C7).
PRIVILEGED_ROLES: Final = frozenset({Role.ADMIN, Role.SECURITY_AUDITOR})


def role_permissions(role: Role | str) -> frozenset[Permission]:
    """Permission set for ``role``. Unknown role names raise ``ValueError`` (closed set)."""
    return ROLE_PERMISSIONS[Role(role)]


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _role_active(assignment: RoleAssignment, now: datetime) -> bool:
    return assignment.expires_at is None or now < _parse_ts(assignment.expires_at.root)


def _contract(scope: IdentityScope) -> ContractIdentityScope:
    if not isinstance(scope, IdentityScope):
        raise TypeError("permission checks require a server-derived IdentityScope")
    return scope.to_contract()


def domains_with_permission(
    scope: IdentityScope, permission: Permission, *, now: datetime
) -> frozenset[str]:
    """Domain ids where an unexpired role assignment of ``scope`` confers ``permission``."""
    contract = _contract(scope)
    domains: set[str] = set()
    for assignment in contract.roles:
        if not _role_active(assignment, now):
            continue
        if permission in role_permissions(assignment.role):
            domains.update(d.root for d in assignment.domain_ids)
    if permission is Permission.DATA_READ:
        domains &= {d.root for d in contract.allowed_domains}
    return frozenset(domains)


def permits(
    scope: IdentityScope,
    permission: Permission,
    *,
    now: datetime,
    domain_id: str | None = None,
    resource_id: str | None = None,
) -> bool:
    """True when ``scope`` holds ``permission`` on the named domain or resource at ``now``.

    A target is required: there is no "anywhere" form, so a caller cannot accidentally ask a
    question whose answer authorizes every domain. Comparisons are exact string matches on
    canonical ids, which carry the cloud and customer segments, so a scope never matches a target
    in another cloud or customer.
    """
    if domain_id is None and resource_id is None:
        raise ValueError("permits() needs a domain_id or a resource_id")
    if domain_id is not None and domain_id in domains_with_permission(scope, permission, now=now):
        return True
    if resource_id is None:
        return False
    for grant in _contract(scope).allowed_resources:
        if grant.resource_id.root != resource_id:
            continue
        if grant.expires_at is not None and now >= _parse_ts(grant.expires_at.root):
            continue
        if any(GRANT_PERMISSIONS[p] is permission for p in grant.permissions):
            return True
    return False

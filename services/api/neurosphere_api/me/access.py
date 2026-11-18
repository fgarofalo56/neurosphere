"""The caller's own access, built from its derivation only (PRP-138 item 5, ``/api/v1/me/access``).

The derived ``IdentityScope`` lists role assignments without their ids, and a stored and a mapped
assignment may hold the same role. They are told apart by the derivation's ``claim_grants``, never
by order: the deriver adds exactly one scope role per applied grant, with the grant's role, its
sorted domain ids and the token expiry, and records the assignment id
``MAPPED_ASSIGNMENT_PREFIX + entry_id``. Each grant whose assignment id is in the derivation
claims one scope role with that exact (role, domains, expiry) signature; every unclaimed scope
role came from the policy store. Should a stored assignment carry the very same signature as a
mapped one, the two are identical rows and either labelling yields the same response.

The body carries counts and flags only: no domain id, claim value, group object id, mapping or
anything about another principal.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from neurosphere_core.auth.scope import (
    MAPPED_ASSIGNMENT_PREFIX,
    ClaimGrant,
    ScopeDerivation,
    customer_control_domain_id,
)

from neurosphere_api.me.models import AccessRoleView, AccessSource, MeAccess

__all__ = ["access_view"]

_SOURCES: Final[dict[str, AccessSource]] = {
    "roles": "entra_app_role",
    "groups": "entra_group",
}

_Signature = tuple[str, tuple[str, ...], datetime | None]


def _parse(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


def _grant_signature(grant: ClaimGrant) -> _Signature:
    return (grant.role.value, tuple(sorted(grant.domain_ids)), grant.expires_at)


def access_view(
    derivation: ScopeDerivation, *, mapping_configured: bool, groups_overage: bool
) -> MeAccess:
    """The ``/api/v1/me/access`` body for ``derivation`` (see the module docstring)."""
    scope = derivation.scope
    control = customer_control_domain_id(str(scope.cloud), scope.customer_id)
    mapped_ids = {
        a.removeprefix(MAPPED_ASSIGNMENT_PREFIX)
        for a in derivation.assignment_ids
        if a.startswith(MAPPED_ASSIGNMENT_PREFIX)
    }
    pending: dict[_Signature, list[ClaimGrant]] = {}
    for grant in derivation.claim_grants:
        if grant.entry_id in mapped_ids:
            pending.setdefault(_grant_signature(grant), []).append(grant)
    roles: list[AccessRoleView] = []
    for assignment in scope.to_contract().roles:
        domains = sorted(d.root for d in assignment.domain_ids)
        expiry = assignment.expires_at
        expires_at = None if expiry is None else expiry.root
        signature: _Signature = (str(assignment.role), tuple(domains), _parse(expires_at))
        matches = pending.get(signature)
        grant = matches.pop(0) if matches else None
        roles.append(
            AccessRoleView(
                role=str(assignment.role),
                source="policy_store" if grant is None else _SOURCES[grant.claim],
                mapping_entry_id=None if grant is None else grant.entry_id,
                domain_count=len(domains),
                customer_control=control in domains,
                expires_at=expires_at,
            )
        )
    return MeAccess(
        mapping_configured=mapping_configured, groups_overage=groups_overage, roles=roles
    )

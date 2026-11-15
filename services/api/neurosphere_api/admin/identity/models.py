"""Response models and view builders of the identity admin API (PRP-39 item 3).

Request bodies are the PRP-37 ``admin/v1`` contracts (``RoleAssignmentChange``,
``DomainMembershipChange``, ``ResourceGrantChange``, ``RevocationRequest``); responses are
``PrincipalAccessSummary`` / ``RevocationStatus`` plus :class:`PrincipalPage` for the list.

Every view is FILTERED to the domains the actor manages (``policy.manage``): memberships and
assignment domains outside them are dropped, an assignment left with no domain is dropped, and a
grant is shown only when its resource's owning domain is managed. Only pseudonymous canonical ids
appear; no name, e-mail, UPN or raw object id is ever read or returned (Clarification 7).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Final

from neurosphere_contracts.admin.v1.principal_access_summary import PrincipalAccessSummary
from neurosphere_contracts.admin.v1.revocation_status import RevocationStatus
from neurosphere_core.auth.revocation import RevocationEntry
from neurosphere_core.auth.scope import PrincipalPolicy
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ADMIN_SCHEMA_VERSION",
    "DEFAULT_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "PrincipalPage",
    "access_summary",
    "principal_kind",
    "revocation_status",
]

ADMIN_SCHEMA_VERSION: Final = "1.0.0"
DEFAULT_PAGE_LIMIT: Final = 50
MAX_PAGE_LIMIT: Final = 200
#: Reported when the customer has no policy head yet (matches the summary's version grammar).
NO_POLICY_VERSION: Final = "none"


class PrincipalPage(BaseModel):
    """One bounded page of principals the actor manages, ordered by principal id."""

    model_config = ConfigDict(extra="forbid")

    items: list[PrincipalAccessSummary] = Field(max_length=MAX_PAGE_LIMIT)
    next_cursor: str | None = None
    #: True when the store returned its maximum and more principals may exist beyond it.
    truncated: bool = False


def _ts(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def principal_kind(principal_id: str) -> str:
    return "user" if principal_id.split(":")[3] == "person" else "service_principal"


def revocation_status(
    principal_id: str, entry: RevocationEntry | None, *, propagation_bound_seconds: float
) -> RevocationStatus:
    bound = max(1, min(900, int(propagation_bound_seconds)))
    if entry is None:
        return RevocationStatus.model_validate(
            {
                "schema_version": ADMIN_SCHEMA_VERSION,
                "principal_id": principal_id,
                "revoked": False,
                "mode": None,
                "revoked_at": None,
                "reason": None,
                "revoked_by": None,
                "propagation_bound_seconds": bound,
            }
        )
    return RevocationStatus.model_validate(
        {
            "schema_version": ADMIN_SCHEMA_VERSION,
            "principal_id": principal_id,
            "revoked": True,
            "mode": entry.mode,
            "revoked_at": _ts(entry.revoked_at),
            "reason": entry.reason,
            "revoked_by": entry.revoked_by,
            "propagation_bound_seconds": bound,
        }
    )


def access_summary(
    policy: PrincipalPolicy,
    *,
    cloud: str,
    managed: frozenset[str],
    visible_grant_ids: Iterable[str],
    policy_version: str | None,
    revocation: RevocationStatus,
    now: datetime,
) -> PrincipalAccessSummary:
    """The stored policy of one principal, filtered to ``managed`` domains (module docstring)."""
    grant_ids = set(visible_grant_ids)
    assignments: list[dict[str, object]] = []
    for assignment in policy.role_assignments:
        domains = [d for d in assignment.domain_ids if d in managed]
        if not domains:
            continue
        assignments.append(
            {
                "assignment_id": assignment.assignment_id,
                "role": assignment.role.value,
                "domain_ids": domains,
                "expires_at": None if assignment.expires_at is None else _ts(assignment.expires_at),
                "reason": assignment.reason,
            }
        )
    grants = [
        {
            "grant_id": g.grant_id,
            "resource_id": g.resource_id,
            "permissions": list(g.permissions),
            "expires_at": _ts(g.expires_at),
            "reason": g.reason,
        }
        for g in policy.grants
        if g.grant_id in grant_ids
    ]
    return PrincipalAccessSummary.model_validate(
        {
            "schema_version": ADMIN_SCHEMA_VERSION,
            "principal": {
                "principal_id": policy.principal_id,
                "principal_kind": principal_kind(policy.principal_id),
            },
            "customer_id": policy.customer_id,
            "cloud": cloud,
            "policy_version": policy_version or NO_POLICY_VERSION,
            "memberships": [d for d in policy.domain_memberships if d in managed],
            "assignments": assignments,
            "grants": grants,
            "revocation": revocation.model_dump(mode="json"),
            "generated_at": _ts(now),
        }
    )

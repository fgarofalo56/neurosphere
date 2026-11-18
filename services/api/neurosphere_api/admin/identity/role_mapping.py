"""``GET /api/v1/admin/identity/role-mapping``: the effective Entra role mapping (PRP-138 item 5).

Read only. The mapping is deployment configuration (``NS_AUTH_ROLE_MAPPINGS``); nothing in the
product can change it, so this module has no write route. The route needs ``policy.manage`` on
the customer's control domain (:func:`~neurosphere_api.authz.require_deployment_admin`): a domain
administrator without the control domain gets 403 ``customer_scope_required``.

The body states the bound tenant and audience, the deployment cloud, and per entry its id, claim
kind, claim value, role, domain mode and control flag. Claim values are shown because the reader
administers the deployment that holds them in configuration; they are never shown to anyone else
(``/api/v1/me/access`` returns none).

Where the mapping comes from: the authz builder parses it and installs it on ``app.state`` under
:data:`CLAIM_ROLE_MAPPING_ATTRIBUTE` (the name of the ``CLAIM_ROLE_MAPPING`` shared key). With no
mapping and no claim mapping counters on ``app.state`` the mapping is off and the answer is
``active: false``. When the counters show a configured mapping but the parsed mapping itself is
not reachable, the route answers 503 ``role_mapping_unavailable`` rather than claiming the
mapping is off.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Request
from neurosphere_core.auth.scope import ClaimRoleMapping, Permission
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.scope import IdentityScope
from pydantic import BaseModel, ConfigDict

from neurosphere_api.authz import claim_mapping_stats, require_deployment_admin

__all__ = [
    "CLAIM_ROLE_MAPPING_ATTRIBUTE",
    "ROLE_MAPPING_PATH",
    "RoleMappingEntryView",
    "RoleMappingView",
    "build_role_mapping_router",
    "claim_role_mapping_of",
    "mapping_configured",
    "role_mapping_view",
]

#: Path of the route, relative to the identity admin prefix.
ROLE_MAPPING_PATH: Final = "/role-mapping"
#: ``app.state`` attribute holding the parsed :class:`ClaimRoleMapping` (absent when off). Equals
#: the ``CLAIM_ROLE_MAPPING`` shared key's name (a test pins it).
CLAIM_ROLE_MAPPING_ATTRIBUTE: Final = "claim_role_mapping"

_DESCRIPTION: Final = (
    "The effective Entra claim to role mapping of this deployment, read only: the bound tenant, "
    "audience and cloud, and each entry's id, claim kind (`roles` or `groups`), claim value, "
    "role, domain mode (`all` or `explicit`) and customer control flag. `active` is false and "
    "`entries` empty when no mapping is configured. The mapping is deployment configuration "
    "(`NS_AUTH_ROLE_MAPPINGS`) and cannot be changed through the API. Needs `policy.manage` on "
    "the whole deployment (the customer control domain)."
)

_PolicyAdmin = Annotated[IdentityScope, Depends(require_deployment_admin(Permission.POLICY_MANAGE))]


class RoleMappingEntryView(BaseModel):
    """One mapping entry as configured."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    claim: Literal["roles", "groups"]
    value: str
    role: str
    domain_mode: Literal["all", "explicit"]
    #: Empty for ``all``; the configured list for ``explicit``.
    domain_ids: list[str]
    customer_control: bool


class RoleMappingView(BaseModel):
    """``GET /api/v1/admin/identity/role-mapping`` body."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    active: bool
    tenant_id: str | None
    audience: str | None
    cloud: Literal["commercial", "government"]
    entries: list[RoleMappingEntryView]


def claim_role_mapping_of(app_state: object) -> ClaimRoleMapping | None:
    """The parsed mapping installed on ``app_state``, or ``None`` (mapping off or not installed)."""
    mapping = getattr(app_state, CLAIM_ROLE_MAPPING_ATTRIBUTE, None)
    return mapping if isinstance(mapping, ClaimRoleMapping) else None


def mapping_configured(app_state: object) -> bool:
    """True when the deployment has a claim role mapping (the parsed mapping or its counters)."""
    return (
        claim_role_mapping_of(app_state) is not None or claim_mapping_stats(app_state) is not None
    )


def role_mapping_view(
    mapping: ClaimRoleMapping | None, cloud: Literal["commercial", "government"]
) -> RoleMappingView:
    """The response body for ``mapping`` (``None`` means off) in the deployment ``cloud``."""
    if mapping is None:
        return RoleMappingView(active=False, tenant_id=None, audience=None, cloud=cloud, entries=[])
    entries = [
        RoleMappingEntryView(
            id=entry.id,
            claim=entry.claim,
            value=entry.value,
            role=entry.role.value,
            domain_mode="all" if entry.domains == "all" else "explicit",
            domain_ids=[] if entry.domains == "all" else list(entry.domains),
            customer_control=entry.customer_control,
        )
        for entry in mapping.entries
    ]
    return RoleMappingView(
        active=True,
        tenant_id=mapping.tenant_id,
        audience=mapping.audience,
        cloud=cloud,
        entries=entries,
    )


def build_role_mapping_router() -> APIRouter:
    router = APIRouter(tags=["admin-identity"])

    @router.get(ROLE_MAPPING_PATH, response_model=RoleMappingView, description=_DESCRIPTION)
    async def get_role_mapping(request: Request, scope: _PolicyAdmin) -> RoleMappingView:
        state = request.app.state
        mapping = claim_role_mapping_of(state)
        if mapping is None and claim_mapping_stats(state) is not None:
            raise DependencyTransientError(
                "the configured role mapping is not available", reason="role_mapping_unavailable"
            )
        cloud: Literal["commercial", "government"] = (
            "government" if str(scope.cloud) == "government" else "commercial"
        )
        return role_mapping_view(mapping, cloud)

    return router

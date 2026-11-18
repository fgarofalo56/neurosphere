"""Response models for ``GET /api/v1/me/domains`` (PRP-28 item 1) and ``GET /api/v1/me/access``
(PRP-138 item 5)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["AccessRoleView", "AccessSource", "DomainView", "MeAccess", "MeDomains"]

#: Where a role in the caller's own access came from (PRP-138).
AccessSource = Literal["entra_app_role", "entra_group", "policy_store"]


class DomainView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_id: str
    display_name: str
    display_name_source: Literal["catalog", "derived"]
    cloud: Literal["commercial", "government"]
    permissions: list[str]


class MeDomains(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DomainView]


class AccessRoleView(BaseModel):
    """One role assignment of the caller's own derived scope. Counts and flags only: never a
    domain id, a claim value or a group object id."""

    model_config = ConfigDict(extra="forbid")

    role: str
    source: AccessSource
    #: The Entra mapping entry id of a mapped role; ``None`` for a policy store role.
    mapping_entry_id: str | None
    domain_count: int
    customer_control: bool
    expires_at: str | None


class MeAccess(BaseModel):
    """``GET /api/v1/me/access`` body: the caller's own roles and where they came from."""

    model_config = ConfigDict(extra="forbid")

    mapping_configured: bool
    groups_overage: bool
    roles: list[AccessRoleView]

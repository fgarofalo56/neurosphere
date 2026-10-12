"""Policy-store documents and the repository interface (PRP-06 C5).

The policy container is partitioned by ``customer_id`` and holds two document kinds:

* ``PolicyHead`` (id ``policy-head``): the customer's current ``policy_version``. Bumping it
  invalidates every cached principal document (the cache is keyed by version, C14).
* ``PrincipalPolicy`` (id ``principal.<pseudonym>``): one principal's role assignments,
  resource-scoped grants (expiry and reason required) and domain memberships.

Entra group and app-role claims are inputs at most, never authority: nothing here reads them.

Repository contract: a missing document returns ``None`` (deny: no grants). Any store failure
raises ``DependencyTransientError``; a malformed document raises it with ``upstream_invalid``
(502). Neither is ever converted to an empty policy.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal, Protocol, Self, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from neurosphere_core.auth.scope.permissions import PRIVILEGED_ROLES, GrantPermission, Role

__all__ = [
    "CANONICAL_ID_PATTERN",
    "NO_POLICY_VERSION",
    "POLICY_HEAD_ID",
    "CanonicalId",
    "PolicyGrant",
    "PolicyHead",
    "PolicyRepository",
    "PolicyRoleAssignment",
    "PrincipalPolicy",
    "principal_document_id",
]

CANONICAL_ID_PATTERN: Final = (
    r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$"
)
POLICY_HEAD_ID: Final = "policy-head"
#: ``policy_version`` reported when a customer has no policy head: no policy, so deny.
NO_POLICY_VERSION: Final = "none"

CanonicalId = Annotated[str, StringConstraints(pattern=CANONICAL_ID_PATTERN, max_length=512)]
CustomerId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9._-]{1,128}$")]
PolicyVersion = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._+-]{1,64}$")]
RecordId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,128}$")]


def principal_document_id(principal_id: str) -> str:
    """Cosmos id for a principal's policy document (the pseudonym segment; no raw ids)."""
    return "principal." + principal_id.rsplit(":", 1)[-1]


class _Doc(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PolicyHead(_Doc):
    id: Literal["policy-head"] = POLICY_HEAD_ID
    doc_type: Literal["policy_head"] = "policy_head"
    customer_id: CustomerId
    policy_version: PolicyVersion


class PolicyRoleAssignment(_Doc):
    assignment_id: RecordId
    role: Role
    domain_ids: tuple[CanonicalId, ...] = Field(min_length=1, max_length=1024)
    expires_at: AwareDatetime | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def _privileged_roles_are_time_bound(self) -> Self:
        if self.role in PRIVILEGED_ROLES and self.expires_at is None:
            raise ValueError(f"{self.role.value} assignments must carry expires_at (C7)")
        return self


class PolicyGrant(_Doc):
    """A custom resource-scoped permission: one named resource, time-bound, reason-bearing."""

    grant_id: RecordId
    resource_id: CanonicalId
    permissions: tuple[GrantPermission, ...] = Field(min_length=1, max_length=5)
    expires_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=512)


class PrincipalPolicy(_Doc):
    id: RecordId
    doc_type: Literal["principal_policy"] = "principal_policy"
    customer_id: CustomerId
    principal_id: CanonicalId
    domain_memberships: tuple[CanonicalId, ...] = Field(default=(), max_length=1024)
    role_assignments: tuple[PolicyRoleAssignment, ...] = Field(default=(), max_length=64)
    grants: tuple[PolicyGrant, ...] = Field(default=(), max_length=4096)

    @model_validator(mode="after")
    def _id_matches_principal(self) -> Self:
        if self.id != principal_document_id(self.principal_id):
            raise ValueError("document id does not match principal_id")
        return self


@runtime_checkable
class PolicyRepository(Protocol):
    """Read side of the policy store. Writes belong to the (audited) admin path."""

    async def get_policy_head(self, customer_id: str) -> PolicyHead | None: ...

    async def get_principal_policy(
        self, customer_id: str, principal_id: str
    ) -> PrincipalPolicy | None: ...

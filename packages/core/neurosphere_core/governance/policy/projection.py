"""Catalog projection of published policies (PRP-105 item 3, acceptance criterion 9).

Each published policy appears in the catalog as the ``Policy`` entity
``<cloud>:<customer>:neurosphere:policy:<policy_id>`` so it shows in lineage. The write goes
through the shipped :class:`~neurosphere_core.catalog.protocol.CatalogRepository` under the
CALLER's derived scope (the worker's or the publishing handler's); nothing here widens a scope,
and a domain the scope cannot write is a refusal, not a bypass.

Mapping: ``mode`` ``off`` -> ``enforcement: disabled``, ``audit`` -> ``advisory``,
``enforce`` -> ``enforced``; ``policy_version`` is the version number as text; ``policy_kind``
follows the rule kinds (one family -> that family, mixed -> ``other``); ``document_ref`` is the
``governance_policy`` canonical id; ``effective_from`` is ``published_at``. Retire sets the entity
``deprecated`` (a lifecycle state: the document and its edges stay).

A projection failure never fails a publish or a run: :func:`project_policy` returns a
:class:`ProjectionResult` with a reason code and the next evaluation tick projects again (the
write is idempotent: an entity that already says the same thing is left alone).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal

from neurosphere_contracts.catalog.v1.policy import Policy as CatalogPolicy

from neurosphere_core.catalog.protocol import CatalogEntity, CatalogRepository
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    RateLimitedError,
    StaleVersionError,
)
from neurosphere_core.governance.policy.ids import (
    governance_policy_canonical_id,
    policy_entity_canonical_id,
)
from neurosphere_core.governance.policy.models import PolicyDefinition
from neurosphere_core.scope import IdentityScope

__all__ = [
    "ENFORCEMENT_BY_MODE",
    "POLICY_KIND_BY_RULE_KIND",
    "PROJECTION_CONFLICT",
    "PROJECTION_FAILED",
    "PROJECTION_INVALID",
    "PROJECTION_OUT_OF_SCOPE",
    "PROJECTION_STORE_UNAVAILABLE",
    "ProjectionAction",
    "ProjectionResult",
    "deprecate_policy_entity",
    "policy_entity",
    "project_policy",
]

#: Policy ``mode`` -> catalog ``enforcement`` (acceptance criterion 9).
ENFORCEMENT_BY_MODE: Final[Mapping[str, str]] = {
    "off": "disabled",
    "audit": "advisory",
    "enforce": "enforced",
}
#: Rule kind -> catalog ``policy_kind`` family.
POLICY_KIND_BY_RULE_KIND: Final[Mapping[str, str]] = {
    "model_allow_list": "model_usage",
    "data_sensitivity_access": "data_handling",
    "residency": "data_handling",
    "budget": "cost",
    "required_owner": "other",
    "required_attestation": "approval",
    "required_approval": "approval",
    "content_rule": "data_handling",
    "registration_required": "approval",
}

PROJECTION_OUT_OF_SCOPE: Final = "projection_out_of_scope"
PROJECTION_CONFLICT: Final = "projection_conflict"
PROJECTION_INVALID: Final = "projection_invalid"
PROJECTION_STORE_UNAVAILABLE: Final = "projection_store_unavailable"
PROJECTION_FAILED: Final = "projection_failed"

ProjectionAction = Literal["created", "updated", "deprecated", "unchanged", "failed"]

_COMPARED: Final = (
    "display_name",
    "policy_kind",
    "policy_version",
    "enforcement",
    "lifecycle_status",
    "effective_from",
    "document_ref",
)

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """What a projection did; ``reason_code`` names a failure (``None`` on success)."""

    entity_id: str
    action: ProjectionAction
    reason_code: str | None = None

    @property
    def ok(self) -> bool:
        return self.action != "failed"


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _policy_kind(policy: PolicyDefinition) -> str:
    families = {POLICY_KIND_BY_RULE_KIND.get(rule.kind.root, "other") for rule in policy.rules}
    return families.pop() if len(families) == 1 else "other"


def _mode(policy: PolicyDefinition) -> str:
    return policy.mode.root if policy.mode is not None else "audit"


def policy_entity(
    policy: PolicyDefinition,
    *,
    now: datetime,
    lifecycle_status: Literal["active", "deprecated"] = "active",
    existing: CatalogEntity | None = None,
) -> CatalogPolicy:
    """The catalog ``Policy`` document for ``policy`` (``existing`` keeps its server fields)."""
    cloud, customer, policy_id = policy.cloud.root, policy.customer_id.root, policy.policy_id.root
    stamp = _timestamp(now)
    published_at = policy.published_at.root if policy.published_at is not None else stamp
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "id": policy_entity_canonical_id(cloud, customer, policy_id),
        "entity_type": "policy",
        "version": 1,
        "etag": "projection",
        "lifecycle_status": lifecycle_status,
        "created_at": stamp,
        "updated_at": stamp,
        "cloud": cloud,
        "customer_id": customer,
        "domain_id": policy.domain_id.root,
        "classification": "internal",
        "display_name": policy.display_name.root,
        "policy_kind": _policy_kind(policy),
        "policy_version": str(policy.policy_version),
        "enforcement": ENFORCEMENT_BY_MODE[_mode(policy)],
        "effective_from": published_at,
        "effective_to": None,
        "document_ref": governance_policy_canonical_id(cloud, customer, policy_id),
    }
    if existing is not None:
        current = existing.model_dump(mode="json")
        for field in ("version", "etag", "created_at", "classification", "attributes"):
            if field in current:
                body[field] = current[field]
    return CatalogPolicy.model_validate(body)


def _same(existing: CatalogEntity, desired: CatalogPolicy) -> bool:
    current = existing.model_dump(mode="json")
    wanted = desired.model_dump(mode="json")
    return all(current.get(field) == wanted.get(field) for field in _COMPARED) and (
        current.get("domain_id") == wanted.get("domain_id")
    )


def _reason(exc: BaseException) -> str:
    if isinstance(exc, ForbiddenError):
        return PROJECTION_OUT_OF_SCOPE
    if isinstance(exc, StaleVersionError):
        return PROJECTION_CONFLICT
    if isinstance(exc, DependencyTransientError | RateLimitedError):
        return PROJECTION_STORE_UNAVAILABLE
    if isinstance(exc, InvalidSchemaError):
        return PROJECTION_INVALID
    return PROJECTION_FAILED


async def _guarded(
    entity_id: str, run: Callable[[], Awaitable[ProjectionResult]], *, policy_id: str
) -> ProjectionResult:
    try:
        return await run()
    except Exception as exc:  # never fails the publish or the run
        reason = _reason(exc)
        _log.warning("govpolicy_projection_failed policy_id=%s reason=%s", policy_id, reason)
        return ProjectionResult(entity_id=entity_id, action="failed", reason_code=reason)


async def project_policy(
    repository: CatalogRepository,
    scope: IdentityScope,
    policy: PolicyDefinition,
    *,
    now: datetime,
) -> ProjectionResult:
    """Create or bring up to date the catalog entity of a PUBLISHED ``policy``."""
    entity_id = policy_entity_canonical_id(
        policy.cloud.root, policy.customer_id.root, policy.policy_id.root
    )

    async def run() -> ProjectionResult:
        if policy.status != "published":
            raise InvalidSchemaError("only a published policy is projected active")
        existing = await repository.get_entity(scope, entity_id)
        if existing is None:
            await repository.create_entity(scope, policy_entity(policy, now=now))
            return ProjectionResult(entity_id=entity_id, action="created")
        desired = policy_entity(policy, now=now, existing=existing)
        if _same(existing, desired):
            return ProjectionResult(entity_id=entity_id, action="unchanged")
        etag = str(existing.model_dump(mode="json")["etag"])
        await repository.update_entity(scope, desired, etag)
        return ProjectionResult(entity_id=entity_id, action="updated")

    return await _guarded(entity_id, run, policy_id=policy.policy_id.root)


async def deprecate_policy_entity(
    repository: CatalogRepository,
    scope: IdentityScope,
    policy: PolicyDefinition,
    *,
    now: datetime,
) -> ProjectionResult:
    """Retire: the catalog entity of ``policy`` becomes ``deprecated`` (created so if absent)."""
    entity_id = policy_entity_canonical_id(
        policy.cloud.root, policy.customer_id.root, policy.policy_id.root
    )

    async def run() -> ProjectionResult:
        existing = await repository.get_entity(scope, entity_id)
        if existing is None:
            await repository.create_entity(
                scope, policy_entity(policy, now=now, lifecycle_status="deprecated")
            )
            return ProjectionResult(entity_id=entity_id, action="deprecated")
        current = existing.model_dump(mode="json")
        if current.get("lifecycle_status") == "deprecated":
            return ProjectionResult(entity_id=entity_id, action="unchanged")
        await repository.deprecate_entity(scope, entity_id, str(current["etag"]))
        return ProjectionResult(entity_id=entity_id, action="deprecated")

    return await _guarded(entity_id, run, policy_id=policy.policy_id.root)

"""Plan approval: the server-side record an apply is checked against (PRP-08 item 12).

A plan is approved once by a ``config.manage`` holder who supplies the plan and its target. The
server hashes exactly what it was given (:func:`plan_hash`), derives the executable resource list
(:func:`derive_resources`) and stores both digests. Apply refuses a plan with no live approval or
whose hash differs, and the executor's connector re-checks the same record at execution time
through :class:`~neurosphere_workers.actions.deploy.PlanApprovals` (``get``).

In-memory and per process, like the scan store: wire a durable implementation of
``PlanApprovals`` for a worker running in another process (open item recorded in the PRP). The
planner does not sign or persist plans, so the approval attests to the approver's input, not to
planner provenance.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from neurosphere_contracts.deployment.v1.deploy_action_plan import ResourceSpec
from neurosphere_core.audit.canonical import sha256_digest
from neurosphere_core.errors import ForbiddenError, InvalidSchemaError
from neurosphere_core.scope import IdentityScope
from neurosphere_workers.actions.deploy import ApprovedPlan, resources_digest

from neurosphere_api.deploy.apply.models import DEPLOYMENT_ID_PATTERN, ApplyTarget
from neurosphere_api.deploy.plan.models import DeploymentPlan

__all__ = [
    "DEFAULT_APPROVAL_TTL_SECONDS",
    "ApprovalRecord",
    "PlanApprovalStore",
    "derive_resources",
    "plan_hash",
]

DEFAULT_APPROVAL_TTL_SECONDS: Final = 24 * 3600
_MAX_ENTRIES: Final = 1000
_DEPLOYMENT_ID: Final = re.compile(DEPLOYMENT_ID_PATTERN)
_FABRIC_SERVICE: Final = "analytics_workspace"
_NAME_LIMIT: Final = 63


def plan_hash(plan: DeploymentPlan) -> str:
    """SHA-256 over the canonical JSON of the plan exactly as approved."""
    return sha256_digest(plan.model_dump(mode="json"))


def _tail(resource_id: str) -> str:
    return resource_id.rstrip("/").rsplit("/", 1)[-1]


def _bounded(name: str) -> str:
    return name[:_NAME_LIMIT]


def derive_resources(plan: DeploymentPlan, target: ApplyTarget) -> list[ResourceSpec]:
    """The executable resource list of ``plan``; refuses anything unresolved (fail closed).

    ``needs_consent`` items, failed checks on a create, a reuse without its id and consent, and a
    target region outside the plan profile all refuse the whole plan. ``skip``/``disabled`` items
    and plan-only ``feature`` items produce nothing.
    """
    if not _DEPLOYMENT_ID.fullmatch(plan.deployment_id):
        raise InvalidSchemaError("invalid deployment id", reason="invalid_deployment_id")
    if target.region not in plan.profile.regions:
        raise InvalidSchemaError(
            "the target region is not a region of the plan profile", reason="region_not_in_plan"
        )
    specs: list[ResourceSpec] = []
    for item in plan.items:
        if item.kind != "service" or item.status in ("skip", "disabled"):
            continue
        if item.status == "needs_consent":
            raise InvalidSchemaError(
                "the plan has items waiting for owner consent", reason="plan_has_unresolved_items"
            )
        if item.status == "reuse":
            consent = item.owner_consent.consent_id if item.owner_consent else None
            if not item.existing_resource_id or not consent:
                raise InvalidSchemaError(
                    "a reused resource needs its id and a recorded owner consent",
                    reason="reuse_without_consent",
                )
            specs.append(
                _spec(
                    item.service,
                    "arm_resource",
                    "reuse",
                    _tail(item.existing_resource_id),
                    target,
                    resource_id=item.existing_resource_id,
                    consent=consent,
                )
            )
            continue
        if any(check.outcome == "fail" for check in item.checks):
            raise InvalidSchemaError(
                "a create item has a failed check", reason="plan_has_failed_checks"
            )
        if item.service == _FABRIC_SERVICE and plan.profile.analytics == "fabric":
            token = re.sub(r"[^a-z0-9]", "", plan.deployment_id)
            specs.append(
                _spec(
                    item.service,
                    "fabric_capacity",
                    "create",
                    _bounded("nsf" + token),
                    target,
                    sku=target.capacity_sku,
                )
            )
            specs.append(
                _spec(
                    item.service,
                    "fabric_workspace",
                    "create",
                    _bounded(f"neurosphere-{plan.deployment_id}"),
                    target,
                )
            )
        else:
            specs.append(
                _spec(
                    item.service,
                    "arm_resource",
                    "create",
                    _bounded(f"{item.service}-{plan.deployment_id}"),
                    target,
                )
            )
    return specs


def _spec(
    service: str,
    kind: str,
    disposition: str,
    name: str,
    target: ApplyTarget,
    *,
    sku: str | None = None,
    resource_id: str | None = None,
    consent: str | None = None,
) -> ResourceSpec:
    reuse = disposition == "reuse"
    return ResourceSpec.model_validate(
        {
            "service": service,
            "kind": kind,
            "disposition": disposition,
            "name": name,
            "region": target.region,
            "sku": sku,
            "resource_id": resource_id,
            "subscription_id": None if reuse else target.subscription_id,
            "resource_group": None if reuse else target.resource_group,
            "consent_reference": consent,
        }
    )


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    approved: ApprovedPlan
    cloud: str
    resources: tuple[ResourceSpec, ...]
    #: Pseudonymous approver (never a real principal id).
    approver: str
    approved_at: datetime
    expires_at: datetime


class PlanApprovalStore:
    """In-memory approvals keyed by ``(customer, plan_id)``; implements ``PlanApprovals``."""

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_APPROVAL_TTL_SECONDS,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock
        self._records: dict[tuple[str, str], ApprovalRecord] = {}

    def approve(
        self, scope: IdentityScope, plan: DeploymentPlan, target: ApplyTarget
    ) -> ApprovalRecord:
        """Approve exactly ``plan``; a different plan under the same id is refused."""
        if plan.profile.cloud != scope.cloud:
            raise ForbiddenError("the plan is for another cloud", reason="cloud_mismatch")
        resources = tuple(derive_resources(plan, target))
        now = self._clock()
        key = (scope.customer_id, plan.plan_id)
        digest = plan_hash(plan)
        existing = self._records.get(key)
        if existing is not None and existing.expires_at > now:
            if existing.approved.plan_hash != digest:
                raise InvalidSchemaError(
                    "another plan was already approved under this plan id",
                    reason="plan_id_conflict",
                )
        while len(self._records) >= _MAX_ENTRIES:
            del self._records[next(iter(self._records))]
        record = ApprovalRecord(
            approved=ApprovedPlan(
                customer_id=scope.customer_id,
                plan_id=plan.plan_id,
                plan_hash=digest,
                resources_digest=resources_digest(resources),
                deployment_id=plan.deployment_id,
            ),
            cloud=plan.profile.cloud,
            resources=resources,
            approver=scope.to_contract().principal.principal_pseudonym,
            approved_at=now,
            expires_at=now + self._ttl,
        )
        self._records[key] = record
        return record

    def record(self, scope: IdentityScope, plan_id: str) -> ApprovalRecord:
        """The live approval for the caller's customer, or ``plan_not_approved`` (fail closed)."""
        found = self._records.get((scope.customer_id, plan_id))
        if found is None or found.expires_at <= self._clock():
            raise ForbiddenError("the plan is not approved", reason="plan_not_approved")
        return found

    async def get(self, customer_id: str, plan_id: str) -> ApprovedPlan | None:
        found = self._records.get((customer_id, plan_id))
        if found is None or found.expires_at <= self._clock():
            return None
        return found.approved

"""The executor's read side of the durable plan approvals (PRP-55 item 4).

:class:`RepositoryPlanApprovals` adapts a core
:class:`~neurosphere_core.deploy.approvals.PlanApprovalRepository` (in production the Cosmos
``deploy_plan_approvals`` container the API writes) to the connector's
:class:`~neurosphere_workers.actions.deploy.PlanApprovals` protocol. Read-only: the worker never
approves. An absent or expired approval reads as ``None``, so the connector refuses
``plan_not_approved`` and provisions nothing.
"""

from __future__ import annotations

from neurosphere_core.deploy.approvals import PlanApprovalRepository

from neurosphere_workers.actions.deploy import ApprovedPlan

__all__ = ["RepositoryPlanApprovals"]


class RepositoryPlanApprovals:
    """``PlanApprovals`` over a durable repository (shared with the API process)."""

    def __init__(self, repository: PlanApprovalRepository) -> None:
        self._repository = repository

    async def get(self, customer_id: str, plan_id: str) -> ApprovedPlan | None:
        found = await self._repository.get(customer_id, plan_id)
        if found is None:
            return None
        return ApprovedPlan(
            customer_id=found.customer_id,
            plan_id=found.plan_id,
            plan_hash=found.plan_hash,
            resources_digest=found.resources_digest,
            deployment_id=found.deployment_id,
        )

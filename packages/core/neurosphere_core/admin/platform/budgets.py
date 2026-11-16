"""Budget administration over the ``admin_config`` store (PRP-44 item 1).

A budget is an ``admin_config`` document of kind ``budget`` whose id is the ``budget_id``. On top
of the contract and the PRP-65 rules (decimal-string amount, thresholds strictly ascending) it
requires the named domain to be registered and every threshold percentage to be 1 to 200.

Stored only: nothing evaluates a budget against spend or sends an alert (clarification 6).
Nothing here logs.
"""

from __future__ import annotations

import builtins
from typing import Final

from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_contracts.admin.v1.budget import SpendBudget

from neurosphere_core.admin.platform.domains import DomainRegistry
from neurosphere_core.admin.store import DEFAULT_LIST_LIMIT, AdminConfigRepository
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue

__all__ = ["BUDGET_KIND", "MAX_THRESHOLD_PERCENT", "BudgetAdmin"]

BUDGET_KIND: Final = "budget"
MAX_THRESHOLD_PERCENT: Final = 200


def _issue(pointer: str, detail: str, reason: str) -> InvalidSchemaError:
    return InvalidSchemaError(
        "budget is invalid", errors=[ValidationIssue(pointer, detail)], reason=reason
    )


class BudgetAdmin:
    """Create, replace, retire (delete), get and list budgets."""

    def __init__(self, repository: AdminConfigRepository, domains: DomainRegistry) -> None:
        self._repository = repository
        self._domains = domains

    async def _check(self, customer_id: str, body: SpendBudget) -> None:
        for index, threshold in enumerate(body.thresholds_percent):
            if threshold.root > MAX_THRESHOLD_PERCENT:
                raise _issue(
                    f"/thresholds_percent/{index}",
                    f"threshold must be 1..{MAX_THRESHOLD_PERCENT}",
                    "budget_threshold_out_of_range",
                )
        if not await self._domains.is_registered(customer_id, body.domain_id.root):
            raise _issue("/domain_id", "domain is not registered", "domain_not_registered")

    async def create(
        self, customer_id: str, body: SpendBudget, *, updated_by: str
    ) -> AdminConfigDocument:
        await self._check(customer_id, body)
        return await self._repository.create(
            customer_id, BUDGET_KIND, body.budget_id.root, body, updated_by=updated_by
        )

    async def replace(
        self,
        customer_id: str,
        budget_id: str,
        body: SpendBudget,
        *,
        if_match: str,
        updated_by: str,
    ) -> AdminConfigDocument:
        if body.budget_id.root != budget_id:
            raise _issue("/budget_id", "budget_id differs from the path", "budget_id_mismatch")
        await self._check(customer_id, body)
        return await self._repository.replace(
            customer_id, BUDGET_KIND, budget_id, body, if_match=if_match, updated_by=updated_by
        )

    async def retire(
        self, customer_id: str, budget_id: str, *, if_match: str, updated_by: str
    ) -> AdminConfigDocument:
        return await self._repository.retire(
            customer_id, BUDGET_KIND, budget_id, if_match=if_match, updated_by=updated_by
        )

    async def get(self, customer_id: str, budget_id: str) -> AdminConfigDocument | None:
        return await self._repository.get(customer_id, BUDGET_KIND, budget_id)

    async def list(
        self,
        customer_id: str,
        *,
        include_retired: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> builtins.list[AdminConfigDocument]:
        return await self._repository.list_by_kind(
            customer_id, BUDGET_KIND, include_retired=include_retired, limit=limit
        )

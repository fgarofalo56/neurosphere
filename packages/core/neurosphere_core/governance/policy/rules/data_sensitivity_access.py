"""``data_sensitivity_access``: sensitive data needs an approved agent version (PRP-105 item 2).

One PRP-73 ``AccessEngine.who_accesses`` question per evaluation: assets in the evaluated
domains whose effective sensitivity categories intersect the rule's, accessed in the rule's
mode. An accessor breaks the rule when ``allowed_when`` is ``exception_only`` (every access needs
an exception), or when it is ``agent_version_approved`` and the accessor is not an approved
agent version (an agent counts through its current version; any other accessor has no
approval). Unassessed assets (null or empty categories) are never a breach.

Evidence per accessor: the access edge and the asset. Categories: the matching sensitivity
category names. The engine's own bounds are lowered to what is left of the rule's budget, and a
truncated answer makes the outcome truncated.
"""

from __future__ import annotations

from typing import Final

from neurosphere_contracts.policy.v1.policy_definition import (
    DataSensitivityAccessParams,
    PolicyDefinition,
    PolicyRule,
)

from neurosphere_core.catalog.graph.access import (
    AccessBudget,
    AccessEngine,
    AccessQuery,
    AccessRow,
    AssetSummary,
)
from neurosphere_core.catalog.protocol import CatalogEntity, CatalogRepository
from neurosphere_core.governance.policy.rules.approval import APPROVED, subject_approval_state
from neurosphere_core.governance.policy.rules.base import (
    FindingEvidence,
    RuleContext,
    RuleOutcome,
    params_as,
    text_of,
)
from neurosphere_core.governance.policy.rules.scan import AppliesTo, FindingCollector

__all__ = ["KIND", "DataSensitivityAccessEvaluator"]

KIND: Final = "data_sensitivity_access"
_MODES: Final[dict[str, list[str]]] = {
    "read": ["read"],
    "write": ["write"],
    "read_or_write": ["read", "write"],
}


class DataSensitivityAccessEvaluator:
    """Evaluator of ``data_sensitivity_access`` over the PRP-73 access engine."""

    def __init__(self, catalog: CatalogRepository, access: AccessEngine) -> None:
        self._catalog = catalog
        self._access = access

    @property
    def kind(self) -> str:
        return KIND

    async def evaluate(
        self, ctx: RuleContext, policy: PolicyDefinition, rule: PolicyRule
    ) -> RuleOutcome:
        params = params_as(rule, DataSensitivityAccessParams, KIND)
        out = FindingCollector(KIND)
        if not ctx.domain_ids or ctx.budget.expired():
            return out.outcome(ctx)
        wanted = sorted({text_of(c) or "" for c in params.sensitivity_categories} - {""})
        remaining_ms = ctx.budget.remaining_ms
        if remaining_ms < 1:
            ctx.budget.mark("time_budget")
            return out.outcome(ctx)
        query = AccessQuery.model_validate(
            {
                "sensitivity_categories": wanted,
                "domain_ids": list(ctx.domain_ids),
                "modes": _MODES[params.access],
                "budget": AccessBudget(
                    max_assets=ctx.budget.remaining_subjects,
                    max_accessors=ctx.budget.remaining_subjects,
                    timeout_ms=remaining_ms,
                ),
            }
        )
        result = await self._access.who_accesses(ctx.scope, query)
        assets = {a.id: a for a in result.assets}
        applies = AppliesTo.of(rule)
        cache: dict[str, CatalogEntity | None] = {}
        states: dict[str, str] = {}
        for row in result.rows:
            if not ctx.budget.take():
                break
            accessor = await self._get(ctx, row.accessor_id, cache)
            if accessor is None or not applies.matches_entity(accessor):
                continue
            if params.allowed_when == "agent_version_approved":
                if accessor.id not in states:
                    states[accessor.id] = await subject_approval_state(self._catalog, ctx, accessor)
                if states[accessor.id] == APPROVED:
                    continue
            self._add(out, row, accessor, assets.get(row.asset_id), wanted)
        if result.truncated:
            timed_out = result.truncated_reason == "timeout_ms"
            ctx.budget.mark("time_budget" if timed_out else "source_truncated")
        return out.outcome(ctx)

    async def _get(
        self, ctx: RuleContext, entity_id: str, cache: dict[str, CatalogEntity | None]
    ) -> CatalogEntity | None:
        if entity_id not in cache:
            cache[entity_id] = await self._catalog.get_entity(ctx.scope, entity_id)
        return cache[entity_id]

    @staticmethod
    def _add(
        out: FindingCollector,
        row: AccessRow,
        accessor: CatalogEntity,
        asset: AssetSummary | None,
        wanted: list[str],
    ) -> None:
        held = set(asset.sensitivity_categories or []) if asset is not None else set()
        out.add(
            subject_id=accessor.id,
            subject_type=accessor.entity_type,
            domain_id=row.accessor_domain_id,
            evidence_class="sensitive_data_access",
            evidence=(
                FindingEvidence(kind="relation", ref=row.edge_id),
                FindingEvidence(kind="catalog_entity", ref=row.asset_id),
            ),
            counts={"access_edges": 1},
            categories=sorted(held & set(wanted)),
        )

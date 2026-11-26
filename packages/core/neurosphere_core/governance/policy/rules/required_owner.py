"""``required_owner``: the entity needs owners (PRP-105 item 2).

Subjects are the active entities of the evaluated domains whose type can carry an ``owned_by``
edge (narrowed by ``applies_to``). Owners are the targets of the entity's presented outgoing
``owned_by`` edges; with ``require_active_owner`` only an in-scope owner whose lifecycle status
is ``active`` counts. Fewer than ``min_owners`` breaks the rule. Evidence: the entity and any
owner edges it has. A node whose edge pages are cut short is skipped and the outcome truncated.
"""

from __future__ import annotations

from typing import Final

from neurosphere_contracts.policy.v1.policy_definition import (
    PolicyDefinition,
    PolicyRule,
    RequiredOwnerParams,
)

from neurosphere_core.catalog.protocol import CatalogRepository, EntityTypeName, PresentedEdge
from neurosphere_core.governance.policy.rules.base import (
    FindingEvidence,
    RuleContext,
    RuleOutcome,
    params_as,
    text_of,
)
from neurosphere_core.governance.policy.rules.scan import (
    AppliesTo,
    FindingCollector,
    iter_entities,
    node_edges,
)

__all__ = ["KIND", "OWNED_ENTITY_TYPES", "RequiredOwnerEvaluator"]

KIND: Final = "required_owner"
OWNED_ENTITY_TYPES: Final[tuple[EntityTypeName, ...]] = (
    "agent",
    "agent_version",
    "model_deployment",
    "grounding_source",
    "tool",
    "service",
)
"""Entity types an ``owned_by`` edge can start from (domains and policies are not checked)."""


class RequiredOwnerEvaluator:
    """Evaluator of ``required_owner`` over catalog ``owned_by`` edges."""

    def __init__(self, catalog: CatalogRepository) -> None:
        self._catalog = catalog

    @property
    def kind(self) -> str:
        return KIND

    async def evaluate(
        self, ctx: RuleContext, policy: PolicyDefinition, rule: PolicyRule
    ) -> RuleOutcome:
        params = params_as(rule, RequiredOwnerParams, KIND)
        min_owners = params.min_owners or 1
        active_only = params.require_active_owner is not False
        applies = AppliesTo.of(rule)
        types: list[EntityTypeName] = [t for t in OWNED_ENTITY_TYPES if applies.allows_type(t)]
        out = FindingCollector(KIND)
        owner_active: dict[str, bool] = {}
        async for entity in iter_entities(self._catalog, ctx, types):
            if not applies.matches_entity(entity):
                continue
            edges = await node_edges(self._catalog, ctx, entity.id, "out", "owned_by")
            if edges is None:
                break
            owners = await self._count(ctx, edges, active_only, owner_active)
            if owners >= min_owners:
                continue
            out.add(
                subject_id=entity.id,
                subject_type=entity.entity_type,
                domain_id=text_of(getattr(entity, "domain_id", None)),
                evidence_class="missing_owner",
                evidence=(
                    FindingEvidence(kind="catalog_entity", ref=entity.id),
                    *(FindingEvidence(kind="relation", ref=e.edge_id) for e in edges[:49]),
                ),
                counts={"owners": owners, "min_owners": min_owners},
            )
        return out.outcome(ctx)

    async def _count(
        self,
        ctx: RuleContext,
        edges: list[PresentedEdge],
        active_only: bool,
        owner_active: dict[str, bool],
    ) -> int:
        owners = {e.target_id for e in edges}
        if not active_only:
            return len(owners)
        count = 0
        for owner_id in sorted(owners):
            if owner_id not in owner_active:
                owner = await self._catalog.get_entity(ctx.scope, owner_id)
                owner_active[owner_id] = (
                    owner is not None and text_of(owner.lifecycle_status) == "active"
                )
            count += int(owner_active[owner_id])
        return count

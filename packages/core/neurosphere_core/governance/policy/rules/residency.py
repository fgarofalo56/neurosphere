"""``residency``: data and calls stay inside the allowed regions or geographies (PRP-105 item 2).

Subjects are the active grounding sources (``residency_region``, ``residency_geography``) and
model deployments (``residency_region``) of the evaluated domains, narrowed by ``applies_to``.
An asset complies when its region is in ``allowed_regions`` or its geography is in
``allowed_geographies``; it breaks the rule when a known value is outside a non-empty allowed
list and nothing complies. Unknown (null) values are unassessed, never a breach. Regions compare
case-insensitively.
"""

from __future__ import annotations

from typing import Final

from neurosphere_contracts.policy.v1.policy_definition import (
    PolicyDefinition,
    PolicyRule,
    ResidencyParams,
)

from neurosphere_core.catalog.protocol import CatalogEntity, CatalogRepository, EntityTypeName
from neurosphere_core.governance.policy.rules.base import (
    FindingEvidence,
    RuleContext,
    RuleOutcome,
    params_as,
    strings_of,
    text_of,
)
from neurosphere_core.governance.policy.rules.scan import AppliesTo, FindingCollector, iter_entities

__all__ = ["KIND", "RESIDENCY_ENTITY_TYPES", "ResidencyEvaluator", "residency_verdict"]

KIND: Final = "residency"
RESIDENCY_ENTITY_TYPES: Final[tuple[EntityTypeName, ...]] = ("grounding_source", "model_deployment")


def residency_verdict(
    region: str | None,
    geography: str | None,
    allowed_regions: frozenset[str],
    allowed_geographies: frozenset[str],
) -> bool | None:
    """True complies, False breaks the rule, None is unassessed."""
    region_ok = (region.lower() in allowed_regions) if region and allowed_regions else None
    geo_ok = (geography in allowed_geographies) if geography and allowed_geographies else None
    if region_ok or geo_ok:
        return True
    if region_ok is False or geo_ok is False:
        return False
    return None


class ResidencyEvaluator:
    """Evaluator of ``residency`` over catalog asset residency fields."""

    def __init__(self, catalog: CatalogRepository) -> None:
        self._catalog = catalog

    @property
    def kind(self) -> str:
        return KIND

    async def evaluate(
        self, ctx: RuleContext, policy: PolicyDefinition, rule: PolicyRule
    ) -> RuleOutcome:
        params = params_as(rule, ResidencyParams, KIND)
        regions = frozenset(r.lower() for r in strings_of(params.allowed_regions))
        geographies = frozenset(strings_of(params.allowed_geographies))
        applies = AppliesTo.of(rule)
        out = FindingCollector(KIND)
        types: list[EntityTypeName] = [t for t in RESIDENCY_ENTITY_TYPES if applies.allows_type(t)]
        if not (regions or geographies):
            return out.outcome(ctx)
        async for entity in iter_entities(self._catalog, ctx, types):
            if not applies.matches_entity(entity):
                continue
            region, geography = _residency(entity)
            if residency_verdict(region, geography, regions, geographies) is not False:
                continue
            out.add(
                subject_id=entity.id,
                subject_type=entity.entity_type,
                domain_id=text_of(getattr(entity, "domain_id", None)),
                evidence_class="residency",
                evidence=(FindingEvidence(kind="catalog_entity", ref=entity.id),),
            )
        return out.outcome(ctx)


def _residency(entity: CatalogEntity) -> tuple[str | None, str | None]:
    return (
        text_of(getattr(entity, "residency_region", None)),
        text_of(getattr(entity, "residency_geography", None)),
    )

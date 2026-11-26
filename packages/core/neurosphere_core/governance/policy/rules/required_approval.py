"""``required_approval``: an entity version needs an approval before it is active (PRP-105 item 2).

Subjects are the active agent versions of the evaluated domains (``entity_types`` defaults to
``agent_version``; other values are open-ended and have no approval record today, so they are
skipped). A version whose approval state is not ``approved`` (no record, ``pending``,
``rejected``, ``suspended``, ``not_required``) breaks the rule. Evidence: the version. Category:
the approval state name (``none`` when no record exists).
"""

from __future__ import annotations

from typing import Final

from neurosphere_contracts.catalog.v1.agent_version import AgentVersion
from neurosphere_contracts.policy.v1.policy_definition import (
    PolicyDefinition,
    PolicyRule,
    RequiredApprovalParams,
)

from neurosphere_core.catalog.protocol import CatalogRepository
from neurosphere_core.governance.policy.rules.approval import APPROVED, approval_state
from neurosphere_core.governance.policy.rules.base import (
    FindingEvidence,
    RuleContext,
    RuleOutcome,
    params_as,
    strings_of,
    text_of,
)
from neurosphere_core.governance.policy.rules.scan import AppliesTo, FindingCollector, iter_entities

__all__ = ["KIND", "RequiredApprovalEvaluator"]

KIND: Final = "required_approval"


class RequiredApprovalEvaluator:
    """Evaluator of ``required_approval`` over catalog agent versions."""

    def __init__(self, catalog: CatalogRepository) -> None:
        self._catalog = catalog

    @property
    def kind(self) -> str:
        return KIND

    async def evaluate(
        self, ctx: RuleContext, policy: PolicyDefinition, rule: PolicyRule
    ) -> RuleOutcome:
        params = params_as(rule, RequiredApprovalParams, KIND)
        out = FindingCollector(KIND)
        if "agent_version" not in strings_of(params.entity_types or ["agent_version"]):
            return out.outcome(ctx)
        applies = AppliesTo.of(rule)
        async for entity in iter_entities(self._catalog, ctx, ["agent_version"]):
            if not isinstance(entity, AgentVersion) or not applies.matches_entity(entity):
                continue
            state = approval_state(entity)
            if state == APPROVED:
                continue
            out.add(
                subject_id=entity.id,
                subject_type="agent_version",
                domain_id=text_of(entity.domain_id),
                evidence_class="approval_missing",
                evidence=(FindingEvidence(kind="catalog_entity", ref=entity.id),),
                categories=(state,),
            )
        return out.outcome(ctx)

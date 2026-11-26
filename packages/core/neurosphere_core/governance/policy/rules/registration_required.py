"""``registration_required``: entities seen in telemetry must be registered (PRP-105 item 2).

For ``agent`` in ``entity_types`` (the only type whose telemetry subjects carry a canonical id
today; other values are skipped):

* Unregistered agents: agent subject points (``agent:<canonical id>``) whose newest point lies
  before the grace cut-off (``now - grace_period_hours``, looking back ``POINT_LOOKBACK`` from
  there) and whose id the catalog does not return for the caller's scope. Evidence: the
  aggregate document id.
* Unregistered versions: active agent versions with no approval record at all (never submitted
  for approval) created before the grace cut-off. Evidence: the version. A version whose
  approval exists but is not ``approved`` is ``required_approval``'s business, not this rule's.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.catalog.v1.agent_version import AgentVersion
from neurosphere_contracts.policy.v1.policy_definition import (
    PolicyDefinition,
    PolicyRule,
    RegistrationRequiredParams,
)

from neurosphere_core.aggregates.models import AggregateWindow
from neurosphere_core.aggregates.subject import MAX_SUBJECT_KEYS_PER_READ, SubjectMetricsReader
from neurosphere_core.catalog import rules as catalog_rules
from neurosphere_core.catalog.protocol import CatalogRepository
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
    entity_type_of_id,
    iter_entities,
)

__all__ = ["KIND", "POINT_LOOKBACK", "RegistrationRequiredEvaluator"]

KIND: Final = "registration_required"
POINT_LOOKBACK: Final = timedelta(hours=24)


class RegistrationRequiredEvaluator:
    """Evaluator of ``registration_required`` over agent subject points and agent versions."""

    def __init__(self, catalog: CatalogRepository, metrics: SubjectMetricsReader) -> None:
        self._catalog = catalog
        self._metrics = metrics

    @property
    def kind(self) -> str:
        return KIND

    async def evaluate(
        self, ctx: RuleContext, policy: PolicyDefinition, rule: PolicyRule
    ) -> RuleOutcome:
        params = params_as(rule, RegistrationRequiredParams, KIND)
        out = FindingCollector(KIND)
        if "agent" not in params.entity_types:
            return out.outcome(ctx)
        grace = timedelta(hours=params.grace_period_hours or 0)
        applies = AppliesTo.of(rule)
        await self._points(ctx, grace, applies, out)
        await self._versions(ctx, grace, applies, out)
        return out.outcome(ctx)

    async def _points(
        self, ctx: RuleContext, grace: timedelta, applies: AppliesTo, out: FindingCollector
    ) -> None:
        cutoff = ctx.now - grace
        window = AggregateWindow(start=cutoff - POINT_LOOKBACK, end=cutoff)
        for domain_id in ctx.domain_ids:
            if ctx.budget.expired():
                return
            limit = min(ctx.budget.remaining_subjects, MAX_SUBJECT_KEYS_PER_READ)
            if limit < 1:
                ctx.budget.mark("subject_budget")
                return
            budget_bound = limit == ctx.budget.remaining_subjects
            lookup = await self._metrics.newest_subject_points(
                ctx.scope.customer_id, domain_id, window, limit
            )
            for key in sorted(lookup.points):
                point = lookup.points[key]
                if point.subject_kind != "agent":
                    continue
                if not ctx.budget.take():
                    return
                agent_id = point.subject_key.split(":", 1)[1]
                if entity_type_of_id(agent_id) != "agent":
                    continue
                if not applies.matches_unregistered(agent_id, "agent"):
                    continue
                if isinstance(await self._catalog.get_entity(ctx.scope, agent_id), Agent):
                    continue
                out.add(
                    subject_id=agent_id,
                    subject_type="agent",
                    domain_id=point.domain_id,
                    evidence_class="unregistered_agent",
                    evidence=(FindingEvidence(kind="aggregate_window", ref=point.id),),
                    counts={"events": point.event_count},
                )
            if lookup.truncated:
                ctx.budget.mark("subject_budget" if budget_bound else "source_truncated")
                return

    async def _versions(
        self, ctx: RuleContext, grace: timedelta, applies: AppliesTo, out: FindingCollector
    ) -> None:
        cutoff = ctx.now - grace
        if not (applies.allows_type("agent") or applies.allows_type("agent_version")):
            return
        async for entity in iter_entities(self._catalog, ctx, ["agent_version"]):
            if not isinstance(entity, AgentVersion) or entity.approval is not None:
                continue
            if catalog_rules.parse_timestamp(entity.created_at.root) > cutoff:
                continue
            if applies.entity_ids and not ({entity.id, entity.agent_id} & applies.entity_ids):
                continue
            out.add(
                subject_id=entity.id,
                subject_type="agent_version",
                domain_id=text_of(entity.domain_id),
                evidence_class="unregistered_version",
                evidence=(FindingEvidence(kind="catalog_entity", ref=entity.id),),
                categories=("none",),
            )

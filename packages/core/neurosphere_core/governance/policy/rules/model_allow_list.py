"""``model_allow_list``: only the listed models or deployments may be used (PRP-105 item 2).

Two sources, both bounded by the rule's budget:

* Catalog: every presented ``uses_model`` edge stored in the evaluated domains whose target
  deployment is neither an allowed deployment id nor an allowed model name (and version, when
  the entry names one). The subject is the edge's source (agent, agent version, tool, service);
  evidence is the edge and the deployment.
* Telemetry: model subject points (``model:<provider>/<model>``) of the last
  ``POINT_LOOKBACK`` whose model name is not allowed. A point carries no version, so an entry
  that pins a version still allows its name here (unknown is never a breach). A point has no
  catalog id; its subject is the telemetry model id from :func:`telemetry_model_id`.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Final

from neurosphere_contracts.catalog.v1.model_deployment import ModelDeployment
from neurosphere_contracts.policy.v1.policy_definition import (
    ModelAllowListParams,
    PolicyDefinition,
    PolicyRule,
)

from neurosphere_core.aggregates.models import AggregateWindow, SubjectPoint
from neurosphere_core.aggregates.subject import MAX_SUBJECT_KEYS_PER_READ, SubjectMetricsReader
from neurosphere_core.catalog.protocol import CatalogEntity, CatalogRepository
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
    iter_domain_edges,
)

__all__ = ["KIND", "POINT_LOOKBACK", "ModelAllowListEvaluator", "telemetry_model_id"]

KIND: Final = "model_allow_list"
POINT_LOOKBACK: Final = timedelta(hours=24)
_UNSAFE = r"[^a-z0-9._/=-]+"


def telemetry_model_id(cloud: str, customer_id: str, series_key: str) -> str:
    """``<cloud>:<customer>:telemetry:model:<provider>/<model>`` for a model subject point.

    Characters outside the canonical id grammar become ``-``. ASSUMPTION (PRP-105 item 2): the
    catalog has no entity for a model seen only in telemetry, so this id names it.
    """
    body = series_key.split(":", 1)[1] if ":" in series_key else series_key
    safe = re.sub(_UNSAFE, "-", body.lower()).strip("-/") or "unknown"
    return f"{cloud}:{customer_id}:telemetry:model:{safe}"


class _Allowed:
    def __init__(self, params: ModelAllowListParams) -> None:
        self.deployments = frozenset(text_of(d) or "" for d in params.allowed_deployment_ids or [])
        self.versions: dict[str, set[str | None]] = {}
        for entry in params.allowed_models or []:
            name = entry.model_name.strip().lower()
            self.versions.setdefault(name, set()).add(entry.model_version)
        self.deployment_names: set[str] = set()

    def allows_deployment(self, deployment: ModelDeployment) -> bool:
        if deployment.id in self.deployments:
            return True
        versions = self.versions.get(deployment.model_name.strip().lower())
        if versions is None:
            return False
        return None in versions or text_of(deployment.model_version) in versions

    def allows_name(self, model_name: str) -> bool:
        name = model_name.strip().lower()
        return name in self.versions or name in self.deployment_names


class ModelAllowListEvaluator:
    """Evaluator of ``model_allow_list`` over catalog ``uses_model`` edges and model points."""

    def __init__(self, catalog: CatalogRepository, metrics: SubjectMetricsReader) -> None:
        self._catalog = catalog
        self._metrics = metrics

    @property
    def kind(self) -> str:
        return KIND

    async def evaluate(
        self, ctx: RuleContext, policy: PolicyDefinition, rule: PolicyRule
    ) -> RuleOutcome:
        params = params_as(rule, ModelAllowListParams, KIND)
        allowed = _Allowed(params)
        applies = AppliesTo.of(rule)
        out = FindingCollector(KIND)
        cache: dict[str, CatalogEntity | None] = {}

        for deployment_id in sorted(allowed.deployments):
            found = await self._get(ctx, deployment_id, cache)
            if isinstance(found, ModelDeployment):
                allowed.deployment_names.add(found.model_name.strip().lower())

        async for edge in iter_domain_edges(self._catalog, ctx, "uses_model"):
            target = await self._get(ctx, edge.target_id, cache)
            if not isinstance(target, ModelDeployment) or allowed.allows_deployment(target):
                continue
            source = await self._get(ctx, edge.source_id, cache)
            if source is None or not applies.matches_entity(source):
                continue
            out.add(
                subject_id=source.id,
                subject_type=source.entity_type,
                domain_id=text_of(getattr(source, "domain_id", None)),
                evidence_class="uses_model",
                evidence=(
                    FindingEvidence(kind="relation", ref=edge.edge_id),
                    FindingEvidence(kind="catalog_entity", ref=target.id),
                ),
                counts={"disallowed_deployments": 1},
            )

        await self._points(ctx, allowed, applies, out)
        return out.outcome(ctx)

    async def _get(
        self, ctx: RuleContext, entity_id: str, cache: dict[str, CatalogEntity | None]
    ) -> CatalogEntity | None:
        if entity_id not in cache:
            cache[entity_id] = await self._catalog.get_entity(ctx.scope, entity_id)
        return cache[entity_id]

    async def _points(
        self, ctx: RuleContext, allowed: _Allowed, applies: AppliesTo, out: FindingCollector
    ) -> None:
        window = AggregateWindow(start=ctx.now - POINT_LOOKBACK, end=ctx.now)
        for domain_id in ctx.domain_ids:
            if ctx.budget.expired():
                return
            limit = min(ctx.budget.remaining_subjects, MAX_SUBJECT_KEYS_PER_READ)
            if limit < 1:
                ctx.budget.mark("subject_budget")
                return
            lookup = await self._metrics.newest_subject_points(
                ctx.scope.customer_id, domain_id, window, limit
            )
            budget_bound = limit == ctx.budget.remaining_subjects
            for key in sorted(lookup.points):
                point = lookup.points[key]
                if point.subject_kind != "model":
                    continue
                if not ctx.budget.take():
                    return
                self._check_point(ctx, point, allowed, applies, out)
            if lookup.truncated:
                ctx.budget.mark("subject_budget" if budget_bound else "source_truncated")
                return

    @staticmethod
    def _check_point(
        ctx: RuleContext,
        point: SubjectPoint,
        allowed: _Allowed,
        applies: AppliesTo,
        out: FindingCollector,
    ) -> None:
        body = point.subject_key.split(":", 1)[-1]
        model_name = body.split("/", 1)[-1]
        if allowed.allows_name(model_name):
            return
        subject_id = telemetry_model_id(ctx.scope.cloud, ctx.scope.customer_id, point.subject_key)
        if not applies.matches_unregistered(subject_id, entity_type_of_id(subject_id)):
            return
        out.add(
            subject_id=subject_id,
            subject_type="model",
            domain_id=point.domain_id,
            evidence_class="model_subject_point",
            evidence=(FindingEvidence(kind="aggregate_window", ref=point.id),),
            counts={"events": point.event_count},
        )

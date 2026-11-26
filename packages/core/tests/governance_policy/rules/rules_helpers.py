"""Builders and in-memory fakes for the rule evaluator tests (no I/O, synthetic data only)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.catalog.v1.agent_version import AgentVersion
from neurosphere_contracts.catalog.v1.grounding_source import GroundingSource
from neurosphere_contracts.catalog.v1.model_deployment import ModelDeployment
from neurosphere_contracts.catalog.v1.owned_by import OwnedByRelation
from neurosphere_contracts.catalog.v1.owner import Owner
from neurosphere_contracts.catalog.v1.reads import ReadsRelation
from neurosphere_contracts.catalog.v1.uses_model import UsesModelRelation
from neurosphere_contracts.policy.v1.policy_definition import PolicyDefinition, PolicyRule
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.aggregates.models import (
    AggregateWindow,
    SubjectPoint,
    aggregate_doc_id,
    format_bucket,
)
from neurosphere_core.aggregates.subject import SubjectKind, SubjectLookup
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.graph.access import AccessEngine
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.governance.policy.rules import (
    FindingCountPage,
    InteractionFindingCount,
    RuleContext,
    RunBudget,
)
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.protocol import SearchRequest, SearchResult

NS = "acme"
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
_CONTRACTS = Path(__file__).resolve().parents[4] / "contracts" / "schemas"
_CATALOG = _CONTRACTS / "catalog" / "v1" / "examples" / "valid"
_POLICY = _CONTRACTS / "policy" / "v1" / "examples" / "valid"
_STAMP = "2026-10-01T08:00:00Z"


def _example(folder: Path, name: str) -> dict[str, Any]:
    return json.loads((folder / name).read_text(encoding="utf-8"))


def dom(name: str) -> str:
    return f"commercial:{NS}:neurosphere:domain:{name}"


def agent_id(name: str) -> str:
    return f"commercial:{NS}:foundry:agent:{name}"


def version_id(name: str) -> str:
    return f"commercial:{NS}:foundry:agent_version:{name}"


def source_id(name: str) -> str:
    return f"commercial:{NS}:foundry:grounding_source:{name}"


def deployment_id(name: str) -> str:
    return f"commercial:{NS}:foundry:model_deployment:{name}"


def owner_id(name: str) -> str:
    return f"commercial:{NS}:foundry:owner:{name}"


def make_scope(*domains: str) -> IdentityScope:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": "commercial",
        "customer_id": NS,
        "principal": {
            "principal_id": f"commercial:{NS}:idp:person:p-0001",
            "principal_pseudonym": "p-0001",
            "principal_kind": "user",
        },
        "roles": [{"role": "viewer", "domain_ids": [dom(d) for d in domains]}],
        "allowed_domains": [dom(d) for d in domains],
        "allowed_resources": [],
        "policy_version": "v1",
        "derived_at": "2026-01-01T00:00:00Z",
        "scope_hash": "sha256:" + hashlib.sha256(b"p-0001").hexdigest(),
    }
    return IdentityScope._from_verified_contract(ContractScope.model_validate(payload))


SCOPE = make_scope("a", "b")


# --------------------------------------------------------------------------- catalog documents


def _entity(example: str, entity_id: str, domain: str, **patch: Any) -> dict[str, Any]:
    raw = _example(_CATALOG, example)
    raw.update(id=entity_id, customer_id=NS, domain_id=dom(domain), version=1, etag="caller-etag")
    raw.update(patch)
    return raw


def agent(name: str, domain: str = "a", **patch: Any) -> Agent:
    raw = _entity("agent.minimal-and-typical.json", agent_id(name), domain)
    raw.update(current_version_id=None, external_agent_id=None, display_name=f"Agent {name}")
    raw.update(patch)
    return Agent.model_validate(raw)


def agent_version(
    name: str, agent_name: str, domain: str = "a", *, state: str | None = None, **patch: Any
) -> AgentVersion:
    raw = _entity("agent_version.minimal-and-typical.json", version_id(name), domain)
    raw.update(agent_id=agent_id(agent_name), created_at=_STAMP, updated_at=_STAMP)
    raw["approval"] = None if state is None else {"state": state}
    raw.update(patch)
    return AgentVersion.model_validate(raw)


def grounding_source(name: str, domain: str = "a", **patch: Any) -> GroundingSource:
    raw = _entity("grounding_source.sensitivity-residency.json", source_id(name), domain)
    raw.update(display_name=f"Source {name}", tags=[], environment="unknown")
    raw.update(patch)
    return GroundingSource.model_validate(raw)


def deployment(
    name: str, domain: str = "a", *, model: str = "gpt-4o", version: str | None = "2024-08-06"
) -> ModelDeployment:
    raw = _entity("model_deployment.minimal-and-typical.json", deployment_id(name), domain)
    raw.update(model_name=model, model_version=version, deployment_name=name)
    return ModelDeployment.model_validate(raw)


def owner(name: str, domain: str = "a", *, lifecycle: str = "active") -> Owner:
    raw = _entity("owner.minimal-and-typical.json", owner_id(name), domain)
    raw.update(lifecycle_status=lifecycle)
    return Owner.model_validate(raw)


def _edge(example: str, relation: str, name: str, src: str, dst: str, domain: str) -> Any:
    raw = _example(_CATALOG, example)
    raw.update(
        id=f"commercial:{NS}:neurosphere:{relation}:{name}",
        source_id=src,
        target_id=dst,
        customer_id=NS,
        domain_id=dom(domain),
        version=1,
        etag="caller-etag",
    )
    return raw


def reads(name: str, src: str, dst: str, domain: str = "a") -> ReadsRelation:
    return ReadsRelation.model_validate(
        _edge("reads.asserted.json", "reads", name, src, dst, domain)
    )


def uses_model(name: str, src: str, dst: str, domain: str = "a") -> UsesModelRelation:
    raw = _edge("uses_model.asserted.json", "uses_model", name, src, dst, domain)
    return UsesModelRelation.model_validate(raw)


def owned_by(name: str, src: str, dst: str, domain: str = "a") -> OwnedByRelation:
    raw = _edge("owned_by.asserted.json", "owned_by", name, src, dst, domain)
    return OwnedByRelation.model_validate(raw)


async def seed(repo: InMemoryCatalogRepository, *docs: Any) -> None:
    """Create entities and edges (edges are recognised by ``relation_type``)."""
    for doc in docs:
        if hasattr(doc, "relation_type"):
            await repo.put_edge(SCOPE, doc, None)
        else:
            await repo.create_entity(SCOPE, doc)


# --------------------------------------------------------------------------- policies


def policy(kind: str, params: dict[str, Any], **applies_to: Any) -> PolicyDefinition:
    raw = _example(_POLICY, "policy-definition.all-kinds.json")
    raw["rules"] = [
        {
            "rule_id": "rule-1",
            "kind": kind,
            "severity": None,
            "applies_to": {
                "entity_types": [],
                "tags": [],
                "environments": [],
                "entity_ids": [],
                **applies_to,
            },
            "params": params,
        }
    ]
    return PolicyDefinition.model_validate(raw)


def only_rule(definition: PolicyDefinition) -> PolicyRule:
    return definition.rules[0]


class StepClock:
    """Monotonic clock that advances ``step`` seconds on every read."""

    def __init__(self, step: float = 0.0) -> None:
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        self.t += self.step
        return self.t


def context(
    *domains: str,
    max_subjects: int = 1000,
    seconds: float = 60.0,
    clock: StepClock | None = None,
) -> RuleContext:
    tick = clock or StepClock()
    return RuleContext(
        scope=SCOPE,
        domain_ids=tuple(dom(d) for d in (domains or ("a", "b"))),
        now=NOW,
        budget=RunBudget.start(max_subjects, seconds, clock=tick),
    )


# --------------------------------------------------------------------------- engines and fakes


class EmptySearch:
    async def search(self, scope: ContractScope, request: SearchRequest) -> SearchResult:
        return SearchResult(hits=[], matched=0, partial=False)


def access_engine(repo: InMemoryCatalogRepository) -> AccessEngine:
    graph = RepositoryGraphQuery(repo, EmptySearch(), now=lambda: NOW)
    return AccessEngine(repo, graph, now=lambda: NOW)


def subject_point(
    kind: SubjectKind, key: str, domain: str = "a", *, hours_ago: int = 1, events: int = 10
) -> SubjectPoint:
    start = format_bucket(NOW - timedelta(hours=hours_ago))
    series = f"{kind}:{key}"
    return SubjectPoint(
        id=aggregate_doc_id(NS, dom(domain), "subject", "hour", start, series),
        customer_id=NS,
        domain_id=dom(domain),
        grain="hour",
        bucket_start=start,
        series_key=series,
        watermark=start,
        complete=True,
        subject_kind=kind,
        subject_key=series,
        event_count=events,
        missing_duration_count=0,
        unknown_outcome_count=0,
        tokens_known_count=0,
    )


class FakeSubjects:
    """``SubjectMetricsReader`` over canned points; records each ``newest`` read."""

    def __init__(self, points: Sequence[SubjectPoint] = ()) -> None:
        self.points = list(points)
        self.reads: list[tuple[str, int]] = []

    async def latest_subject_points(
        self,
        customer_id: str,
        domain_id: str,
        kind: SubjectKind,
        keys: Sequence[str],
        window: AggregateWindow,
    ) -> SubjectLookup:
        return SubjectLookup(points={})

    async def newest_subject_points(
        self, customer_id: str, domain_id: str, window: AggregateWindow, limit: int
    ) -> SubjectLookup:
        self.reads.append((domain_id, limit))
        start, end = format_bucket(window.start), format_bucket(window.end)
        found = sorted(
            (
                p
                for p in self.points
                if p.customer_id == customer_id
                and p.domain_id == domain_id
                and start <= p.bucket_start < end
            ),
            key=lambda p: p.series_key,
        )
        kept = found[:limit]
        return SubjectLookup(points={p.series_key: p for p in kept}, truncated=len(found) > limit)


class FakeFindingReader:
    """``InteractionFindingReader`` over canned counts; records the arguments it got."""

    def __init__(self, counts: Sequence[InteractionFindingCount] = ()) -> None:
        self.counts = list(counts)
        self.calls: list[dict[str, Any]] = []

    async def count_findings(
        self,
        scope: IdentityScope,
        *,
        domain_ids: Sequence[str],
        categories: Sequence[str],
        parts: Sequence[str],
        start: datetime,
        end: datetime,
        limit: int,
    ) -> FindingCountPage:
        self.calls.append(
            {"domain_ids": list(domain_ids), "categories": list(categories), "limit": limit}
        )
        rows = [c for c in self.counts if c.domain_id in domain_ids]
        subjects = sorted({r.subject_id for r in rows})
        kept = set(subjects[:limit])
        return FindingCountPage(
            counts=tuple(r for r in rows if r.subject_id in kept),
            truncated=len(subjects) > limit,
        )

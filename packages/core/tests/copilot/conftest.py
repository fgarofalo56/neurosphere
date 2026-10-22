"""Fakes and builders for the copilot tool tests (offline; no network, no emulators)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.actions.v1.action_intent import ActionIntent
from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.actions import DraftRequest
from neurosphere_core.aggregates import (
    AggregateSeries,
    AggregateWindow,
    CostPoint,
    Grain,
    Metric,
    QueryResult,
)
from neurosphere_core.catalog import CatalogEntity, EntityFilter
from neurosphere_core.copilot.tools import (
    EvidenceRecord,
    RefusalEvent,
    ToolDependencies,
    ToolRegistry,
    build_default_registry,
)
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.scope import IdentityScope

SCHEMAS = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "schemas"
CUSTOMER = "contoso"
FINANCE = "commercial:contoso:catalog:domain:finance"
OPERATIONS = "commercial:contoso:catalog:domain:operations"
NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)


def _example(rel: str) -> dict[str, Any]:
    return json.loads((SCHEMAS / rel).read_text(encoding="utf-8"))


def _agent(name: str, domain: str) -> Agent:
    raw = _example("catalog/v1/examples/valid/agent.minimal-and-typical.json")
    raw.update(
        id=f"commercial:{CUSTOMER}:foundry:agent:{name}",
        customer_id=CUSTOMER,
        domain_id=domain,
        current_version_id=None,
        external_agent_id=None,
        version=1,
        etag="caller-etag",
        display_name=f"Agent {name}",
        updated_at="2026-10-21T08:00:00Z",
        created_at="2026-10-01T08:00:00Z",
    )
    return Agent.model_validate(raw)


def _recommendation(n: int, domain: str) -> Recommendation:
    raw = _example("recommendations/v1/examples/valid/recommendation.cost-spike-scored.json")
    raw["recommendation_id"] = f"commercial:{CUSTOMER}:neurosphere:recommendation:rec-{n:04d}"
    raw["domain_id"] = domain
    return Recommendation.model_validate(raw)


def _cost_point(domain: str, day: int, *, watermark: str | None) -> CostPoint:
    return CostPoint(
        id=f"agg-{domain.rsplit(':', 1)[-1]}-{day}",
        customer_id=CUSTOMER,
        domain_id=domain,
        grain="day",
        bucket_start=f"2026-10-{day:02d}T00:00:00Z",
        series_key="total",
        watermark=watermark,
        complete=True,
        kind="estimated",
        currency="USD",
        amount=Decimal("12.50"),
        entry_count=3,
        known_count=3,
        price_versions=[],
    )


def make_scope(roles: list[tuple[str, list[str]]], allowed: list[str]) -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "principal": {
                "principal_id": f"commercial:{CUSTOMER}:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [
                {
                    "role": role,
                    "domain_ids": domains,
                    **(
                        {"expires_at": "2099-01-01T00:00:00Z"}
                        if role in ("admin", "security_auditor")
                        else {}
                    ),
                }
                for role, domains in roles
            ],
            "allowed_domains": allowed,
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-20T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"copilot-scope").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


@dataclass
class FakeCatalog:
    entities: list[Agent]
    leak: bool = False
    """When True, ignore the domain filter (a misbehaving port) to prove the tool re-filters."""
    seen_filters: list[EntityFilter] = field(default_factory=list[EntityFilter])

    async def get_entity(self, scope: IdentityScope, entity_id: str) -> CatalogEntity | None:
        for e in self.entities:
            if e.id == entity_id and e.domain_id.root in scope.allowed_domains:
                return e
        return None

    async def list_entities(
        self, scope: IdentityScope, flt: EntityFilter, page: PageRequest
    ) -> Page[CatalogEntity]:
        self.seen_filters.append(flt)
        wanted = set(flt.domain_ids or [])
        items = [e for e in self.entities if self.leak or e.domain_id.root in wanted]
        return Page[CatalogEntity](items=tuple(items[: page.page_size]))


@dataclass
class FakeMetrics:
    watermark: str | None = "2026-10-21T10:00:00Z"
    domains_queried: list[str] = field(default_factory=list[str])

    async def query(
        self,
        customer_id: str,
        domain_id: str,
        metric: Metric,
        grain: Grain,
        window: AggregateWindow,
        *,
        max_series: int,
        max_points: int,
    ) -> QueryResult:
        self.domains_queried.append(domain_id)
        points = tuple(_cost_point(domain_id, d, watermark=self.watermark) for d in (1, 2))
        return QueryResult(series=(AggregateSeries(key="total", points=points),), truncated=False)


@dataclass
class FakeRecommendations:
    items: list[Recommendation]
    domains_queried: list[str] = field(default_factory=list[str])

    async def list(
        self,
        scope: IdentityScope,
        domain: str,
        kind: str | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[Recommendation]:
        self.domains_queried.append(domain)
        return Page[Recommendation](
            items=tuple(r for r in self.items if r.domain_id.root == domain)
        )


@dataclass
class FakeEvidence:
    records: list[EvidenceRecord]
    domains_seen: list[tuple[str, ...]] = field(default_factory=list[tuple[str, ...]])
    leak: bool = False

    async def get_many(
        self, scope: IdentityScope, domain_ids: Sequence[str], evidence_ids: Sequence[str]
    ) -> Sequence[EvidenceRecord]:
        self.domains_seen.append(tuple(domain_ids))
        return [
            r
            for r in self.records
            if r.evidence_id in evidence_ids and (self.leak or r.domain_id in domain_ids)
        ]


@dataclass
class FakeDrafter:
    requests: list[DraftRequest] = field(default_factory=list[DraftRequest])
    domains: list[str] = field(default_factory=list[str])

    async def draft(
        self, scope: IdentityScope, request: DraftRequest, *, domain_id: str
    ) -> ActionIntent:
        self.requests.append(request)
        self.domains.append(domain_id)
        raw = _example("actions/v1/examples/valid/action-intent.drafted-mcp-agent.json")
        raw.update(
            action_kind=request.action_kind,
            target=request.target.model_dump(mode="json"),
            target_version=request.target_version,
            idempotency_key=request.idempotency_key,
            channel=request.channel,
        )
        return ActionIntent.model_validate(raw)


@dataclass
class RecordingSink:
    events: list[RefusalEvent] = field(default_factory=list[RefusalEvent])

    def refused(self, event: RefusalEvent) -> None:
        self.events.append(event)


@dataclass
class Harness:
    registry: ToolRegistry
    catalog: FakeCatalog
    metrics: FakeMetrics
    recs: FakeRecommendations
    evidence: FakeEvidence
    drafter: FakeDrafter
    sink: RecordingSink


@pytest.fixture
def harness() -> Harness:
    catalog = FakeCatalog([_agent("fin-1", FINANCE), _agent("ops-1", OPERATIONS)])
    metrics = FakeMetrics()
    recs = FakeRecommendations([_recommendation(1, FINANCE), _recommendation(2, OPERATIONS)])
    evidence = FakeEvidence(
        [
            EvidenceRecord(
                evidence_id="ev-fin",
                kind="document",
                ref="doc-1",
                domain_id=FINANCE,
                observed_at="2026-10-21T09:00:00Z",
            ),
            EvidenceRecord(
                evidence_id="ev-ops",
                kind="document",
                ref="doc-2",
                domain_id=OPERATIONS,
                observed_at=None,
            ),
        ]
    )
    drafter = FakeDrafter()
    sink = RecordingSink()
    deps = ToolDependencies(
        catalog=catalog,
        metrics=metrics,
        recommendations=recs,
        evidence=evidence,
        drafter=drafter,
        clock=lambda: NOW,
    )
    return Harness(
        build_default_registry(deps, sink=sink), catalog, metrics, recs, evidence, drafter, sink
    )


@pytest.fixture
def scope_factory() -> Callable[[list[tuple[str, list[str]]], list[str]], IdentityScope]:
    return make_scope


@pytest.fixture
def query_args() -> Callable[..., dict[str, Any]]:
    """Builds a minimal valid StructuredQuery payload (the ``query`` argument of a read tool)."""

    def build(
        entity: str, *, operation: str = "list", limit: int = 20, **extra: Any
    ) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "operation": operation,
            "entity": entity,
            "budget": {"timeout_ms": 2000, "limit": limit, "max_depth": 0},
            **extra,
        }

    return build

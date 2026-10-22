"""Shared builders for the copilot API tests (PRP-19 item 2). Offline: no network, no emulator.

This directory has no ``__init__.py`` (same convention as ``services/api/tests/evaluation``):
import by module name. Everything here is a fake of a PORT (catalog, aggregates, recommendations,
evidence, the model) so the REAL engine, tool registry, authz and action service run in tests.

``World`` records every domain any data port was asked for (``domains_asked``): the injection
suite asserts that set stays inside the derived scope.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from neurosphere_api.copilot import (
    ActionPlaneDrafter,
    CopilotEngine,
    CopilotSettings,
    SseEvent,
    ToolPorts,
)
from neurosphere_api.copilot.context import resolve_context
from neurosphere_api.copilot.engine import ChartPlanValidator, TurnOutcome
from neurosphere_api.copilot.models import MessageContext
from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.aggregates import (
    AggregateSeries,
    AggregateWindow,
    CostPoint,
    Grain,
    InMemoryAggregateStore,
    Metric,
    QueryResult,
)
from neurosphere_core.catalog import CatalogEntity, EntityFilter
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.copilot.models import (
    Completed,
    ModelEvent,
    ModelRequest,
    TextDelta,
    ToolCallRequested,
)
from neurosphere_core.copilot.models.protocol import AdapterDescriptor
from neurosphere_core.copilot.tools import EvidenceRecord
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.recommendations import InMemoryRecommendationStore
from neurosphere_core.scope import IdentityScope

SCHEMAS = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "schemas"
CUSTOMER = "contoso"
FINANCE = "commercial:contoso:catalog:domain:finance"
OPERATIONS = "commercial:contoso:catalog:domain:operations"
NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)


def _example(rel: str) -> dict[str, Any]:
    return json.loads((SCHEMAS / rel).read_text(encoding="utf-8"))


def agent(
    entity_id: str,
    domain: str,
    *,
    customer: str = CUSTOMER,
    cloud: str = "commercial",
    **attrs: Any,
) -> Agent:
    raw = _example("catalog/v1/examples/valid/agent.minimal-and-typical.json")
    raw.update(
        id=entity_id,
        cloud=cloud,
        customer_id=customer,
        domain_id=domain,
        current_version_id=None,
        external_agent_id=None,
        version=1,
        etag="caller-etag",
        display_name="Agent " + entity_id.rsplit(":", 1)[-1][:40],
        updated_at="2026-10-21T08:00:00Z",
        created_at="2026-10-01T08:00:00Z",
        attributes=dict(attrs),
    )
    return Agent.model_validate(raw)


def recommendation(n: int, domain: str) -> Recommendation:
    raw = _example("recommendations/v1/examples/valid/recommendation.cost-spike-scored.json")
    raw["recommendation_id"] = f"commercial:{CUSTOMER}:neurosphere:recommendation:rec-{n:04d}"
    raw["domain_id"] = domain
    return Recommendation.model_validate(raw)


def make_scope(
    roles: Sequence[tuple[str, Sequence[str]]],
    allowed: Sequence[str],
    *,
    cloud: str = "commercial",
    customer: str = CUSTOMER,
) -> IdentityScope:
    """A real ``IdentityScope`` (verified-contract constructor, as the deriver builds it)."""
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": cloud,
            "customer_id": customer,
            "principal": {
                "principal_id": f"{cloud}:{customer}:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [
                {
                    "role": role,
                    "domain_ids": list(domains),
                    **(
                        {"expires_at": "2099-01-01T00:00:00Z"}
                        if role in ("admin", "security_auditor")
                        else {}
                    ),
                }
                for role, domains in roles
            ],
            "allowed_domains": list(allowed),
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-20T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"copilot-api-scope").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


# -- port fakes (real in-memory classes with a recording read path) ------------------------------


class RecordingCatalog(InMemoryCatalogRepository):
    def __init__(self, entities: Sequence[Agent]) -> None:
        super().__init__()
        self.entities = list(entities)
        self.domains_asked: list[str] = []

    async def get_entity(self, scope: IdentityScope, entity_id: str) -> CatalogEntity | None:
        for entity in self.entities:
            if entity.id == entity_id:
                self.domains_asked.append(entity.domain_id.root)
                return entity if entity.domain_id.root in scope.allowed_domains else None
        return None

    async def list_entities(
        self, scope: IdentityScope, flt: EntityFilter, page: PageRequest
    ) -> Page[CatalogEntity]:
        self.domains_asked.extend(flt.domain_ids or [])
        wanted = set(flt.domain_ids or [])
        items = [
            e
            for e in self.entities
            if e.domain_id.root in wanted and e.domain_id.root in scope.allowed_domains
        ]
        return Page[CatalogEntity](items=tuple(items[: page.page_size]))


class RecordingMetrics(InMemoryAggregateStore):
    def __init__(
        self, *, series_key: str = "total", watermark: str | None = "2026-10-21T10:00:00Z"
    ):
        super().__init__()
        self.series_key = series_key
        self.watermark = watermark
        self.domains_asked: list[str] = []

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
        self.domains_asked.append(domain_id)
        points = tuple(
            CostPoint(
                id=f"agg-{domain_id.rsplit(':', 1)[-1]}-{day}",
                customer_id=customer_id,
                domain_id=domain_id,
                grain="day",
                bucket_start=f"2026-10-{day:02d}T00:00:00Z",
                series_key=self.series_key,
                watermark=self.watermark,
                complete=True,
                kind="estimated",
                currency="USD",
                amount=Decimal("12.50"),
                entry_count=3,
                known_count=3,
                price_versions=[],
            )
            for day in (1, 2)
        )
        return QueryResult(
            series=(AggregateSeries(key=self.series_key, points=points),), truncated=False
        )


class RecordingRecommendations(InMemoryRecommendationStore):
    def __init__(self, items: Sequence[Recommendation]) -> None:
        super().__init__(items)
        self.domains_asked: list[str] = []

    async def list(
        self,
        scope: IdentityScope,
        domain: str,
        kind: str | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[Recommendation]:
        self.domains_asked.append(domain)
        return await super().list(scope, domain, kind, q, cursor, limit)


@dataclass
class RecordingEvidence:
    records: list[EvidenceRecord] = field(default_factory=list[EvidenceRecord])
    domains_asked: list[str] = field(default_factory=list[str])

    async def get_many(
        self, scope: IdentityScope, domain_ids: Sequence[str], evidence_ids: Sequence[str]
    ) -> Sequence[EvidenceRecord]:
        self.domains_asked.extend(domain_ids)
        return [r for r in self.records if r.evidence_id in evidence_ids]


@dataclass
class World:
    catalog: RecordingCatalog
    metrics: RecordingMetrics
    recs: RecordingRecommendations
    evidence: RecordingEvidence

    @property
    def ports(self) -> ToolPorts:
        return ToolPorts(
            catalog=self.catalog,
            metrics=self.metrics,
            recommendations=self.recs,
            evidence=self.evidence,
        )

    def domains_asked(self) -> set[str]:
        return {
            *self.catalog.domains_asked,
            *self.metrics.domains_asked,
            *self.recs.domains_asked,
            *self.evidence.domains_asked,
        }


def make_world(
    entities: Sequence[Agent] | None = None,
    *,
    recs: Sequence[Recommendation] | None = None,
    evidence: Sequence[EvidenceRecord] = (),
    series_key: str = "total",
    watermark: str | None = "2026-10-21T10:00:00Z",
) -> World:
    return World(
        catalog=RecordingCatalog(
            entities
            if entities is not None
            else [
                agent("commercial:contoso:foundry:agent:fin-1", FINANCE),
                agent("commercial:contoso:foundry:agent:ops-1", OPERATIONS),
            ]
        ),
        metrics=RecordingMetrics(series_key=series_key, watermark=watermark),
        recs=RecordingRecommendations(
            recs
            if recs is not None
            else [recommendation(1, FINANCE), recommendation(2, OPERATIONS)]
        ),
        evidence=RecordingEvidence(list(evidence)),
    )


# -- the scripted model --------------------------------------------------------------------------

Step = Callable[[ModelRequest], list[ModelEvent]]


class ScriptedAdapter:
    """Replays one scripted step per model invocation; the last step repeats if exhausted.

    A step is a function of the request, so a "compromised" model can read what it was shown
    (system text, tool results) exactly as a real one could. ``requests`` keeps every request.
    """

    def __init__(self, *steps: Step) -> None:
        self._steps = steps
        self.requests: list[ModelRequest] = []
        self._descriptor = AdapterDescriptor(kind="fixture", name="scripted", synthetic=True)

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        index = min(len(self.requests), len(self._steps) - 1)
        self.requests.append(request)
        for event in self._steps[index](request):
            yield event


def say(text: str) -> Step:
    return lambda _r: [TextDelta(text=text), Completed(stop_reason="end_turn")]


def call(name: str, arguments: dict[str, Any], call_id: str = "call_1") -> Step:
    return lambda _r: [
        ToolCallRequested(call_id=call_id, tool_name=name, arguments=arguments),
        Completed(stop_reason="tool_calls"),
    ]


def query_args(
    entity: str,
    *,
    domain: str | None = None,
    operation: str = "list",
    limit: int = 20,
    **extra: Any,
) -> dict[str, Any]:
    """A minimal valid ``StructuredQuery`` payload, optionally filtered to one domain."""
    query: dict[str, Any] = {
        "schema_version": "1.0.0",
        "operation": operation,
        "entity": entity,
        "budget": {"timeout_ms": 2000, "limit": limit, "max_depth": 0},
        **extra,
    }
    if domain is not None:
        query["filters"] = [{"field": "domain_id", "op": "eq", "value": domain}]
    return query


def cost_args(*, domain: str | None = None) -> dict[str, Any]:
    return {
        "query": query_args(
            "cost_record",
            operation="aggregate",
            domain=domain,
            time_range={"start": "2026-10-01T00:00:00Z", "end": "2026-10-10T00:00:00Z"},
            time_bucket="day",
        )
    }


# -- driving the engine --------------------------------------------------------------------------


@dataclass
class Turn:
    events: list[SseEvent]
    persisted: list[TurnOutcome]
    drafter: ActionPlaneDrafter

    @property
    def names(self) -> list[str]:
        return [e.name for e in self.events]

    @property
    def terminal(self) -> SseEvent:
        return self.events[-1]

    def of(self, name: str) -> list[SseEvent]:
        return [e for e in self.events if e.name == name]

    @property
    def text(self) -> str:
        return "".join(getattr(e.payload, "text", "") for e in self.of("token"))


def make_engine(
    adapter: ScriptedAdapter,
    world: World,
    *,
    settings: CopilotSettings | None = None,
    chart_validator: ChartPlanValidator | None = None,
) -> CopilotEngine:
    return CopilotEngine(
        adapter=adapter,
        ports=world.ports,
        settings=settings or CopilotSettings(),
        chart_validator=chart_validator,
        clock=lambda: NOW,
    )


async def run_turn(
    engine: CopilotEngine,
    scope: IdentityScope,
    text: str = "What changed in finance?",
    *,
    hint: MessageContext | None = None,
    settings: CopilotSettings | None = None,
) -> Turn:
    context = await resolve_context(
        scope,
        hint or MessageContext(),
        catalog=engine.ports.catalog,
        settings=settings or CopilotSettings(),
        now=NOW,
    )
    persisted: list[TurnOutcome] = []

    async def persist(outcome: TurnOutcome) -> None:
        persisted.append(outcome)

    drafter = ActionPlaneDrafter(None, "corr-test")
    events = [
        event
        async for event in engine.run(
            scope=scope,
            user_text=text,
            context=context,
            history=[],
            drafter=drafter,
            correlation_id="corr-test",
            persist=persist,
        )
    ]
    return Turn(events=events, persisted=persisted, drafter=drafter)

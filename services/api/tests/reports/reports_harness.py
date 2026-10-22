"""Harness for the saved-report API tests (PRP-19 item 5). No network.

The REAL authz stack (dev-issuer JWTs, scope derivation over an in-memory policy store) from
``services/api/tests/authz``, the real reports router, an in-memory report store and the real
copilot tool registry over in-memory catalog fakes.

People (customer ``contoso``):

* ALICE -- analyst on FINANCE and OPERATIONS (the report owner)
* BOB   -- viewer on FINANCE only (a share principal)
* CAROL -- viewer on FINANCE (never shared)
* DAVE  -- admin on FINANCE (``config.manage``; approves publications)
* ERIN  -- analyst AND admin on FINANCE (can request, must not approve her own)

This directory has no ``__init__.py``: import by module name.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
from neurosphere_api.reports import (
    PREFIX,
    InMemoryReportStore,
    RunCache,
    build_router,
    configure_reports,
)
from neurosphere_contracts.actions.v1.action_intent import ActionIntent
from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from neurosphere_core.actions import DraftRequest
from neurosphere_core.aggregates import AggregateWindow, Grain, Metric, QueryResult
from neurosphere_core.auth.scope import Role
from neurosphere_core.catalog import CatalogEntity, EntityFilter
from neurosphere_core.copilot.tools import (
    EvidenceRecord,
    ToolDependencies,
    ToolRegistry,
    build_default_registry,
)
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.scope import IdentityScope

ALICE: str = helpers.ALICE
BOB: str = helpers.BOB
CAROL: str = helpers.CAROL
DAVE: str = helpers.NOBODY
ERIN: str = "a05b6c7d-8e9f-4a01-b2c3-d4e5f6a7b8c9"
FINANCE: str = helpers.FINANCE
OPERATIONS: str = helpers.OPERATIONS
CUSTOMER: str = helpers.CUSTOMER

_SCHEMAS = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "schemas"

REPORTS_PATH = f"{PREFIX}/domains/{FINANCE}/reports"


def principal(object_id: str) -> str:
    return str(helpers.principal_id_for(object_id))


def _agent(name: str, domain: str, version: int) -> Agent:
    raw = json.loads(
        (_SCHEMAS / "catalog/v1/examples/valid/agent.minimal-and-typical.json").read_text(
            encoding="utf-8"
        )
    )
    raw.update(
        id=f"commercial:{CUSTOMER}:foundry:agent:{name}",
        customer_id=CUSTOMER,
        domain_id=domain,
        current_version_id=None,
        external_agent_id=None,
        version=version,
        etag="caller-etag",
        display_name=f"Agent {name}",
        updated_at="2026-10-21T08:00:00Z",
        created_at="2026-10-01T08:00:00Z",
    )
    return Agent.model_validate(raw)


class FakeCatalog:
    """Domain-filtered catalog stand-in (the tool re-filters as well)."""

    def __init__(self, entities: Sequence[Agent]) -> None:
        self.entities = list(entities)

    async def get_entity(self, scope: IdentityScope, entity_id: str) -> CatalogEntity | None:
        return None

    async def list_entities(
        self, scope: IdentityScope, flt: EntityFilter, page: PageRequest
    ) -> Page[CatalogEntity]:
        wanted = set(flt.domain_ids or [])
        items = [e for e in self.entities if e.domain_id.root in wanted]
        return Page[CatalogEntity](items=tuple(items[: page.page_size]))


class _Unused:
    """Ports the report tools never reach in these tests."""

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
        raise AssertionError("metrics are not used")

    async def list(
        self,
        scope: IdentityScope,
        domain: str,
        kind: str | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[Recommendation]:
        raise AssertionError("recommendations are not used")

    async def get_many(
        self, scope: IdentityScope, domain_ids: Sequence[str], evidence_ids: Sequence[str]
    ) -> Sequence[EvidenceRecord]:
        raise AssertionError("evidence is not used")

    async def draft(
        self, scope: IdentityScope, request: DraftRequest, *, domain_id: str
    ) -> ActionIntent:
        raise AssertionError("reports never draft actions")


def agent_query(**extra: Any) -> dict[str, Any]:
    """A bounded StructuredQuery listing agents (no scope fields, no free text)."""
    return {
        "schema_version": "1.0.0",
        "operation": "list",
        "entity": "agent",
        "budget": {"timeout_ms": 2000, "limit": 20, "max_depth": 0},
        **extra,
    }


def chart_plan() -> dict[str, Any]:
    """A valid plan; the sample row only exists so field references validate at save time."""
    return {
        "schema_version": "1.0.0",
        "citations": [{"evidence_id": "ev:agents", "as_of": "2026-10-10T11:58:00Z"}],
        "spec": {
            "title": "Agent versions",
            "data": {"values": [{"display_name": "sample", "version": 1.0}]},
            "mark": "bar",
            "encoding": {
                "x": {"field": "display_name", "type": "nominal"},
                "y": {"field": "version", "type": "quantitative"},
            },
        },
    }


def report_body(title: str = "Agents by version", **overrides: Any) -> dict[str, Any]:
    return {"title": title, "chart_plan": chart_plan(), "query_spec": agent_query(), **overrides}


@dataclass
class Api:
    h: Any
    store: InMemoryReportStore
    registry: ToolRegistry
    catalog: FakeCatalog
    responses: list[Any] = field(default_factory=list[Any])

    def call(self, method: str, who: str | None, path: str = "", **kwargs: Any) -> Any:
        headers = dict(self.h.auth(who)) if who else {}
        headers.update(kwargs.pop("headers", {}))
        response = self.h.client.request(method, f"{REPORTS_PATH}{path}", headers=headers, **kwargs)
        self.responses.append(response)
        return response

    def create(self, who: str = ALICE, body: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.call("POST", who, json=body or report_body())
        assert response.status_code == 201, response.text
        return response.json()

    def run(self, who: str, report_id: str) -> Any:
        return self.call("POST", who, f"/{report_id}/run")

    def revoke(self, who: str, *roles: Any) -> None:
        """Replace a principal's policy and drop the cached copy (the revocation cache hook)."""
        self.h.repo.put_principal(helpers.policy(who, *roles))
        self.h.deriver.invalidate_principal(principal(who))

    def share(self, owner: str, report_id: str, with_whom: str) -> dict[str, Any]:
        response = self.call(
            "POST", owner, f"/{report_id}/shares", json={"principal_id": principal(with_whom)}
        )
        assert response.status_code == 200, response.text
        return response.json()


def problem(response: Any) -> dict[str, Any]:
    assert response.headers["content-type"].startswith("application/problem+json"), response.text
    return response.json()


def make_api(*, cache: RunCache | None = None) -> Api:
    h = helpers.harness(
        helpers.policy(
            ALICE,
            helpers.role(Role.ANALYST, FINANCE, OPERATIONS),
        ),
        helpers.policy(BOB, helpers.role(Role.VIEWER, FINANCE)),
        helpers.policy(CAROL, helpers.role(Role.VIEWER, FINANCE)),
        helpers.policy(DAVE, helpers.role(Role.ADMIN, FINANCE)),
        helpers.policy(
            ERIN, helpers.role(Role.ANALYST, FINANCE), helpers.role(Role.ADMIN, FINANCE)
        ),
        routers={PREFIX: build_router()},
    )

    def clock() -> datetime:
        return datetime.fromtimestamp(h.clock(), UTC)

    catalog = FakeCatalog(
        [
            _agent("fin-1", FINANCE, 3),
            _agent("fin-2", FINANCE, 4),
            _agent("ops-1", OPERATIONS, 9),
        ]
    )
    unused: Any = _Unused()
    registry = build_default_registry(
        ToolDependencies(
            catalog=catalog,
            metrics=unused,
            recommendations=unused,
            evidence=unused,
            drafter=unused,
            clock=clock,
        )
    )
    store = InMemoryReportStore()
    configure_reports(h.app, store=store, tool_registry=registry, clock=clock, run_cache=cache)
    return Api(h=h, store=store, registry=registry, catalog=catalog)

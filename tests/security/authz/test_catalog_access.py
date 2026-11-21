"""ABAC negative suite for the catalog access routes (PRP-73 item 4).

The suite world (``world.py``) serves the real router table, so the three access routes are
mounted at the canonical ``/api/v1/catalog/access`` prefix and at the ``/catalog/access`` alias.
This module installs one in-memory catalog (repository + graph) on every deployment, additively,
and asserts per route (canonical and alias) and per dimension:

=====================================  ====================================================
Dimension                              Expected outcome
=====================================  ====================================================
no role                                403, denial recorded, nothing read
viewer assigned to another domain      200 with nothing of the unreadable domain, no denial
                                       (the routes name no domain; the SCOPE filters), and
                                       the same answer as for ids that do not exist
wrong customer (other deployment)      200 with nothing, no denial
wrong cloud (Government ids)           200 with nothing; a Government region is 422
expired assignment                     403, denial recorded
body-supplied scope fields             422 for an entitled caller (extra fields forbidden,
                                       clarification 12), 403 for a caller with no role;
                                       never honoured; a GET query string or header carrying
                                       customer, cloud or domain is ignored
=====================================  ====================================================

``test_catalog_access_leak.py`` holds the two-domain leak proofs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.catalog.v1.grounding_source import GroundingSource
from neurosphere_contracts.catalog.v1.invokes import InvokesRelation
from neurosphere_contracts.catalog.v1.reads import ReadsRelation
from neurosphere_contracts.catalog.v1.writes import WritesRelation
from neurosphere_core.auth.scope import (
    PolicyRoleAssignment,
    PrincipalPolicy,
    Role,
    principal_document_id,
)
from neurosphere_core.catalog import CatalogEdge
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.cloud import CloudName
from neurosphere_core.search.fixture.index import FixtureSearchIndex, documents_from_catalog

from .test_agent_match import make_agent, writer_scope
from .world import (
    AUDIENCE,
    TENANTS,
    Deployment,
    Who,
    World,
    at,
    dev_issuer,
    domain_id,
    pseudonymizer,
    run,
)

PREFIX = "/api/v1/catalog/access"
ALIAS = "/catalog/access"
FIN_ID = domain_id("contoso", "finance")
OPS_ID = domain_id("contoso", "operations")
HR_ID = domain_id("contoso", "hr")
FAB_FIN_ID = domain_id("fabrikam", "finance")
GOV_FIN_ID = domain_id("contoso", "finance", cloud="government")
VIEWER_FIN = Who("contoso", "finance", Role.VIEWER)
VIEWER_OPS = Who("contoso", "operations", Role.VIEWER)
VIEWER_FAB = Who("fabrikam", "finance", Role.VIEWER)
NO_ROLE_OID = "a1b2c3d4-0000-4000-8000-00000000f073"
EXPIRED_OID = "a1b2c3d4-0000-4000-8000-00000000f074"
NS = "commercial:contoso"
GOV_ASSET_ID = "government:contoso:foundry:grounding_source:gov-ledger"
_EXAMPLES = (
    Path(__file__).resolve().parents[3] / "packages/contracts/schemas/catalog/v1/examples/valid"
)

# Names of the seeded catalog (synthetic). FIN is readable by VIEWER_FIN, OPS by VIEWER_OPS.
FIN_ASSET = f"{NS}:foundry:grounding_source:customers"
OPS_ASSET = f"{NS}:foundry:grounding_source:ledger"
FIN_AGENT_W = f"{NS}:foundry:agent:fin-writer"
FIN_AGENT_R = f"{NS}:foundry:agent:fin-reader"
OPS_AGENT = f"{NS}:foundry:agent:ops-reader"
# Dependents chain: fin-top (FIN) -> ops-mid (OPS) -> fin-svc (FIN); a second, wholly FIN chain.
FIN_SVC = f"{NS}:foundry:agent:fin-svc"
OPS_MID = f"{NS}:foundry:agent:ops-mid"
FIN_TOP = f"{NS}:foundry:agent:fin-top"
FIN_NEAR = f"{NS}:foundry:agent:fin-near"
MISSING_ID = f"{NS}:foundry:grounding_source:does-not-exist"
MISSING_NODE = f"{NS}:foundry:agent:does-not-exist"


@dataclass(frozen=True)
class Route:
    name: str
    method: str
    suffix: str
    body: dict[str, Any] | None

    def path(self, prefix: str) -> str:
        return prefix + self.suffix


ROUTES: tuple[Route, ...] = (
    Route("query", "POST", "/query", {"asset_ids": [FIN_ASSET, OPS_ASSET]}),
    Route("dependents", "POST", "/dependents", {"node_id": FIN_SVC, "max_depth": 3}),
    Route("region-groups", "GET", "/region-groups", None),
)
PREFIXES = {"canonical": PREFIX, "alias": ALIAS}
#: (route, prefix label) pairs: every route on the canonical path and on the alias.
VARIANTS = [
    pytest.param(r, p, id=f"{r.name}-{label}") for r in ROUTES for label, p in PREFIXES.items()
]
POST_VARIANTS = [
    pytest.param(r, p, id=f"{r.name}-{label}")
    for r in ROUTES
    if r.method == "POST"
    for label, p in PREFIXES.items()
]
QUERY_VARIANTS = [
    pytest.param(r, p, id=f"{r.name}-{label}")
    for r in ROUTES
    if r.name == "query"
    for label, p in PREFIXES.items()
]

AUDITED = {"query": "catalog.access_query", "dependents": "catalog.dependents"}


def example(name: str) -> dict[str, Any]:
    loaded = json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def asset(name: str, domain: str, **patch: Any) -> GroundingSource:
    raw = example("grounding_source.sensitivity-residency.json")
    raw.update(
        id=f"{NS}:foundry:grounding_source:{name}",
        domain_id=domain,
        display_name=f"Asset {name}",
        version=1,
        etag="caller-etag",
        tags=[],
        environment="unknown",
    )
    raw.update(patch)
    return GroundingSource.model_validate(raw)


def edge(kind: str, name: str, source: str, target: str, domain: str, **patch: Any) -> CatalogEdge:
    raw = example(f"{kind}.inferred.json")
    raw.update(
        id=f"{NS}:neurosphere:{kind}:{name}",
        source_id=source,
        target_id=target,
        domain_id=domain,
        version=1,
        etag="caller-etag",
    )
    raw.update(patch)
    model = {"reads": ReadsRelation, "writes": WritesRelation, "invokes": InvokesRelation}[kind]
    return model.model_validate(raw)


def _agent(name: str, domain: str) -> Any:
    return make_agent(name, domain, tags=["t"], description=f"{name} agent")


@dataclass
class AccessWorld:
    world: World
    repo: InMemoryCatalogRepository


def install(world: World) -> AccessWorld:
    """Seed one catalog (contoso, two domains) and serve it from EVERY deployment.

    The fabrikam deployment gets the same repository on purpose: its callers must see none of
    contoso's data because of the scope, not because of an empty store.
    """
    repo = InMemoryCatalogRepository()
    entities: list[Any] = [
        _agent("fin-writer", "finance"),
        _agent("fin-reader", "finance"),
        _agent("ops-reader", "operations"),
        _agent("fin-svc", "finance"),
        _agent("ops-mid", "operations"),
        _agent("fin-top", "finance"),
        _agent("fin-near", "finance"),
        asset(
            "customers",
            FIN_ID,
            contains_personal_data=True,
            sensitivity_categories=["pii"],
            residency_region="westeurope",
            classification="restricted",
        ),
        asset(
            "ledger",
            OPS_ID,
            contains_personal_data=True,
            sensitivity_categories=["pii"],
            residency_region="northeurope",
            classification="restricted",
        ),
    ]
    edges = [
        edge("writes", "w-fin", FIN_AGENT_W, FIN_ASSET, FIN_ID),
        edge("reads", "r-fin", FIN_AGENT_R, FIN_ASSET, FIN_ID),
        edge("reads", "r-ops-fin", OPS_AGENT, FIN_ASSET, FIN_ID),
        edge("writes", "w-ops", OPS_AGENT, OPS_ASSET, OPS_ID),
        edge("reads", "r-fin-ops", FIN_AGENT_R, OPS_ASSET, OPS_ID),
        edge("invokes", "top-mid", FIN_TOP, OPS_MID, FIN_ID),
        edge("invokes", "mid-svc", OPS_MID, FIN_SVC, OPS_ID),
        edge("invokes", "near-svc", FIN_NEAR, FIN_SVC, FIN_ID),
    ]

    async def seed() -> None:
        scope = writer_scope()
        for entity in entities:
            await repo.create_entity(scope, entity)
        for e in edges:
            await repo.put_edge(scope, e, None)

    run(seed())
    docs = [e.model_dump(mode="json") for e in entities]
    graph = RepositoryGraphQuery(repo, FixtureSearchIndex(documents_from_catalog(docs)))
    for dep in world.deployments.values():
        dep.app.state.catalog_repository = repo
        dep.app.state.catalog_graph = graph
        dep.app.state.audit_repository = dep.audit_repo
    _seed_principal(world["contoso"], NO_ROLE_OID, roles=())
    expiring = PolicyRoleAssignment(
        assignment_id="ra-expiring", role=Role.VIEWER, domain_ids=(FIN_ID,), expires_at=at(10)
    )
    _seed_principal(world["contoso"], EXPIRED_OID, roles=(expiring,))
    return AccessWorld(world=world, repo=repo)


def _seed_principal(
    dep: Deployment,
    object_id: str,
    *,
    roles: tuple[PolicyRoleAssignment, ...],
    memberships: tuple[str, ...] = (FIN_ID,),
) -> None:
    principal = pseudonymizer().principal_id(
        cloud=CloudName.COMMERCIAL,
        customer_id=dep.customer,
        tenant_id=TENANTS[dep.customer],
        object_id=object_id,
        kind="user",
    )
    dep.repo.put_principal(
        PrincipalPolicy(
            id=principal_document_id(principal),
            customer_id=dep.customer,
            principal_id=principal,
            domain_memberships=memberships,
            role_assignments=roles,
        )
    )


def bearer_for(dep: Deployment, object_id: str) -> dict[str, str]:
    token = dev_issuer(dep.customer).mint(audience=AUDIENCE, object_id=object_id, now=dep.clock.now)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def aworld(world: World) -> AccessWorld:
    return install(world)


def call(
    dep: Deployment,
    route: Route,
    prefix: str,
    headers: dict[str, str],
    *,
    body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> Any:
    payload = body if body is not None else route.body
    return dep.client.request(
        route.method, route.path(prefix), headers=headers, json=payload, params=params
    )


def audit_count(dep: Deployment) -> int:
    return sum(1 for (_c, d) in dep.audit_store._docs if d != "tail")  # pyright: ignore[reportPrivateUsage]


def audit_text(dep: Deployment) -> str:
    docs: list[dict[str, Any]] = []
    for chain in sorted({chain for (chain, _doc) in dep.audit_store._docs}):  # pyright: ignore[reportPrivateUsage]
        docs.extend(dep.audit_store.raw_documents(chain))
    return json.dumps(docs, sort_keys=True)


def assert_denied(dep: Deployment, route: Route, prefix: str, headers: dict[str, str]) -> Any:
    attempts, audited = len(dep.recorder.attempts), audit_count(dep)
    response = call(dep, route, prefix, headers)
    assert response.status_code == 403, f"{route.name}: {response.status_code} {response.text}"
    assert len(dep.recorder.attempts) == attempts + 1, "no denial was recorded"
    assert audit_count(dep) == audited + 1, "the denial record was not persisted"
    assert dep.recorder.attempts[-1].reason == response.json()["reason"]
    # The refusal says nothing about the catalog.
    for fragment in ("fin-writer", "fin-reader", "ops-reader", "Asset customers"):
        assert fragment not in response.text
    return response


def rows_of(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "rows" in payload:
        return list(payload["rows"])
    return [r for g in payload["groups"] for r in g["rows"]]


def assert_nothing_from(payload: dict[str, Any], *forbidden: str) -> None:
    text = json.dumps(payload)
    for fragment in forbidden:
        assert fragment not in text, f"{fragment} leaked: {text}"


def allowed_records(dep: Deployment, before: int) -> int:
    return audit_count(dep) - before


def test_every_route_in_the_inventory_has_a_case() -> None:
    from fastapi.routing import APIRoute
    from neurosphere_api.catalog.access.router import build_router

    served = {
        (r.path, m)
        for r in build_router().routes
        if isinstance(r, APIRoute)
        for m in sorted(r.methods or ())
    }
    cases = {(r.suffix, r.method) for r in ROUTES}
    assert served == cases


@pytest.mark.parametrize(("route", "prefix"), VARIANTS)
def test_no_role(aworld: AccessWorld, route: Route, prefix: str) -> None:
    dep = aworld.world["contoso"]
    response = assert_denied(dep, route, prefix, bearer_for(dep, NO_ROLE_OID))
    assert response.json()["reason"] == "permission_missing", response.text


@pytest.mark.parametrize(("route", "prefix"), VARIANTS)
def test_no_token_is_unauthorized(aworld: AccessWorld, route: Route, prefix: str) -> None:
    dep = aworld.world["contoso"]
    before = audit_count(dep)
    response = call(dep, route, prefix, {})
    assert response.status_code == 401, response.text
    assert audit_count(dep) == before


@pytest.mark.parametrize(("route", "prefix"), VARIANTS)
def test_viewer_assigned_to_another_domain(aworld: AccessWorld, route: Route, prefix: str) -> None:
    """The routes name no domain, so the scope is the only filter: an operations viewer asking
    about finance data gets 200 and nothing from finance; the denial is the empty answer."""
    dep = aworld.world["contoso"]
    headers = dep.bearer(VIEWER_OPS)
    attempts, audited = len(dep.recorder.attempts), audit_count(dep)
    response = call(dep, route, prefix, headers)
    assert response.status_code == 200, response.text
    assert len(dep.recorder.attempts) == attempts, "a permitted read recorded a denial"
    expected_records = 1 if route.name in AUDITED else 0
    assert audit_count(dep) == audited + expected_records
    payload = response.json()
    if route.name == "query":
        assert rows_of(payload) == [r for r in rows_of(payload) if r["asset_id"] == OPS_ASSET]
        assert_nothing_from(payload, FIN_ASSET, FIN_ID, "fin-writer", "fin-reader")
    elif route.name == "dependents":
        assert payload["groups"] == [] and payload["total"] == 0
        assert_nothing_from(payload, FIN_TOP, FIN_NEAR, FIN_SVC, FIN_ID)


@pytest.mark.parametrize(("route", "prefix"), QUERY_VARIANTS)
def test_viewer_naming_a_domain_filter_of_the_other_domain(
    aworld: AccessWorld, route: Route, prefix: str
) -> None:
    dep = aworld.world["contoso"]
    body = {"filters": {"domain_ids": [FIN_ID]}}
    response = call(dep, route, prefix, dep.bearer(VIEWER_OPS), body=body)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["rows"] == [] and payload["assets"] == []
    assert_nothing_from(payload, FIN_ASSET, FIN_ID)


@pytest.mark.parametrize(("route", "prefix"), VARIANTS)
def test_wrong_customer(aworld: AccessWorld, route: Route, prefix: str) -> None:
    """A fabrikam viewer is served the same repository and still sees nothing of contoso."""
    fab = aworld.world["fabrikam"]
    attempts, audited = len(fab.recorder.attempts), audit_count(fab)
    response = call(fab, route, prefix, fab.bearer(VIEWER_FAB))
    assert response.status_code == 200, response.text
    assert len(fab.recorder.attempts) == attempts
    assert audit_count(fab) == audited + (1 if route.name in AUDITED else 0)
    payload = response.json()
    if route.name == "region-groups":
        assert payload["groups"]
        return
    assert rows_of(payload) == []
    assert_nothing_from(payload, "contoso", FIN_ASSET, OPS_ASSET, FIN_ID, OPS_ID)
    if route.name == "query":
        assert payload["assets"] == [] and payload["assets_scanned"] == 0


@pytest.mark.parametrize(("route", "prefix"), VARIANTS)
def test_wrong_cloud(aworld: AccessWorld, route: Route, prefix: str) -> None:
    """A Commercial caller naming Government domains, assets or nodes gets nothing."""
    dep = aworld.world["contoso"]
    headers = dep.bearer(VIEWER_FIN)
    if route.name == "query":
        body: dict[str, Any] = {
            "asset_ids": [GOV_ASSET_ID],
            "filters": {"domain_ids": [GOV_FIN_ID]},
        }
        response = call(dep, route, prefix, headers, body=body)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["rows"] == [] and payload["assets"] == []
        assert_nothing_from(payload, "government")
        gov_region = call(
            dep, route, prefix, headers, body={"filters": {"residency_regions": ["usgovvirginia"]}}
        )
        assert gov_region.status_code == 422, gov_region.text
        assert gov_region.json()["reason"] == "unknown_region"
    elif route.name == "dependents":
        response = call(
            dep,
            route,
            prefix,
            headers,
            body={"node_id": "government:contoso:foundry:agent:gov-svc", "max_depth": 2},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["groups"] == [] and payload["total"] == 0
        assert_nothing_from(payload, "government")
    else:
        response = call(dep, route, prefix, headers)
        assert response.status_code == 200, response.text
        names = {g["name"] for g in response.json()["groups"]}
        assert names, "a Commercial caller gets the Commercial groups"
        assert_nothing_from(response.json(), "usgov", "usdod")


@pytest.mark.parametrize(("route", "prefix"), VARIANTS)
def test_expired_assignment(aworld: AccessWorld, route: Route, prefix: str) -> None:
    dep = aworld.world["contoso"]
    aworld.world.clock.advance(11)  # the viewer assignment lapsed
    response = assert_denied(dep, route, prefix, bearer_for(dep, EXPIRED_OID))
    assert response.json()["reason"] == "permission_missing", response.text


@pytest.mark.parametrize(("route", "prefix"), VARIANTS)
def test_the_in_scope_control_is_served(aworld: AccessWorld, route: Route, prefix: str) -> None:
    """The same routes serve an in-scope viewer, so the refusals above are real."""
    dep = aworld.world["contoso"]
    before = audit_count(dep)
    response = call(dep, route, prefix, dep.bearer(VIEWER_FIN))
    assert response.status_code == 200, response.text
    assert audit_count(dep) == before + (1 if route.name in AUDITED else 0)
    if route.name == "query":
        assert {r["accessor_id"] for r in rows_of(response.json())} >= {FIN_AGENT_W, FIN_AGENT_R}


SCOPE_FIELDS: tuple[tuple[str, Any], ...] = (
    ("customer_id", "fabrikam"),
    ("tenant_id", "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"),
    ("cloud", "government"),
    ("domain_id", OPS_ID),
    ("domain_ids", [OPS_ID, HR_ID]),
    ("allowed_domains", [OPS_ID]),
    ("scope", {"customer_id": "fabrikam", "cloud": "government"}),
)


@pytest.mark.parametrize(("route", "prefix"), POST_VARIANTS)
@pytest.mark.parametrize(("field", "value"), SCOPE_FIELDS, ids=[f for f, _ in SCOPE_FIELDS])
def test_body_supplied_scope_is_refused(
    aworld: AccessWorld, route: Route, prefix: str, field: str, value: Any
) -> None:
    """Request models forbid extra fields (clarification 12): 422, nothing read or audited."""
    dep = aworld.world["contoso"]
    base = dict(route.body or {})
    attempts, audited = len(dep.recorder.attempts), audit_count(dep)
    response = call(dep, route, prefix, dep.bearer(VIEWER_FIN), body={**base, field: value})
    assert response.status_code == 422, response.text
    assert audit_count(dep) == audited, "a refused request wrote an audit record"
    assert len(dep.recorder.attempts) == attempts
    for fragment in ("fin-writer", "fin-reader", "ops-reader", "Asset customers"):
        assert fragment not in response.text, response.text


@pytest.mark.parametrize(("route", "prefix"), POST_VARIANTS)
def test_body_supplied_scope_does_not_reach_a_caller_without_a_role(
    aworld: AccessWorld, route: Route, prefix: str
) -> None:
    """Authorization runs before body validation: no role is a 403, never a 422 hint."""
    dep = aworld.world["contoso"]
    body = {**(route.body or {}), "customer_id": "fabrikam", "domain_id": FIN_ID}
    attempts = len(dep.recorder.attempts)
    response = call(dep, route, prefix, bearer_for(dep, NO_ROLE_OID), body=body)
    assert response.status_code == 403, response.text
    assert len(dep.recorder.attempts) == attempts + 1


@pytest.mark.parametrize(("route", "prefix"), VARIANTS)
def test_query_string_and_header_scope_is_ignored(
    aworld: AccessWorld, route: Route, prefix: str
) -> None:
    """The query-string (and header) equivalent of body scope fields changes nothing: the answer
    for a finance viewer is identical with and without them."""
    dep = aworld.world["contoso"]
    headers = dep.bearer(VIEWER_FIN)
    plain = call(dep, route, prefix, headers)
    attempts = len(dep.recorder.attempts)
    spoofed_headers = {
        **headers,
        "X-Customer-Id": "fabrikam",
        "X-Domain-Id": OPS_ID,
        "X-Cloud": "government",
    }
    spoofed = call(
        dep,
        route,
        prefix,
        spoofed_headers,
        params={
            "customer_id": "fabrikam",
            "cloud": "government",
            "domain_id": OPS_ID,
            "domain_ids": HR_ID,
        },
    )
    assert plain.status_code == spoofed.status_code == 200, spoofed.text
    assert spoofed.json() == plain.json()
    assert len(dep.recorder.attempts) == attempts
    # and nothing from the operations domain appears for a finance viewer
    if route.name == "query":
        assert_nothing_from(spoofed.json(), OPS_ASSET, "ops-reader")

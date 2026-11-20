"""ABAC negative suite for the agent match routes (PRP-72 item 5).

The suite world (``world.py``) serves the real router table, so the three match routes are
mounted. This module installs a real ``AgentMatcher`` (in-memory catalog, fixture search, in-memory
feedback store) on each deployment, additively, and asserts that EVERY route refuses, per dimension,
with a recorded denial and without reaching the matcher:

=====================================  ====================================================
Dimension                              Expected refusal
=====================================  ====================================================
no role (member of the domain only)    403 ``target_out_of_scope``
viewer without the path domain         403 (denied, recorded)
wrong domain (not in the caller's      403 (denied, recorded)
scope)
other customer (path names a domain    403 (denied, recorded)
of another customer)
other cloud (path names a domain in    403 (denied, recorded)
another cloud)
expired role assignment                403 ``target_out_of_scope``
=====================================  ====================================================

``test_agent_match_secrecy.py`` holds the leak test (task text and clear principal identifier).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.auth.scope import (
    PolicyRoleAssignment,
    PrincipalPolicy,
    Role,
    principal_document_id,
)
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.recommendations.matching import (
    AgentMatcher,
    InMemoryFeedbackStore,
    MatchSettings,
)
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.fixture.index import FixtureSearchIndex, documents_from_catalog

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

BASE = "/api/v1/recommendations/domains/{domain}/match"
FIN_ID = domain_id("contoso", "finance")
OPS_ID = domain_id("contoso", "operations")
FAB_FIN_ID = domain_id("fabrikam", "finance")
HR_ID = domain_id("contoso", "hr")
GOV_FIN_ID = domain_id("contoso", "finance", cloud="government")
VIEWER_FIN = Who("contoso", "finance", Role.VIEWER)
VIEWER_OPS = Who("contoso", "operations", Role.VIEWER)
VIEWER_FAB = Who("fabrikam", "finance", Role.VIEWER)
NO_ROLE_OID = "a1b2c3d4-0000-4000-8000-00000000f072"
EXPIRED_OID = "a1b2c3d4-0000-4000-8000-00000000f073"
_EXAMPLE = (
    Path(__file__).resolve().parents[3]
    / "packages/contracts/schemas/catalog/v1/examples/valid/agent.minimal-and-typical.json"
)

MATCH_BODY: dict[str, Any] = {"schema_version": "1.0.0", "task_text": "reconcile the invoices"}
FEEDBACK_BODY: dict[str, Any] = {
    "schema_version": "1.0.0",
    "match_id": "m-1",
    "entity_id": "commercial:contoso:foundry:agent:invoice-bot",
    "decision": "accepted",
}


@dataclass(frozen=True)
class Route:
    name: str
    method: str
    suffix: str
    body: dict[str, Any] | None

    def path(self, domain: str) -> str:
        return BASE.replace("{domain}", domain) + self.suffix


ROUTES: tuple[Route, ...] = (
    Route("match", "POST", "", MATCH_BODY),
    Route("feedback", "POST", "/feedback", FEEDBACK_BODY),
    Route("metrics", "GET", "/metrics", None),
)


def make_agent(name: str, domain: str, *, tags: Sequence[str], description: str) -> Agent:
    raw = json.loads(_EXAMPLE.read_text(encoding="utf-8"))
    raw.update(
        id=f"commercial:contoso:foundry:agent:{name}",
        customer_id="contoso",
        domain_id=domain_id("contoso", domain),
        current_version_id=None,
        external_agent_id=None,
        version=1,
        etag="caller-etag",
        display_name=f"Agent {name}",
        description=description,
        tags=list(tags),
        capabilities=["invoice.reconcile"],
        environment="production",
    )
    return Agent.model_validate(raw)


def writer_scope() -> IdentityScope:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": "commercial",
        "customer_id": "contoso",
        "principal": {
            "principal_id": "commercial:contoso:idp:person:p-writer",
            "principal_pseudonym": "p-writer",
            "principal_kind": "user",
        },
        "roles": [{"role": "viewer", "domain_ids": [FIN_ID, OPS_ID]}],
        "allowed_domains": [FIN_ID, OPS_ID],
        "allowed_resources": [],
        "policy_version": "v1",
        "derived_at": "2026-01-01T00:00:00Z",
        "scope_hash": "sha256:" + "ab" * 32,
    }
    return IdentityScope._from_verified_contract(ContractScope.model_validate(payload))


@dataclass
class MatchWorld:
    world: World
    feedback: InMemoryFeedbackStore
    calls: list[str]


class _SpyMatcher(AgentMatcher):
    """Counts how often a route reaches the matcher (a refusal must never get this far)."""

    calls: list[str]

    async def match_detailed(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("match")
        return await super().match_detailed(*args, **kwargs)

    async def record_feedback(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("feedback")
        return await super().record_feedback(*args, **kwargs)

    async def metrics(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("metrics")
        return await super().metrics(*args, **kwargs)


def install(world: World) -> MatchWorld:
    repo = InMemoryCatalogRepository()
    agents = [
        make_agent("invoice-bot", "finance", tags=["finance"], description="reconcile invoices"),
        make_agent("ops-bot", "operations", tags=["ops"], description="triage incidents"),
    ]
    docs = documents_from_catalog([a.model_dump(mode="json") for a in agents])
    search = FixtureSearchIndex(docs)
    store = InMemoryFeedbackStore()

    async def seed() -> None:
        for agent in agents:
            await repo.create_entity(writer_scope(), agent)

    run(seed())
    matcher = _SpyMatcher(
        search, RepositoryGraphQuery(repo, search), store, settings=MatchSettings()
    )
    matcher.calls = []
    for customer, dep in world.deployments.items():
        dep.app.state.agent_matcher = matcher
        dep.app.state.audit_repository = dep.audit_repo
        assert customer in TENANTS
    _seed(world["contoso"], NO_ROLE_OID, roles=())
    expiring = PolicyRoleAssignment(
        assignment_id="ra-expiring",
        role=Role.VIEWER,
        domain_ids=(FIN_ID,),
        expires_at=at(10),
    )
    _seed(world["contoso"], EXPIRED_OID, roles=(expiring,))
    return MatchWorld(world=world, feedback=store, calls=matcher.calls)


def _seed(dep: Deployment, object_id: str, *, roles: tuple[PolicyRoleAssignment, ...]) -> None:
    principal = pseudonymizer().principal_id(
        cloud=_commercial(), customer_id=dep.customer, tenant_id=TENANTS[dep.customer],
        object_id=object_id, kind="user",
    )  # fmt: skip
    dep.repo.put_principal(
        PrincipalPolicy(
            id=principal_document_id(principal),
            customer_id=dep.customer,
            principal_id=principal,
            domain_memberships=(FIN_ID,),
            role_assignments=roles,
        )
    )


def _commercial() -> Any:
    from neurosphere_core.cloud import CloudName

    return CloudName.COMMERCIAL


def bearer_for(dep: Deployment, object_id: str) -> dict[str, str]:
    token = dev_issuer(dep.customer).mint(audience=AUDIENCE, object_id=object_id, now=dep.clock.now)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mworld(world: World) -> MatchWorld:
    return install(world)


def call(dep: Deployment, route: Route, domain: str, headers: dict[str, str]) -> Any:
    return dep.client.request(route.method, route.path(domain), headers=headers, json=route.body)


def audit_count(dep: Deployment) -> int:
    return sum(1 for (_c, d) in dep.audit_store._docs if d != "tail")  # pyright: ignore[reportPrivateUsage]


def assert_denied(
    mw: MatchWorld,
    dep: Deployment,
    route: Route,
    domain: str,
    headers: dict[str, str],
    *,
    reason: str | None = None,
) -> None:
    attempts, audited = len(dep.recorder.attempts), audit_count(dep)
    response = call(dep, route, domain, headers)
    assert response.status_code == 403, f"{route.name}: {response.status_code} {response.text}"
    if reason is not None:
        assert response.json()["reason"] == reason, response.text
    assert len(dep.recorder.attempts) == attempts + 1, "no denial was recorded"
    assert audit_count(dep) == audited + 1, "the denial record was not persisted"
    assert mw.calls == [], "the matcher was reached by a refused request"
    assert dep.recorder.attempts[-1].reason == response.json()["reason"]


def test_every_route_in_the_inventory_has_a_case() -> None:
    from fastapi.routing import APIRoute
    from neurosphere_api.recommendations.match import PREFIX, build_router

    served = {
        (PREFIX + (r.path if r.path != "/" else ""), m)
        for r in build_router().routes
        if isinstance(r, APIRoute)
        for m in sorted(r.methods or ())
    }
    cases = {(BASE + r.suffix, r.method) for r in ROUTES}
    assert served == cases


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_no_role(mworld: MatchWorld, route: Route) -> None:
    dep = mworld.world["contoso"]
    assert_denied(
        mworld, dep, route, FIN_ID, bearer_for(dep, NO_ROLE_OID), reason="target_out_of_scope"
    )


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_viewer_without_the_domain(mworld: MatchWorld, route: Route) -> None:
    dep = mworld.world["contoso"]
    assert_denied(mworld, dep, route, FIN_ID, dep.bearer(VIEWER_OPS))


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_wrong_domain(mworld: MatchWorld, route: Route) -> None:
    dep = mworld.world["contoso"]
    assert_denied(mworld, dep, route, HR_ID, dep.bearer(VIEWER_FIN))
    assert_denied(mworld, dep, route, OPS_ID, dep.bearer(VIEWER_FIN))


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_other_customer(mworld: MatchWorld, route: Route) -> None:
    fab = mworld.world["fabrikam"]
    assert_denied(mworld, fab, route, FIN_ID, fab.bearer(VIEWER_FAB))
    # A fabrikam viewer is fine on fabrikam's own domain, so the refusal above is the customer.
    own = call(fab, route, FAB_FIN_ID, fab.bearer(VIEWER_FAB))
    assert own.status_code != 403, own.text


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_other_cloud(mworld: MatchWorld, route: Route) -> None:
    dep = mworld.world["contoso"]
    assert_denied(mworld, dep, route, GOV_FIN_ID, dep.bearer(VIEWER_FIN))


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_expired_scope(mworld: MatchWorld, route: Route) -> None:
    dep = mworld.world["contoso"]
    headers = bearer_for(dep, EXPIRED_OID)
    mworld.world.clock.advance(11)  # the viewer assignment lapsed
    headers = bearer_for(dep, EXPIRED_OID)
    assert_denied(mworld, dep, route, FIN_ID, headers, reason="target_out_of_scope")


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_an_in_scope_viewer_reaches_the_matcher(mworld: MatchWorld, route: Route) -> None:
    """The control: the same routes accept an in-scope viewer, so the denials above are real."""
    dep = mworld.world["contoso"]
    if route.name == "feedback":
        return  # needs a stored match; covered by the secrecy test's flow
    response = call(dep, route, FIN_ID, dep.bearer(VIEWER_FIN))
    assert response.status_code == 200, response.text
    assert mworld.calls == [route.name]

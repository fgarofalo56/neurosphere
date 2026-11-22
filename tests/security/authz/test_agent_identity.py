"""ABAC negative suite for the agent identity routes (PRP-137 item 5).

The suite world serves the real router table, so both routes are mounted; this module installs the
agent identity plane over an in-memory catalog on each deployment.

==================================  ==========================================================
Dimension                           Expected result
==================================  ==========================================================
steward of the path domain          PUT 200 (``catalog.curate`` in that domain)
viewer / analyst / admin / auditor  PUT 403 and a denial record (no ``catalog.curate``)
steward of another domain           PUT 403 and a denial record
expired steward                     PUT 403 and a denial record
viewer of the path domain           GET 200; viewer of another domain GET 403
target agent of another domain      indistinguishable from a missing target (same 404)
other customer                      cannot reach the first customer's catalog (404/403)
audit records                       ids and reason codes, never the external agent id
app boot                            passes ``verify_route_permissions`` with the new routes
==================================  ==========================================================
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from neurosphere_api.agent_identity import AgentIdentityPlane, configure_agent_identity
from neurosphere_api.authz.routes import route_inventory, verify_route_permissions
from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.auth.scope import (
    PolicyRoleAssignment,
    PrincipalPolicy,
    Role,
    principal_document_id,
)
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.scope import IdentityScope

from .test_admin_connectors import _bearer  # pyright: ignore[reportPrivateUsage]
from .test_admin_identity import pid_of
from .world import Deployment, Who, World, at, domain_id, run

_VALID = (
    Path(__file__).resolve().parents[3] / "packages/contracts/schemas/catalog/v1/examples/valid"
)
BASE = "/api/v1/agent-identity/domains"
EXPIRED_STEWARD_OID = "a1b2c3d4-0000-4000-8000-00000000f137"
EXTERNAL = "0f1e2d3c-4b5a-4968-8776-655443322110"
DENIED_ROLES = (Role.VIEWER, Role.ANALYST, Role.ADMIN, Role.SECURITY_AUDITOR)


def _agent_id(customer: str, name: str) -> str:
    return f"commercial:{customer}:foundry:agent:{name}"


def _seed_scope(customer: str) -> IdentityScope:
    domains = [domain_id(customer, "finance"), domain_id(customer, "operations")]
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": "commercial",
        "customer_id": customer,
        "principal": {
            "principal_id": f"commercial:{customer}:idp:person:seed",
            "principal_pseudonym": "p-0001",
            "principal_kind": "user",
        },
        "roles": [{"role": "viewer", "domain_ids": domains}],
        "allowed_domains": domains,
        "allowed_resources": [],
        "policy_version": "v1",
        "derived_at": "2026-01-01T00:00:00Z",
        "scope_hash": "sha256:" + hashlib.sha256(b"seed").hexdigest(),
    }
    return IdentityScope._from_verified_contract(  # pyright: ignore[reportPrivateUsage]
        ContractScope.model_validate(payload)
    )


def _agent(customer: str, name: str, domain: str) -> Agent:
    raw = json.loads((_VALID / "agent.minimal-and-typical.json").read_text(encoding="utf-8"))
    raw.update(
        id=_agent_id(customer, name),
        customer_id=customer,
        domain_id=domain_id(customer, domain),
        current_version_id=None,
        external_agent_id=None,
        version=1,
        etag="caller-etag",
        display_name=f"Agent {name}",
    )
    return Agent.model_validate(raw)


def _audit_count(dep: Deployment) -> int:
    return sum(1 for (_c, d) in dep.audit_store._docs if d != "tail")  # pyright: ignore[reportPrivateUsage]


def _body(customer: str, name: str = "finance-one", external: str = "asst-1") -> dict[str, str]:
    return {
        "source_id": "foundry",
        "external_agent_id": external,
        "target_agent_id": _agent_id(customer, name),
    }


@pytest.fixture
def aworld(world: World) -> World:
    for dep in world.deployments.values():
        repo = InMemoryCatalogRepository()
        scope = _seed_scope(dep.customer)
        for name, domain in (("finance-one", "finance"), ("ops-one", "operations")):
            run(repo.create_entity(scope, _agent(dep.customer, name, domain)))
        configure_agent_identity(dep.app, AgentIdentityPlane(repository=repo))
        fin = domain_id(dep.customer, "finance")
        dep.repo.put_principal(
            PrincipalPolicy(
                id=principal_document_id(pid_of(EXPIRED_STEWARD_OID, dep.customer)),
                customer_id=dep.customer,
                principal_id=pid_of(EXPIRED_STEWARD_OID, dep.customer),
                domain_memberships=(fin,),
                role_assignments=(
                    PolicyRoleAssignment(
                        assignment_id="ra-expiring",
                        role=Role.DOMAIN_STEWARD,
                        domain_ids=(fin,),
                        expires_at=at(10),
                    ),
                ),
            )
        )
    return world


def _put(dep: Deployment, who: Who, path_domain: str, body: dict[str, str]) -> Any:
    return dep.client.put(
        f"{BASE}/{domain_id(dep.customer, path_domain)}/aliases", json=body, headers=dep.bearer(who)
    )


def _denied(dep: Deployment, call: Any) -> None:
    audited = _audit_count(dep)
    attempts = len(dep.recorder.attempts)
    response = call()
    assert response.status_code == 403, f"{response.status_code} {response.text}"
    assert len(dep.recorder.attempts) == attempts + 1, "no denial was recorded"
    assert _audit_count(dep) == audited + 1, "the denial record was not persisted"


def test_the_steward_of_the_domain_writes(aworld: World) -> None:
    dep = aworld["contoso"]
    steward = Who("contoso", "finance", Role.DOMAIN_STEWARD)
    response = _put(dep, steward, "finance", _body("contoso"))
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "created"
    assert response.json()["reresolve_needed"] is True


@pytest.mark.parametrize("role", DENIED_ROLES, ids=lambda r: r.value)
def test_roles_without_catalog_curate_are_denied_and_recorded(aworld: World, role: Role) -> None:
    dep = aworld["contoso"]
    who = Who("contoso", "finance", role)
    _denied(dep, lambda: _put(dep, who, "finance", _body("contoso")))


def test_a_steward_of_another_domain_is_denied_and_recorded(aworld: World) -> None:
    dep = aworld["contoso"]
    other = Who("contoso", "operations", Role.DOMAIN_STEWARD)
    _denied(dep, lambda: _put(dep, other, "finance", _body("contoso")))


def test_an_expired_steward_is_denied_and_recorded(aworld: World) -> None:
    dep = aworld["contoso"]
    url = f"{BASE}/{domain_id('contoso', 'finance')}/aliases"
    headers = _bearer(dep, EXPIRED_STEWARD_OID)
    assert dep.client.put(url, json=_body("contoso"), headers=headers).status_code == 200
    aworld.clock.advance(11)
    _denied(dep, lambda: dep.client.put(url, json=_body("contoso", external="x2"), headers=headers))


def test_the_viewer_of_the_domain_reads_and_another_domains_viewer_does_not(aworld: World) -> None:
    dep = aworld["contoso"]
    steward = Who("contoso", "finance", Role.DOMAIN_STEWARD)
    assert _put(dep, steward, "finance", _body("contoso")).status_code == 200
    url = f"{BASE}/{domain_id('contoso', 'finance')}/aliases"
    params = {"source_id": "foundry", "external_agent_id": "asst-1"}
    viewer = Who("contoso", "finance", Role.VIEWER)
    read = dep.client.get(url, params=params, headers=dep.bearer(viewer))
    assert read.status_code == 200 and read.json()["target_agent_id"].endswith(":finance-one")
    outsider = Who("contoso", "operations", Role.VIEWER)
    _denied(dep, lambda: dep.client.get(url, params=params, headers=dep.bearer(outsider)))


def test_a_target_in_another_domain_is_the_same_404_as_a_missing_target(aworld: World) -> None:
    dep = aworld["contoso"]
    steward = Who("contoso", "finance", Role.DOMAIN_STEWARD)
    other = _put(dep, steward, "finance", _body("contoso", name="ops-one"))
    missing = _put(dep, steward, "finance", _body("contoso", name="nothing-here"))
    assert other.status_code == missing.status_code == 404
    assert other.json()["reason"] == missing.json()["reason"]
    assert other.json()["detail"] == missing.json()["detail"]
    assert "ops-one" not in other.text


def test_a_target_of_another_customer_is_the_same_404(aworld: World) -> None:
    dep = aworld["contoso"]
    steward = Who("contoso", "finance", Role.DOMAIN_STEWARD)
    foreign = _put(dep, steward, "finance", _body("fabrikam"))
    missing = _put(dep, steward, "finance", _body("contoso", name="nothing-here"))
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["reason"] == missing.json()["reason"]


def test_the_other_customer_does_not_see_the_alias(aworld: World) -> None:
    contoso, fabrikam = aworld["contoso"], aworld["fabrikam"]
    steward = Who("contoso", "finance", Role.DOMAIN_STEWARD)
    assert _put(contoso, steward, "finance", _body("contoso")).status_code == 200
    viewer = Who("fabrikam", "finance", Role.VIEWER)
    read = fabrikam.client.get(
        f"{BASE}/{domain_id('fabrikam', 'finance')}/aliases",
        params={"source_id": "foundry", "external_agent_id": "asst-1"},
        headers=fabrikam.bearer(viewer),
    )
    assert read.status_code == 404


def test_audit_records_carry_no_event_content(aworld: World) -> None:
    dep = aworld["contoso"]
    steward = Who("contoso", "finance", Role.DOMAIN_STEWARD)
    body = _body("contoso", external=EXTERNAL)
    body["reason"] = "renamed_in_foundry"
    assert _put(dep, steward, "finance", body).status_code == 200
    docs = [d for (_c, k), d in dep.audit_store._docs.items() if k != "tail"]  # pyright: ignore[reportPrivateUsage]
    text = json.dumps(docs, default=str)
    assert "agent_identity.alias_declare" in text
    assert EXTERNAL not in text


def test_the_app_boots_under_verify_route_permissions(aworld: World) -> None:
    dep = aworld["contoso"]
    verify_route_permissions(dep.app)
    found = {
        (e.path, m): e.permissions
        for e in route_inventory(dep.app)
        if e.path.startswith("/api/v1/agent-identity")
        for m in e.methods
    }
    path = "/api/v1/agent-identity/domains/{domain}/aliases"
    assert found == {(path, "PUT"): ("catalog.curate",), (path, "GET"): ("data.read",)}


def test_an_unconfigured_plane_is_503_after_authorization(aworld: World) -> None:
    dep = aworld["contoso"]
    configure_agent_identity(dep.app, None)
    steward = Who("contoso", "finance", Role.DOMAIN_STEWARD)
    assert _put(dep, steward, "finance", _body("contoso")).status_code == 503
    viewer = Who("contoso", "finance", Role.VIEWER)
    _denied(dep, lambda: _put(dep, viewer, "finance", _body("contoso")))

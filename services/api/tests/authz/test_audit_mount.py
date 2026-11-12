"""Item 4's audit router mounted behind ``require`` via ``audit_require_permission``."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_api.audit import ROUTE_PREFIX, build_router, register
from neurosphere_api.authz import (
    audit_require_permission,
    domain_from_chain_id,
    route_inventory,
    undeclared_routes,
)
from neurosphere_api.routers import RouterRegistry
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import Role, compute_scope_hash
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.scope import IdentityScope

from .authz_helpers import ALICE, CAROL, FINANCE, Harness, harness, policy, role

#: PRP-31 item 14b: domains with non-``catalog`` source segments (the seed mints
#: ``sandbox:domain:dom-00N``; the kill-switch runbook uses ``neurosphere:domain:*``).
SANDBOX_DOM = "commercial:contoso:sandbox:domain:dom-001"
NEURO_DOM = "commercial:contoso:neurosphere:domain:customer-control"
#: Same last segment as FINANCE under another source: before 14b both wrote ``contoso.finance``.
SANDBOX_FINANCE = "commercial:contoso:sandbox:domain:finance"

SBX_AUDITOR = "82c34e45-7abf-42c7-9987-853d978bbbd7"
NEURO_AUDITOR = "b535cc08-b156-4677-af2c-4da6a887a0c3"
#: security_auditor of SANDBOX_FINANCE only: must never read FINANCE's ``contoso.finance``.
SBX_FINANCE_AUDITOR = "78b1b711-015a-49dc-a0e1-7928487e5edc"
#: security_auditor of both FINANCE and SANDBOX_FINANCE: reads both, each on its own chain.
BOTH_FINANCE_AUDITOR = "2c66d260-4850-4112-9ecd-7c526d2a35c3"

SBX_CHAIN = "contoso._7.sandbox.dom-001"
NEURO_CHAIN = "contoso._11.neurosphere.customer-control"
SBX_FINANCE_CHAIN = "contoso._7.sandbox.finance"

POLICIES = (
    policy(ALICE, role(Role.VIEWER, FINANCE)),
    policy(CAROL, role(Role.SECURITY_AUDITOR, FINANCE)),
    policy(SBX_AUDITOR, role(Role.SECURITY_AUDITOR, SANDBOX_DOM), memberships=(SANDBOX_DOM,)),
    policy(NEURO_AUDITOR, role(Role.SECURITY_AUDITOR, NEURO_DOM), memberships=(NEURO_DOM,)),
    policy(
        SBX_FINANCE_AUDITOR,
        role(Role.SECURITY_AUDITOR, SANDBOX_FINANCE),
        memberships=(SANDBOX_FINANCE,),
    ),
    policy(
        BOTH_FINANCE_AUDITOR,
        role(Role.SECURITY_AUDITOR, FINANCE, SANDBOX_FINANCE),
        memberships=(FINANCE, SANDBOX_FINANCE),
    ),
)


def _audit_harness() -> Harness:
    factory = audit_require_permission(chain_domain=domain_from_chain_id)
    h = harness(*POLICIES, routers={ROUTE_PREFIX: build_router(require_permission=factory)})
    h.app.state.audit_repository = AuditRepository(InMemoryAuditStore())
    return h


# (principal, chain, endpoint, status, reason)
CASES: list[tuple[str | None, str, str, int, str | None]] = [
    (None, "contoso.finance", "records", 401, "missing_token"),
    (CAROL, "contoso.finance", "records", 200, None),
    (CAROL, "contoso.finance", "verify", 200, None),
    (CAROL, "contoso.hr", "records", 403, "target_out_of_scope"),  # no customer-level fallback
    (CAROL, "fabrikam.finance", "verify", 403, "audit_chain_out_of_scope"),
    (CAROL, "contosox.finance", "verify", 403, "audit_chain_out_of_scope"),
    (CAROL, "contoso", "records", 403, "audit_chain_out_of_scope"),
    (CAROL, "contoso.", "records", 403, "audit_chain_out_of_scope"),
    (CAROL, "contoso.Not_A_Domain", "records", 403, "target_unresolved"),  # off-convention: deny
    (ALICE, "contoso.finance", "records", 403, "target_out_of_scope"),
    # PRP-31 item 14b: every source is readable on its own, source-qualified chain.
    (SBX_AUDITOR, SBX_CHAIN, "records", 200, None),
    (SBX_AUDITOR, SBX_CHAIN, "verify", 200, None),
    (NEURO_AUDITOR, NEURO_CHAIN, "records", 200, None),
    (NEURO_AUDITOR, NEURO_CHAIN, "verify", 200, None),
    (SBX_FINANCE_AUDITOR, SBX_FINANCE_CHAIN, "records", 200, None),
    (BOTH_FINANCE_AUDITOR, "contoso.finance", "records", 200, None),
    (BOTH_FINANCE_AUDITOR, SBX_FINANCE_CHAIN, "verify", 200, None),
    # Same name, other source: the legacy chain is the catalog domain's, never the sandbox one.
    (SBX_FINANCE_AUDITOR, "contoso.finance", "records", 403, "target_out_of_scope"),
    (SBX_FINANCE_AUDITOR, "contoso.finance", "verify", 403, "target_out_of_scope"),
    (CAROL, SBX_FINANCE_CHAIN, "records", 403, "target_out_of_scope"),
    # Unheld domains, any source.
    (SBX_AUDITOR, NEURO_CHAIN, "records", 403, "target_out_of_scope"),
    (NEURO_AUDITOR, SBX_CHAIN, "verify", 403, "target_out_of_scope"),
    # The pre-14b aliased chain of a sandbox domain maps to the catalog domain: not readable.
    (SBX_AUDITOR, "contoso.dom-001", "records", 403, "target_out_of_scope"),
    # Another customer; non-canonical spellings of the qualified form.
    (SBX_AUDITOR, "fabrikam._7.sandbox.dom-001", "records", 403, "audit_chain_out_of_scope"),
    (SBX_AUDITOR, "contoso._07.sandbox.dom-001", "records", 403, "target_unresolved"),
    (SBX_AUDITOR, "contoso._8.sandbox.dom-001", "records", 403, "target_unresolved"),
    (CAROL, "contoso._7.catalog.finance", "records", 403, "target_unresolved"),
]


@pytest.mark.parametrize(("who", "chain", "endpoint", "status", "reason"), CASES)
def test_audit_routes_behind_require(
    who: str | None, chain: str, endpoint: str, status: int, reason: str | None
) -> None:
    h = _audit_harness()
    headers = h.auth(who) if who else {}
    response = h.client.get(f"{ROUTE_PREFIX}/chains/{chain}/{endpoint}", headers=headers)
    assert response.status_code == status, response.text
    if reason is not None:
        assert response.json()["reason"] == reason


def test_audit_routes_declare_permissions() -> None:
    h = _audit_harness()
    assert undeclared_routes(h.app) == ()
    audit = [e for e in route_inventory(h.app) if e.path.startswith(f"{ROUTE_PREFIX}/chains/")]
    assert len(audit) == 2
    assert all(e.permissions == ("audit.read",) for e in audit)


def test_register_hook_accepts_the_adapter() -> None:
    registry = RouterRegistry()
    register(
        registry, require_permission=audit_require_permission(chain_domain=domain_from_chain_id)
    )
    # The successor prefix and its deprecated alias (PRP-29 item 4).
    assert registry.prefixes == (ROUTE_PREFIX, "/audit")


def test_unknown_audit_permission_fails_at_mount() -> None:
    with pytest.raises(InvalidSchemaError):
        audit_require_permission(chain_domain=domain_from_chain_id)("audit.write")


def test_a_domain_mapper_is_mandatory() -> None:
    with pytest.raises(TypeError):
        audit_require_permission()  # type: ignore[call-arg]


@pytest.mark.parametrize("endpoint", ["records", "verify"])
def test_default_app_mounts_audit_and_fails_closed_until_configured(endpoint: str) -> None:
    from fastapi.testclient import TestClient
    from neurosphere_api.app import create_app
    from neurosphere_core.cloud import Settings

    client = TestClient(create_app(Settings(env="local")), raise_server_exceptions=False)
    for headers in ({}, {"Authorization": "Bearer not-a-token"}):
        response = client.get(f"{ROUTE_PREFIX}/chains/contoso.hr/{endpoint}", headers=headers)
        assert response.status_code == 503


# --------------------------------------------------------------------------- the mapper itself


def _scope(cloud: str = "commercial", *roles: tuple[str, tuple[str, ...]]) -> IdentityScope:
    """A contract scope built through the test hook, so it may name ids derivation would drop."""
    doc: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": cloud,
        "customer_id": "contoso",
        "principal": {
            "principal_id": f"{cloud}:contoso:entra:person:p-0123456789abcdef",
            "principal_pseudonym": "p-0123456789abcdef",
            "principal_kind": "user",
        },
        "roles": [{"role": r, "domain_ids": list(ds)} for r, ds in roles],
        "allowed_domains": [],
        "allowed_resources": [],
        "policy_version": "2026.10.01-1",
        "derived_at": "2026-10-10T00:00:00Z",
    }
    doc["scope_hash"] = compute_scope_hash(doc)
    contract = ContractScope.model_validate(doc)
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    ("chain", "domain"),
    [
        ("contoso.finance", FINANCE),
        (SBX_CHAIN, SANDBOX_DOM),
        (NEURO_CHAIN, NEURO_DOM),
        (SBX_FINANCE_CHAIN, SANDBOX_FINANCE),
    ],
    ids=["catalog", "sandbox", "neurosphere", "sandbox-finance"],
)
def test_each_source_maps_to_exactly_one_domain_regardless_of_grants(
    chain: str, domain: str
) -> None:
    # The mapping never consults grants: a scope holding nothing, or holding a same-named domain
    # of another source, gets the same answer; the permission check on that domain decides.
    for scope in (_scope(), _scope("commercial", ("viewer", (SANDBOX_FINANCE, FINANCE)))):
        assert domain_from_chain_id(scope, chain) == domain


def test_the_cloud_comes_from_the_scope() -> None:
    gov = _scope("government")
    assert domain_from_chain_id(gov, SBX_CHAIN) == "government:contoso:sandbox:domain:dom-001"


@pytest.mark.parametrize(
    "chain",
    ["fabrikam.finance", "contosox.finance", "contoso", "contoso.", "contoso.Finance", "finance"],
)
def test_chains_outside_the_convention_or_customer_are_denied(chain: str) -> None:
    assert domain_from_chain_id(_scope(), chain) is None

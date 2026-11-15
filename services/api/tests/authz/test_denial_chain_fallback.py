"""Audit-chain hardening on the API side (PRP-48 item 5, #206 items 1-3).

* #206.1: a dotted ``NS_AUTH_CUSTOMER_ID`` fails the ``authz`` component at boot.
* #206.2: a denial targeting a member domain whose chain cannot be encoded is recorded on
  ``<customer>.authz-denials``, never a 503.
* #206.3: the reserved chain names equal the constants that name each customer-level chain.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends
from neurosphere_api.actions.emergency import control_chain_id
from neurosphere_api.admin.identity.plane import identity_admin_chain
from neurosphere_api.audit.access import DENIALS_CHAIN_NAME
from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.deploy.scan.audit import audit_chain as deploy_chain_id
from neurosphere_api.gateway.service import audit_chain_id as gateway_chain_id
from neurosphere_api.mcp.admin.service import audit_chain_id as mcp_admin_chain_id
from neurosphere_api.runtime.builders.authz import DENIAL_CHAIN_NAME, AuditDenialRecorder
from neurosphere_core.admin import admin_config_chain_id
from neurosphere_core.audit import RESERVED_CHAIN_NAMES, AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import Permission, Role
from neurosphere_core.scope import IdentityScope

from .authz_helpers import ALICE, CUSTOMER, FINANCE, FakeClock, harness, policy, role

#: Canonical catalog domains whose chain cannot be encoded: a reserved name, and a name with a
#: character legal in a domain id but not in a chain id.
RESERVED_DOMAIN = f"commercial:{CUSTOMER}:catalog:domain:gateway"
UNENCODABLE_DOMAIN = f"commercial:{CUSTOMER}:catalog:domain:fin=1"
DENIALS = f"{CUSTOMER}.authz-denials"


Managed = Annotated[
    IdentityScope, Depends(require(Permission.CONFIG_MANAGE, domain_from_path("domain_id")))
]


def _router() -> APIRouter:
    router = APIRouter()

    @router.put("/domains/{domain_id}/settings")
    async def settings(domain_id: str, scope: Managed) -> dict[str, Any]:
        return {}

    return router


def test_reserved_names_are_pinned_to_the_chain_constants() -> None:
    names = {
        chain.removeprefix(f"{CUSTOMER}.")
        for chain in (
            f"{CUSTOMER}.{DENIAL_CHAIN_NAME}",
            f"{CUSTOMER}.{DENIALS_CHAIN_NAME}",
            gateway_chain_id(CUSTOMER),
            control_chain_id(CUSTOMER),
            deploy_chain_id(CUSTOMER),
            mcp_admin_chain_id(CUSTOMER),
            admin_config_chain_id(CUSTOMER),
            identity_admin_chain(CUSTOMER),
        )
    }
    assert names == RESERVED_CHAIN_NAMES


@pytest.mark.parametrize("domain", [RESERVED_DOMAIN, UNENCODABLE_DOMAIN])
def test_unencodable_member_domain_denial_lands_on_the_customer_chain(domain: str) -> None:
    repository = AuditRepository(InMemoryAuditStore())
    h = harness(
        policy(ALICE, role(Role.VIEWER, FINANCE, domain), memberships=(FINANCE, domain)),
        routers={"/t": _router()},
        denials=AuditDenialRecorder(lambda: repository),
    )
    url = f"/t/domains/{domain}/settings"
    response = h.client.put(url, headers=h.auth(ALICE))
    assert response.status_code == 403, response.text  # never 503 audit_write_failed
    assert response.json()["reason"] == "target_out_of_scope"
    records = asyncio.run(repository.read_range(DENIALS, start=0))
    assert len(records) == 1
    assert records[0].kind == "denied"


def test_encodable_member_domain_denial_stays_on_the_domain_chain() -> None:
    repository = AuditRepository(InMemoryAuditStore())
    h = harness(
        policy(ALICE, role(Role.VIEWER, FINANCE)),
        routers={"/t": _router()},
        denials=AuditDenialRecorder(lambda: repository),
    )
    response = h.client.put(f"/t/domains/{FINANCE}/settings", headers=h.auth(ALICE))
    assert response.status_code == 403
    assert len(asyncio.run(repository.read_range(f"{CUSTOMER}.finance", start=0))) == 1
    assert asyncio.run(repository.read_range(DENIALS, start=0)) == []


def test_dotted_customer_id_fails_authz_at_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
        builders_with_stubs,
        compose,
        configure_auth_env,
        configured_overrides,
    )

    configure_auth_env(monkeypatch, CUSTOMER_ID="contoso.eu")
    clock = FakeClock()
    composed = compose(configured_overrides(clock), builders=builders_with_stubs(), clock=clock)
    status = composed.registry.get("authz")
    assert (status.state, status.reason) == ("failed", "customer_id_invalid")

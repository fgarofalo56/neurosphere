"""PRP-40 item 4: ``GET /api/v1/audit/denials`` needs a customer-wide auditor."""

from __future__ import annotations

import pytest
from neurosphere_api.audit.access import DENIALS_CHAIN_NAME
from neurosphere_api.runtime.builders.authz import DENIAL_CHAIN_NAME

from .audit_api_helpers import AUDITOR_ALL, AUDITOR_FO, STEWARD, World, make_world, seed

DENIALS = "/api/v1/audit/denials"


@pytest.fixture
async def world() -> World:
    w = make_world()
    await seed(w)
    return w


def test_chain_name_matches_the_recorder() -> None:
    assert DENIALS_CHAIN_NAME == DENIAL_CHAIN_NAME


async def test_customer_wide_auditor_reads_the_denials_chain(world: World) -> None:
    response = world.get(AUDITOR_ALL, DENIALS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [r["kind"] for r in body["items"]] == ["denied", "denied"]
    assert {r["chain_id"] for r in body["items"]} == {"contoso.authz-denials"}
    assert body["next_cursor"] is None


async def test_paging(world: World) -> None:
    first = world.get(AUDITOR_ALL, DENIALS, page_size=1).json()
    assert len(first["items"]) == 1 and first["next_cursor"] == "1"
    second = world.get(AUDITOR_ALL, DENIALS, page_size=1, cursor=first["next_cursor"]).json()
    assert second["items"][0]["sequence"] == 1 and second["next_cursor"] is None


async def test_domain_only_auditor_gets_customer_scope_required(world: World) -> None:
    response = world.get(AUDITOR_FO, DENIALS)
    assert response.status_code == 403
    assert response.json()["reason"] == "customer_scope_required"
    attempt = world.denials.attempts[-1]
    assert (attempt.permission, attempt.reason) == ("audit.read", "customer_scope_required")


async def test_caller_without_audit_read_is_403(world: World) -> None:
    response = world.get(STEWARD, DENIALS)
    assert response.status_code == 403
    assert response.json()["reason"] == "permission_missing"


async def test_no_chain_id_parameter_is_honoured(world: World) -> None:
    response = world.get(AUDITOR_ALL, DENIALS, chain_id="contoso.finance")
    assert {r["chain_id"] for r in response.json()["items"]} == {"contoso.authz-denials"}

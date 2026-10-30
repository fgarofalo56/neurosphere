"""PRP-31 item 2: the audit domain list, records and verify adapters derive the chain server-side,
work for an auditor with no ``data.read`` and refuse cross-customer and cross-domain reads."""

from __future__ import annotations

import asyncio

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    HR,
    OPERATIONS,
)
from neurosphere_api.ui_adapters.audit import auditable_chain
from neurosphere_core.audit import ChainVerification

from .adapter_support import (
    ALIASING_FINANCE,
    AUDITOR,
    AUDITOR_BOTH,
    AUDITOR_FOREIGN,
    AUDITOR_READER,
    OTHER_CUSTOMER_FINANCE,
    STEWARD,
    VIEWER,
    World,
    agent_doc,
    domain_doc,
    make_edge,
    make_world,
)

BASE = "/api/v1/audit/domains"


def _decide(world: World, times: int = 1) -> None:
    """Write real FINANCE audit records through the curation adapter (``channel=button``)."""
    world.seed(agent_doc("fin-a", FINANCE), agent_doc("fin-b", FINANCE))
    (edge,) = world.seed_edges(make_edge("e-fin", "fin-a", "fin-b", FINANCE))
    path = f"/api/v1/catalog/domains/{FINANCE}/curation/edges/{edge.id}/decisions"
    for _ in range(times):
        body = {
            "decision": "accept",
            "reason": "steward accept",
            "expected_edge_version": edge.version.root,
            "expected_edge_etag": edge.etag.root,
        }
        response = world.post(STEWARD, path, body)
        assert response.status_code == 201


@pytest.fixture
def world() -> World:
    return make_world()


# --------------------------------------------------------------------------- domain list


def test_auditor_without_data_read_gets_403_from_me_domains_but_lists_audit_domains(
    world: World,
) -> None:
    assert world.get(AUDITOR, "/api/v1/me/domains").status_code == 403
    response = world.get(AUDITOR, BASE)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [
            {"domain_id": FINANCE, "display_name": "Finance", "display_name_source": "derived"}
        ]
    }


def test_list_is_sorted_and_limited_to_audit_read_domains(world: World) -> None:
    response = world.get(AUDITOR_BOTH, BASE)
    assert response.status_code == 200, response.text
    assert [i["domain_id"] for i in response.json()["items"]] == [FINANCE, OPERATIONS]
    assert HR not in {i["domain_id"] for i in response.json()["items"]}


def test_list_uses_catalog_names_the_caller_can_read(world: World) -> None:
    world.seed(domain_doc(FINANCE, "Finance & Billing"))
    world.h.app.state.catalog_repository = world.repo
    # The auditor holds no data.read: the repository shows them nothing, so the label is derived.
    auditor = world.get(AUDITOR, BASE).json()["items"]
    assert auditor[0]["display_name_source"] == "derived"
    # A caller who also holds data.read there sees the catalog's name.
    reader = world.get(AUDITOR_READER, BASE)
    assert reader.status_code == 200, reader.text
    assert reader.json()["items"] == [
        {
            "domain_id": FINANCE,
            "display_name": "Finance & Billing",
            "display_name_source": "catalog",
        }
    ]


@pytest.mark.parametrize("who", [VIEWER, STEWARD])
def test_list_is_403_without_audit_read(world: World, who: str) -> None:
    response = world.get(who, BASE)
    assert response.status_code == 403
    assert response.json()["reason"] == "permission_missing"


def test_list_is_403_when_only_foreign_or_aliasing_domains_are_held(world: World) -> None:
    response = world.get(AUDITOR_FOREIGN, BASE)
    assert response.status_code == 403, response.text


def test_list_is_401_without_a_token(world: World) -> None:
    assert world.get(None, BASE).status_code == 401


# --------------------------------------------------------------------------- records / verify


def test_auditor_reads_records_derived_from_the_path_domain(world: World) -> None:
    _decide(world)
    response = world.get(AUDITOR, f"{BASE}/{FINANCE}/records")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [i["kind"] for i in items] == ["before", "after"]
    assert {i["channel"] for i in items} == {"button"}
    assert response.json()["next_cursor"] is None


def test_records_page_by_sequence_cursor(world: World) -> None:
    _decide(world, times=2)  # four records: before/after twice
    first = world.get(AUDITOR, f"{BASE}/{FINANCE}/records", params={"page_size": 3})
    assert first.status_code == 200, first.text
    assert len(first.json()["items"]) == 3
    cursor = first.json()["next_cursor"]
    assert cursor == "3"
    rest = world.get(
        AUDITOR, f"{BASE}/{FINANCE}/records", params={"page_size": 3, "cursor": cursor}
    )
    assert rest.status_code == 200, rest.text
    assert len(rest.json()["items"]) == 1
    assert rest.json()["next_cursor"] is None


def test_verify_returns_the_chain_verification_unchanged(world: World) -> None:
    _decide(world)
    response = world.get(AUDITOR, f"{BASE}/{FINANCE}/verify")
    assert response.status_code == 200, response.text
    expected = asyncio.run(world.audit.verify("contoso.finance"))
    assert ChainVerification.model_validate(response.json()) == expected
    assert response.json()["ok"] is True
    assert response.json()["chain_id"] == "contoso.finance"


def test_verify_matches_the_chain_route(world: World) -> None:
    _decide(world)
    adapter = world.get(AUDITOR, f"{BASE}/{FINANCE}/verify")
    chain = world.get(AUDITOR, "/api/v1/audit/chains/contoso.finance/verify")
    assert adapter.status_code == chain.status_code == 200
    assert adapter.json() == chain.json()


@pytest.mark.parametrize("endpoint", ["records", "verify"])
@pytest.mark.parametrize(
    ("who", "domain", "reason"),
    [
        (AUDITOR, OPERATIONS, "target_out_of_scope"),  # cross-domain
        (AUDITOR, HR, "target_out_of_scope"),
        (AUDITOR, OTHER_CUSTOMER_FINANCE, "audit_chain_out_of_scope"),  # cross-customer
        (AUDITOR, "government:contoso:catalog:domain:finance", "audit_chain_out_of_scope"),
        (AUDITOR_FOREIGN, OTHER_CUSTOMER_FINANCE, "audit_chain_out_of_scope"),
        (AUDITOR_FOREIGN, ALIASING_FINANCE, "audit_chain_out_of_scope"),  # would alias FINANCE
        (VIEWER, FINANCE, "target_out_of_scope"),  # data.read is not audit.read
        (STEWARD, FINANCE, "target_out_of_scope"),
    ],
    ids=[
        "cross-domain",
        "cross-domain-hr",
        "cross-customer",
        "cross-cloud",
        "foreign-role-cross-customer",
        "aliasing-domain",
        "viewer",
        "steward",
    ],
)
def test_out_of_scope_reads_are_403(
    world: World, endpoint: str, who: str, domain: str, reason: str
) -> None:
    _decide(world)
    response = world.get(who, f"{BASE}/{domain}/{endpoint}")
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == reason


def test_a_chain_id_in_the_path_is_not_a_domain(world: World) -> None:
    _decide(world)
    response = world.get(AUDITOR, f"{BASE}/contoso.finance/records")
    assert response.status_code == 403


def test_auditable_chain_round_trip() -> None:
    w = make_world()
    scope = asyncio.run(w.scope_of(AUDITOR))
    assert auditable_chain(scope, FINANCE) == "contoso.finance"
    assert auditable_chain(scope, ALIASING_FINANCE) is None
    assert auditable_chain(scope, OTHER_CUSTOMER_FINANCE) is None
    assert auditable_chain(scope, "contoso.finance") is None


def test_unconfigured_audit_store_is_503(world: World) -> None:
    del world.h.app.state.audit_repository
    response = world.get(AUDITOR, f"{BASE}/{FINANCE}/records")
    assert response.status_code == 503
    assert response.json()["reason"] == "audit_store_unconfigured"

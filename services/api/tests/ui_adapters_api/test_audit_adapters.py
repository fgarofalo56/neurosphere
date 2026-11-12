"""PRP-31 item 2: the audit domain list, records and verify adapters derive the chain server-side,
work for an auditor with no ``data.read`` and refuse cross-customer and cross-domain reads."""

from __future__ import annotations

import asyncio

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    HR,
    OPERATIONS,
    policy,
    role,
)
from neurosphere_api.ui_adapters.audit import auditable_chain
from neurosphere_core.audit import (
    AuditContext,
    ChainVerification,
    build_allowed,
    domain_audit_chain_id,
    make_subject,
)
from neurosphere_core.auth.scope import PolicyRoleAssignment, Role

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
CHAINS = "/api/v1/audit/chains"

#: PRP-31 item 14b: domains with non-``catalog`` source segments, as the seed
#: (``sandbox:domain:dom-00N``) and the kill-switch runbook (``neurosphere:domain:*``) mint them.
SANDBOX_DOM = "commercial:contoso:sandbox:domain:dom-001"
NEURO_DOM = "commercial:contoso:neurosphere:domain:customer-control"

#: security_auditor of FINANCE, SANDBOX_DOM and NEURO_DOM (one domain per source).
AUDITOR_SOURCES = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
#: security_auditor of FINANCE and of ALIASING_FINANCE (same name, ``billing`` source).
AUDITOR_TWO_FINANCES = "1b2c3d4e-5f6a-4b7c-9d8e-0f1a2b3c4d5e"
#: security_auditor of another customer's FINANCE only.
FOREIGN_ONLY = "2c3d4e5f-6a7b-4c8d-ae9f-1a2b3c4d5e6f"


def _add(
    world: World, object_id: str, *roles: PolicyRoleAssignment, memberships: tuple[str, ...]
) -> None:
    world.h.repo.put_principal(policy(object_id, *roles, memberships=memberships))


def _add_source_auditors(world: World) -> None:
    _add(
        world,
        AUDITOR_SOURCES,
        role(Role.SECURITY_AUDITOR, FINANCE, SANDBOX_DOM, NEURO_DOM),
        memberships=(FINANCE, SANDBOX_DOM, NEURO_DOM),
    )
    _add(
        world,
        AUDITOR_TWO_FINANCES,
        role(Role.SECURITY_AUDITOR, FINANCE, ALIASING_FINANCE),
        memberships=(FINANCE, ALIASING_FINANCE),
    )


def _write(world: World, domain: str, count: int = 2) -> str:
    """Append ``count`` records to ``domain``'s chain, named by the shared writer helper."""
    chain = domain_audit_chain_id("contoso", domain)

    async def run() -> None:
        scope = await world.scope_of(AUDITOR_SOURCES)
        ctx = AuditContext.from_scope(
            scope, correlation_id="corr-item14b", operation="catalog.read", channel="rest"
        )
        subject = make_subject(domain, "domain")
        for _ in range(count):
            await world.audit.append(chain, build_allowed(ctx, subject))

    asyncio.run(run())
    return chain


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


def test_list_never_shows_another_customers_domain(world: World) -> None:
    # PRP-31 item 14b: AUDITOR_FOREIGN's role names fabrikam's FINANCE and billing:domain:finance.
    # Before 14b the billing domain's chain aliased FINANCE's ``contoso.finance``, so it was
    # refused and this list was 403. It now has its own chain (``contoso._7.billing.finance``)
    # and lists; the other customer's domain never does.
    response = world.get(AUDITOR_FOREIGN, BASE)
    assert response.status_code == 200, response.text
    assert [i["domain_id"] for i in response.json()["items"]] == [ALIASING_FINANCE]


def test_list_is_403_when_only_another_customers_domain_is_held(world: World) -> None:
    _add(
        world,
        FOREIGN_ONLY,
        role(Role.SECURITY_AUDITOR, OTHER_CUSTOMER_FINANCE),
        memberships=(OTHER_CUSTOMER_FINANCE,),
    )
    response = world.get(FOREIGN_ONLY, BASE)
    assert response.status_code == 403, response.text


def test_list_is_401_without_a_token(world: World) -> None:
    assert world.get(None, BASE).status_code == 401


# --------------------------------------------------------------- item 14b: every source segment


def test_list_shows_every_source_segment(world: World) -> None:
    _add_source_auditors(world)
    response = world.get(AUDITOR_SOURCES, BASE)
    assert response.status_code == 200, response.text
    assert sorted(i["domain_id"] for i in response.json()["items"]) == sorted(
        [FINANCE, NEURO_DOM, SANDBOX_DOM]
    )


def test_list_shows_both_same_named_domains(world: World) -> None:
    _add_source_auditors(world)
    response = world.get(AUDITOR_TWO_FINANCES, BASE)
    assert response.status_code == 200, response.text
    assert sorted(i["domain_id"] for i in response.json()["items"]) == sorted(
        [ALIASING_FINANCE, FINANCE]
    )


@pytest.mark.parametrize(
    "domain", [FINANCE, SANDBOX_DOM, NEURO_DOM], ids=["catalog", "sandbox", "neurosphere"]
)
def test_each_source_reads_and_verifies_on_both_routes(world: World, domain: str) -> None:
    _add_source_auditors(world)
    chain = _write(world, domain)
    records = world.get(AUDITOR_SOURCES, f"{BASE}/{domain}/records")
    assert records.status_code == 200, records.text
    assert len(records.json()["items"]) == 2
    assert {i["subject"]["target"]["canonical_id"] for i in records.json()["items"]} == {domain}
    by_chain = world.get(AUDITOR_SOURCES, f"{CHAINS}/{chain}/records")
    assert by_chain.status_code == 200, by_chain.text
    assert by_chain.json() == records.json()
    verify = world.get(AUDITOR_SOURCES, f"{BASE}/{domain}/verify")
    chain_verify = world.get(AUDITOR_SOURCES, f"{CHAINS}/{chain}/verify")
    assert verify.status_code == chain_verify.status_code == 200, verify.text
    assert verify.json() == chain_verify.json()
    assert verify.json()["ok"] is True
    assert verify.json()["records_checked"] == 2
    assert verify.json()["chain_id"] == chain


def test_same_name_different_source_get_different_chains(world: World) -> None:
    _add_source_auditors(world)
    catalog_chain = _write(world, FINANCE, count=2)
    billing_chain = _write(world, ALIASING_FINANCE, count=3)
    assert catalog_chain == "contoso.finance"  # byte-identical to the pre-14b name
    assert billing_chain == "contoso._7.billing.finance"
    for domain, count in ((FINANCE, 2), (ALIASING_FINANCE, 3)):
        response = world.get(AUDITOR_TWO_FINANCES, f"{BASE}/{domain}/records")
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == count
        assert {i["subject"]["target"]["canonical_id"] for i in items} == {domain}


@pytest.mark.parametrize("endpoint", ["records", "verify"])
def test_holder_of_one_same_named_domain_cannot_read_the_other(world: World, endpoint: str) -> None:
    """The case Item 14 left leaking (an xfail there): it is a plain 403 now."""
    _add_source_auditors(world)
    _decide(world)  # FINANCE (catalog source) records on contoso.finance
    # AUDITOR_FOREIGN holds billing:domain:finance only.
    by_chain = world.get(AUDITOR_FOREIGN, f"{CHAINS}/contoso.finance/{endpoint}")
    assert by_chain.status_code == 403, by_chain.text
    assert by_chain.json()["reason"] == "target_out_of_scope"
    by_domain = world.get(AUDITOR_FOREIGN, f"{BASE}/{FINANCE}/{endpoint}")
    assert by_domain.status_code == 403, by_domain.text
    # Its own domain reads its own (empty) chain, never FINANCE's records.
    own = world.get(AUDITOR_FOREIGN, f"{BASE}/{ALIASING_FINANCE}/{endpoint}")
    assert own.status_code == 200, own.text
    if endpoint == "records":
        assert own.json()["items"] == []
    else:
        assert own.json()["chain_id"] == "contoso._7.billing.finance"
        assert own.json()["records_checked"] == 0
    # And the other way round: FINANCE's auditor cannot read the billing chain.
    _write(world, ALIASING_FINANCE)
    reverse = world.get(AUDITOR, f"{CHAINS}/contoso._7.billing.finance/{endpoint}")
    assert reverse.status_code == 403, reverse.text
    assert reverse.json()["reason"] == "target_out_of_scope"


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
        # Item 14b: the billing domain has its own chain now, so these are permission refusals
        # on the exact domain (before 14b: a round-trip refusal, ``audit_chain_out_of_scope``).
        (AUDITOR_FOREIGN, FINANCE, "target_out_of_scope"),  # holds billing:finance only
        (AUDITOR, ALIASING_FINANCE, "target_out_of_scope"),  # holds catalog:finance only
        (AUDITOR, SANDBOX_DOM, "target_out_of_scope"),
        (AUDITOR_SOURCES, "commercial:fabrikam:sandbox:domain:dom-001", "audit_chain_out_of_scope"),
        (AUDITOR_SOURCES, "government:contoso:sandbox:domain:dom-001", "audit_chain_out_of_scope"),
        (AUDITOR_SOURCES, "commercial:contoso:sandbox:domain:dom=001", "audit_chain_out_of_scope"),
        (VIEWER, FINANCE, "target_out_of_scope"),  # data.read is not audit.read
        (STEWARD, FINANCE, "target_out_of_scope"),
    ],
    ids=[
        "cross-domain",
        "cross-domain-hr",
        "cross-customer",
        "cross-cloud",
        "foreign-role-cross-customer",
        "same-name-catalog-not-held",
        "same-name-billing-not-held",
        "sandbox-not-held",
        "sandbox-cross-customer",
        "sandbox-cross-cloud",
        "unencodable-name",
        "viewer",
        "steward",
    ],
)
def test_out_of_scope_reads_are_403(
    world: World, endpoint: str, who: str, domain: str, reason: str
) -> None:
    _decide(world)
    _add_source_auditors(world)
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
    # Item 14b: a non-catalog source round-trips to its own chain (before 14b: None, because
    # ``contoso.finance`` mapped back to the catalog domain). Holding it is checked separately.
    assert auditable_chain(scope, ALIASING_FINANCE) == "contoso._7.billing.finance"
    assert auditable_chain(scope, SANDBOX_DOM) == "contoso._7.sandbox.dom-001"
    assert auditable_chain(scope, OTHER_CUSTOMER_FINANCE) is None
    assert auditable_chain(scope, "government:contoso:catalog:domain:finance") is None
    assert auditable_chain(scope, "commercial:contoso:catalog:domain:fin/ance") is None
    assert auditable_chain(scope, "contoso.finance") is None


def test_unconfigured_audit_store_is_503(world: World) -> None:
    del world.h.app.state.audit_repository
    response = world.get(AUDITOR, f"{BASE}/{FINANCE}/records")
    assert response.status_code == 503
    assert response.json()["reason"] == "audit_store_unconfigured"

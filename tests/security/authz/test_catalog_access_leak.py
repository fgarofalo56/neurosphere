"""Leak proofs for the catalog access routes (PRP-73 item 4).

A two-domain world (finance, operations) where operations holds accessors, assets and a MIDDLE
dependents node that a finance-only viewer cannot read. For every response field that could carry
a hint (rows, ``assets``, ``unassessed_assets``, ``unassessed_count``, ``assets_scanned``,
``total``, ``groups``, ``path_node_ids``, ``relation_path``, ``bound``, status codes, error text,
the audit chain and the logs) the suite proves an out-of-scope thing is indistinguishable from a
thing that does not exist, and that an entitled caller with both domains DOES see it (so the
absence is the scope, not an empty fixture).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from neurosphere_core.auth.scope import PolicyRoleAssignment, Role

from .test_catalog_access import (
    FIN_AGENT_R,
    FIN_AGENT_W,
    FIN_ASSET,
    FIN_ID,
    FIN_NEAR,
    FIN_SVC,
    FIN_TOP,
    HR_ID,
    MISSING_ID,
    MISSING_NODE,
    OPS_AGENT,
    OPS_ASSET,
    OPS_ID,
    OPS_MID,
    PREFIX,
    VIEWER_FAB,
    VIEWER_FIN,
    VIEWER_OPS,
    AccessWorld,
    asset,
    audit_text,
    bearer_for,
    edge,
    install,
    run,
)
from .test_catalog_access import _seed_principal as seed_principal  # pyright: ignore[reportPrivateUsage]
from .world import Deployment, World, at

QUERY = f"{PREFIX}/query"
DEPENDENTS = f"{PREFIX}/dependents"
PERSONAL = {"contains_personal_data": True}
BOTH_OID = "a1b2c3d4-0000-4000-8000-00000000f075"
FIN_MYSTERY = "commercial:contoso:foundry:grounding_source:fin-mystery"
OPS_MYSTERY = "commercial:contoso:foundry:grounding_source:ops-mystery"
OPS_ONLY_FRAGMENTS = (OPS_ASSET, OPS_AGENT, OPS_MID, OPS_MYSTERY, OPS_ID, "r-ops-fin", "mid-svc")


@pytest.fixture
def aworld(world: World) -> AccessWorld:
    aw = install(world)
    seed_principal(
        world["contoso"],
        BOTH_OID,
        memberships=(FIN_ID, OPS_ID),
        roles=(
            PolicyRoleAssignment(
                assignment_id="ra-both",
                role=Role.VIEWER,
                domain_ids=(FIN_ID, OPS_ID),
                expires_at=at(7 * 24 * 3600),
            ),
        ),
    )

    async def more() -> None:
        from .test_catalog_access import writer_scope

        scope = writer_scope()
        # An unassessed asset in each domain (every sensitivity field null).
        for name, domain in (("fin-mystery", FIN_ID), ("ops-mystery", OPS_ID)):
            await aw.repo.create_entity(
                scope,
                asset(
                    name,
                    domain,
                    contains_personal_data=None,
                    sensitivity_categories=None,
                    residency_region=None,
                    classification="unknown",
                ),
            )
        await aw.repo.put_edge(
            scope, edge("writes", "w-ops-mystery", OPS_AGENT, OPS_MYSTERY, OPS_ID), None
        )
        await aw.repo.put_edge(
            scope, edge("reads", "r-fin-mystery", FIN_AGENT_R, FIN_MYSTERY, FIN_ID), None
        )

    run(more())
    return aw


def post(dep: Deployment, path: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
    return dep.client.post(path, headers=headers, json=body)


def contoso(aw: AccessWorld) -> Deployment:
    return aw.world["contoso"]


def text_of(response: Any) -> str:
    return json.dumps(response.json(), sort_keys=True)


def assert_no_ops(response: Any) -> None:
    text = response.text
    for fragment in OPS_ONLY_FRAGMENTS:
        assert fragment not in text, f"{fragment} leaked: {text}"


def accessor_ids(payload: dict[str, Any]) -> set[str]:
    rows = (
        payload["rows"] if "rows" in payload else [r for g in payload["groups"] for r in g["rows"]]
    )
    return {r["accessor_id"] for r in rows}


# ---------------------------------------------------------------------------------- control


def test_control_an_entitled_caller_of_both_domains_sees_the_operations_data(
    aworld: AccessWorld,
) -> None:
    """Without this the absences below could be an empty fixture."""
    dep = contoso(aworld)
    both = bearer_for(dep, BOTH_OID)
    query = post(dep, QUERY, both, {"include_unassessed": True, "filters": PERSONAL})
    assert query.status_code == 200, query.text
    payload = query.json()
    assert {FIN_AGENT_W, FIN_AGENT_R, OPS_AGENT} <= accessor_ids(payload)
    assert {a["id"] for a in payload["assets"]} >= {FIN_ASSET, OPS_ASSET}
    assert payload["unassessed_count"] == 2
    dependents = post(dep, DEPENDENTS, both, {"node_id": FIN_SVC, "max_depth": 3})
    assert dependents.status_code == 200, dependents.text
    body = dependents.json()
    assert {FIN_NEAR, OPS_MID, FIN_TOP} <= accessor_ids(body)
    top = next(r for g in body["groups"] for r in g["rows"] if r["accessor_id"] == FIN_TOP)
    assert top["depth"] == 2
    assert OPS_MID in top["path_node_ids"]


# ------------------------------------------------------------------------------ query leaks


def test_query_rows_assets_and_counts_hold_only_readable_domains(aworld: AccessWorld) -> None:
    dep = contoso(aworld)
    response = post(
        dep, QUERY, dep.bearer(VIEWER_FIN), {"include_unassessed": True, "filters": PERSONAL}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert_no_ops(response)
    # rows: the operations reader of a finance asset is an unreadable accessor, not a hidden count
    assert accessor_ids(payload) == {FIN_AGENT_W, FIN_AGENT_R}
    assert len(payload["rows"]) == 2
    assert [a["id"] for a in payload["assets"]] == [FIN_ASSET]
    assert [a["id"] for a in payload["unassessed_assets"]] == [FIN_MYSTERY]
    assert payload["unassessed_count"] == 1
    assert payload["assets_scanned"] == 2  # customers + fin-mystery; the operations pair unseen
    assert payload["truncated"] is False and payload["truncated_reason"] is None
    for row in payload["rows"]:
        assert row["accessor_domain_id"] == FIN_ID
        assert set(row["path_node_ids"]) <= {row["accessor_id"], row["asset_id"]}


def test_the_other_domain_sees_its_own_slice_only(aworld: AccessWorld) -> None:
    dep = contoso(aworld)
    response = post(
        dep, QUERY, dep.bearer(VIEWER_OPS), {"include_unassessed": True, "filters": PERSONAL}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    for fragment in (FIN_ASSET, FIN_AGENT_W, FIN_AGENT_R, FIN_MYSTERY, FIN_ID, "r-fin-ops"):
        assert fragment not in response.text, fragment
    assert accessor_ids(payload) == {OPS_AGENT}
    assert [a["id"] for a in payload["assets"]] == [OPS_ASSET]
    assert payload["unassessed_count"] == 1
    assert payload["assets_scanned"] == 2


def test_an_unreadable_asset_id_answers_like_one_that_does_not_exist(aworld: AccessWorld) -> None:
    dep = contoso(aworld)
    headers = dep.bearer(VIEWER_FIN)
    for extra in ({}, {"include_unassessed": True}, {"modes": ["write"]}):
        hidden = post(dep, QUERY, headers, {"asset_ids": [OPS_ASSET], **extra})
        missing = post(dep, QUERY, headers, {"asset_ids": [MISSING_ID], **extra})
        assert hidden.status_code == missing.status_code == 200
        assert hidden.json() == missing.json(), (hidden.text, missing.text)
        assert hidden.json()["rows"] == [] and hidden.json()["assets_scanned"] == 0
    mixed = post(dep, QUERY, headers, {"asset_ids": [OPS_ASSET, FIN_ASSET, MISSING_ID]})
    clean = post(dep, QUERY, headers, {"asset_ids": [FIN_ASSET]})
    assert mixed.json() == clean.json()
    assert_no_ops(mixed)


def test_filters_domain_ids_can_only_narrow(aworld: AccessWorld) -> None:
    dep = contoso(aworld)
    headers = dep.bearer(VIEWER_FIN)
    hidden = post(dep, QUERY, headers, {"filters": {"domain_ids": [OPS_ID]}})
    unknown = post(dep, QUERY, headers, {"filters": {"domain_ids": [HR_ID]}})
    assert hidden.status_code == unknown.status_code == 200
    assert hidden.json() == unknown.json()
    assert hidden.json()["rows"] == [] and hidden.json()["assets_scanned"] == 0
    assert_no_ops(hidden)
    widened = post(dep, QUERY, headers, {"filters": {"domain_ids": [FIN_ID, OPS_ID]}})
    narrowed = post(dep, QUERY, headers, {"filters": {"domain_ids": [FIN_ID]}})
    unfiltered = post(dep, QUERY, headers, {})
    assert widened.json() == narrowed.json() == unfiltered.json()
    assert_no_ops(widened)


def test_sensitivity_and_region_filters_do_not_surface_unreadable_assets(
    aworld: AccessWorld,
) -> None:
    dep = contoso(aworld)
    headers = dep.bearer(VIEWER_FIN)
    for filters in (
        {"sensitivity_categories": ["pii"]},
        {"contains_personal_data": True},
        {"region_group": "eu"},
        {"residency_regions": ["northeurope"]},
        {"classifications": ["restricted"]},
    ):
        response = post(dep, QUERY, headers, {"filters": filters, "include_unassessed": True})
        assert response.status_code == 200, (filters, response.text)
        assert_no_ops(response)
        assert OPS_ASSET not in [a["id"] for a in response.json()["assets"]]
    northeurope = post(dep, QUERY, headers, {"filters": {"residency_regions": ["northeurope"]}})
    assert northeurope.json()["rows"] == [] and northeurope.json()["assets"] == []


def test_bound_and_counters_do_not_depend_on_unreadable_data(aworld: AccessWorld) -> None:
    """``bound`` is the fixed ceilings; a caller with no data sees the same object."""
    dep = contoso(aworld)
    fab = aworld.world["fabrikam"]
    mine = post(dep, QUERY, dep.bearer(VIEWER_FIN), {})
    nobody = post(fab, QUERY, fab.bearer(VIEWER_FAB), {})
    assert mine.json()["bound"] == nobody.json()["bound"]
    lowered = post(dep, QUERY, dep.bearer(VIEWER_FIN), {"budget": {"max_assets": 1}})
    assert lowered.json()["bound"]["max_assets"] == 1
    assert_no_ops(lowered)
    # the truncation signal for a named unreadable id is the one for a named missing id
    budget = {"max_assets": 1}
    hidden = post(
        dep, QUERY, dep.bearer(VIEWER_FIN), {"asset_ids": [FIN_ASSET, OPS_ASSET], "budget": budget}
    )
    missing = post(
        dep, QUERY, dep.bearer(VIEWER_FIN), {"asset_ids": [FIN_ASSET, MISSING_ID], "budget": budget}
    )
    assert hidden.json() == missing.json()
    assert_no_ops(hidden)


# -------------------------------------------------------------------------- dependents leaks


def test_a_dependents_chain_with_an_unreadable_middle_node_leaks_nothing(
    aworld: AccessWorld,
) -> None:
    """fin-top -> ops-mid -> fin-svc: a finance viewer must not see ops-mid in any field, and
    must not learn the finance node behind it either (the walk stops at what it cannot read)."""
    dep = contoso(aworld)
    response = post(dep, DEPENDENTS, dep.bearer(VIEWER_FIN), {"node_id": FIN_SVC, "max_depth": 5})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert_no_ops(response)
    assert accessor_ids(payload) == {FIN_NEAR}
    assert payload["total"] == 1
    assert [g["depth"] for g in payload["groups"]] == [1]
    for group in payload["groups"]:
        for row in group["rows"]:
            assert row["path_node_ids"] == [FIN_NEAR, FIN_SVC]
            assert row["relation_path"] == ["invokes"]
            assert row["evidence_ids"] is not None
    assert payload["truncated"] is False
    # assets_scanned counts visited readable nodes only (FIN_SVC and FIN_NEAR)
    assert payload["assets_scanned"] <= 2


def test_dependents_of_an_unreadable_or_missing_node_are_indistinguishable(
    aworld: AccessWorld,
) -> None:
    dep = contoso(aworld)
    fin = dep.bearer(VIEWER_FIN)
    for depth in (1, 3, 5):
        hidden = post(dep, DEPENDENTS, fin, {"node_id": OPS_MID, "max_depth": depth})
        missing = post(dep, DEPENDENTS, fin, {"node_id": MISSING_NODE, "max_depth": depth})
        assert hidden.status_code == missing.status_code == 200
        assert hidden.json() == missing.json(), (hidden.text, missing.text)
        assert hidden.json()["groups"] == [] and hidden.json()["total"] == 0
    ops = dep.bearer(VIEWER_OPS)
    # an operations viewer asking about the finance node, and about its own node whose only
    # dependent (fin-top) is finance
    hidden_node = post(dep, DEPENDENTS, ops, {"node_id": FIN_SVC, "max_depth": 3})
    missing_node = post(dep, DEPENDENTS, ops, {"node_id": MISSING_NODE, "max_depth": 3})
    assert hidden_node.json() == missing_node.json()
    own = post(dep, DEPENDENTS, ops, {"node_id": OPS_MID, "max_depth": 3})
    assert own.status_code == 200, own.text
    assert own.json()["groups"] == [] and own.json()["total"] == 0
    for fragment in (FIN_TOP, FIN_NEAR, FIN_SVC, FIN_ID, "top-mid", "near-svc"):
        assert fragment not in own.text and fragment not in hidden_node.text, fragment


def test_dependents_total_and_groups_match_the_readable_rows(aworld: AccessWorld) -> None:
    dep = contoso(aworld)
    response = post(dep, DEPENDENTS, dep.bearer(VIEWER_FIN), {"node_id": FIN_SVC, "max_depth": 1})
    payload = response.json()
    assert payload["total"] == sum(len(g["rows"]) for g in payload["groups"]) == 1
    assert payload["bound"]["max_depth"] == 1


# ------------------------------------------------------------------------------- error text


def test_error_text_names_only_what_the_caller_sent(aworld: AccessWorld) -> None:
    dep = contoso(aworld)
    headers = dep.bearer(VIEWER_FIN)
    gov = post(dep, QUERY, headers, {"filters": {"residency_regions": ["usgovvirginia"]}})
    assert gov.status_code == 422, gov.text
    assert gov.json()["reason"] == "unknown_region"
    assert "usgovvirginia" in gov.text  # the caller's own token, echoed once
    for fragment in ("usgovarizona", "usgovtexas", "usdod", "government", "Government"):
        assert fragment not in gov.text, fragment
    assert_no_ops(gov)
    unknown_group = post(dep, QUERY, headers, {"filters": {"region_group": "atlantis"}})
    assert unknown_group.status_code == 422, unknown_group.text
    assert unknown_group.json()["reason"] == "unknown_region_group"
    assert_no_ops(unknown_group)
    deep = post(dep, DEPENDENTS, headers, {"node_id": OPS_MID, "max_depth": 6})
    assert deep.status_code == 422, deep.text
    assert deep.json()["reason"] == "max_depth_exceeded"
    zero = post(dep, DEPENDENTS, headers, {"node_id": OPS_MID, "max_depth": 0})
    assert zero.status_code == 422, zero.text
    many = post(dep, QUERY, headers, {"asset_ids": [f"{OPS_ASSET}-{n}" for n in range(51)]})
    assert many.status_code == 422, many.text
    assert many.json()["reason"] == "too_many_assets"
    for response in (deep, zero, many):
        for fragment in (OPS_AGENT, OPS_MYSTERY, FIN_ASSET, FIN_AGENT_W, "mid-svc"):
            assert fragment not in response.text, fragment


def test_a_commercial_caller_sending_a_government_region_gets_only_its_own_token(
    aworld: AccessWorld,
) -> None:
    dep = contoso(aworld)
    response = post(
        dep,
        QUERY,
        dep.bearer(VIEWER_FIN),
        {"filters": {"residency_regions": ["usgovvirginia"], "region_group": "eu"}},
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["reason"] == "unknown_region"
    assert response.text.count("usgovvirginia") <= 2
    # A Commercial region of the same shape is accepted, so the refusal is the cloud.
    ok = post(
        dep, QUERY, dep.bearer(VIEWER_FIN), {"filters": {"residency_regions": ["westeurope"]}}
    )
    assert ok.status_code == 200, ok.text


# ----------------------------------------------------------------------- audit and log leaks


def test_the_audit_chain_and_logs_hold_no_unreadable_identifiers(
    aworld: AccessWorld, caplog: pytest.LogCaptureFixture
) -> None:
    dep = contoso(aworld)
    headers = dep.bearer(VIEWER_FIN)
    with caplog.at_level(logging.DEBUG):
        post(dep, QUERY, headers, {"filters": {"domain_ids": [OPS_ID, FIN_ID]}})
        post(dep, QUERY, headers, {"asset_ids": [OPS_ASSET]})
        post(dep, DEPENDENTS, headers, {"node_id": OPS_MID, "max_depth": 3})
        post(dep, DEPENDENTS, headers, {"node_id": FIN_SVC, "max_depth": 3})
    audit = audit_text(dep)
    assert "catalog.access_query" in audit and "catalog.dependents" in audit
    for label, text in (("audit", audit), ("log", caplog.text)):
        for fragment in (OPS_ASSET, OPS_AGENT, OPS_MID, OPS_MYSTERY, OPS_ID, "mid-svc"):
            assert fragment not in text, f"{label} holds {fragment}"
        # names and filter values are never recorded, only domains read and counts
        assert "Asset customers" not in text, label
        assert "westeurope" not in text, label

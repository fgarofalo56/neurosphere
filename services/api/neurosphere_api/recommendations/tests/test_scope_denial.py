"""Authorization at the recommendations routes: the path domain is the TARGET checked against the
derived scope. Domain B is never visible to a domain-A scope in list, detail or ``q`` search."""

import pytest

from neurosphere_api.recommendations.tests.support import (
    ALICE,
    BOB,
    CAROL,
    FINANCE,
    OPERATIONS,
    make_api,
    make_rec,
)

OPS_SUBJECT = "commercial:contoso:foundry:agent:ops-secret-bot"


def seeded():
    fin = make_rec(1)
    ops = make_rec(2, domain=OPERATIONS, subject_ids=[OPS_SUBJECT], kind="unused_agent")
    return make_api(fin, ops), fin, ops


def test_list_is_403_for_an_out_of_scope_domain() -> None:
    api, _, _ = seeded()
    response = api.get(ALICE, f"/domains/{OPERATIONS}")
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "forbidden"
    assert "ops-secret-bot" not in response.text


def test_detail_is_403_for_an_out_of_scope_domain() -> None:
    api, _, ops = seeded()
    response = api.get(ALICE, f"/domains/{OPERATIONS}/items/{ops.recommendation_id.root}")
    assert response.status_code == 403
    assert "ops-secret-bot" not in response.text


def test_search_is_403_for_an_out_of_scope_domain() -> None:
    api, _, _ = seeded()
    response = api.get(ALICE, f"/domains/{OPERATIONS}", q="ops-secret-bot")
    assert response.status_code == 403


def test_search_in_the_allowed_domain_never_returns_the_other_domain() -> None:
    api, _, _ = seeded()
    response = api.get(ALICE, f"/domains/{FINANCE}", q="ops-secret-bot")
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}
    unfiltered = api.get(ALICE, f"/domains/{FINANCE}", q="unused_agent")
    assert unfiltered.json()["items"] == []


def test_detail_of_other_domain_item_under_allowed_domain_is_404() -> None:
    api, _, ops = seeded()
    response = api.get(ALICE, f"/domains/{FINANCE}/items/{ops.recommendation_id.root}")
    assert response.status_code == 404
    assert "ops-secret-bot" not in response.text


def test_each_viewer_sees_only_their_domain() -> None:
    api, fin, ops = seeded()
    a = api.get(ALICE, f"/domains/{FINANCE}").json()["items"]
    b = api.get(BOB, f"/domains/{OPERATIONS}").json()["items"]
    assert [i["recommendation_id"] for i in a] == [fin.recommendation_id.root]
    assert [i["recommendation_id"] for i in b] == [ops.recommendation_id.root]


def test_unauthenticated_is_401() -> None:
    api, _, _ = seeded()
    assert api.get(None, f"/domains/{FINANCE}").status_code == 401


def test_unknown_domain_is_403_not_an_empty_200() -> None:
    api, _, _ = seeded()
    ghost = "commercial:contoso:catalog:domain:ghost"
    assert api.get(ALICE, f"/domains/{ghost}").status_code == 403


def test_policy_store_outage_is_503_fail_closed() -> None:
    api, _, _ = seeded()
    api.h.repo.fail_with(ConnectionError("policy store down"))
    response = api.get(ALICE, f"/domains/{FINANCE}")
    assert response.status_code == 503
    assert response.json()["code"] == "dependency_transient"


@pytest.mark.parametrize(
    "params",
    [
        {"domain_id": OPERATIONS},
        {"customer_id": "fabrikam"},
        {"domain_id": OPERATIONS, "customer_id": "fabrikam"},
    ],
)
def test_caller_supplied_scope_params_never_widen_scope(params: dict[str, str]) -> None:
    api, fin, _ = seeded()
    allowed = api.get(ALICE, f"/domains/{FINANCE}", **params)
    assert allowed.status_code == 200
    assert [i["recommendation_id"] for i in allowed.json()["items"]] == [fin.recommendation_id.root]
    assert api.get(ALICE, f"/domains/{OPERATIONS}", **params).status_code == 403


def test_review_request_needs_propose_permission_and_domain_scope() -> None:
    api, fin, ops = seeded()
    body = {"recommendation_id": fin.recommendation_id.root}
    assert api.post(ALICE, f"/domains/{FINANCE}/review-requests", body).status_code == 403
    assert api.post(CAROL, f"/domains/{OPERATIONS}/review-requests", body).status_code == 403
    cross = {"recommendation_id": ops.recommendation_id.root}
    assert api.post(CAROL, f"/domains/{FINANCE}/review-requests", cross).status_code == 404


def test_body_domain_and_customer_are_ignored() -> None:
    api, _, ops = seeded()
    body = {
        "recommendation_id": ops.recommendation_id.root,
        "domain_id": OPERATIONS,
        "customer_id": "fabrikam",
    }
    assert api.post(CAROL, f"/domains/{FINANCE}/review-requests", body).status_code == 404
    assert api.post(CAROL, f"/domains/{OPERATIONS}/review-requests", body).status_code == 403


def test_unconfigured_store_or_router_is_503() -> None:
    api = make_api(make_rec(1), wire=False)
    response = api.get(ALICE, f"/domains/{FINANCE}")
    assert response.status_code == 503
    assert response.json()["reason"] == "recommendations_unconfigured"
    api.h.app.state.recommendation_store = api.store
    assert api.get(ALICE, f"/domains/{FINANCE}").status_code == 200
    detail = api.get(ALICE, f"/domains/{FINANCE}/items/{make_rec(1).recommendation_id.root}")
    assert detail.status_code == 503
    assert detail.json()["reason"] == "review_router_unconfigured"

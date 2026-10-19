"""Nothing executes: the executions route only refuses, and the router has no other mutating
route besides review-requests."""

from fastapi.routing import APIRoute

from neurosphere_api.recommendations import build_router
from neurosphere_api.recommendations.tests.support import ALICE, CAROL, FINANCE, make_api, make_rec

EXEC = f"/domains/{FINANCE}/executions"


def test_executions_always_refuses_with_capability_unavailable() -> None:
    rec = make_rec(1)
    api = make_api(rec)
    response = api.post(CAROL, EXEC, {"recommendation_id": rec.recommendation_id.root})
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "capability_unavailable"
    assert body["detail"] == "action gates not passed"
    assert body["reason"] == "action_gates_not_passed"


def test_executions_refuses_without_a_body_too() -> None:
    api = make_api(make_rec(1))
    assert api.post(CAROL, EXEC).json()["code"] == "capability_unavailable"


def test_executions_authenticates_and_authorizes_before_refusing() -> None:
    api = make_api(make_rec(1))
    assert api.post(None, EXEC).status_code == 401
    # ALICE is a viewer: no action.propose, so 403 comes before the refusal.
    assert api.post(ALICE, EXEC).status_code == 403
    other = "/domains/commercial:contoso:catalog:domain:operations/executions"
    assert api.post(CAROL, other).status_code == 403


def test_execution_leaves_the_store_untouched() -> None:
    rec = make_rec(1)
    api = make_api(rec)
    api.post(CAROL, EXEC, {"recommendation_id": rec.recommendation_id.root})
    detail = api.get(ALICE, f"/domains/{FINANCE}/items/{rec.recommendation_id.root}").json()
    assert detail["review"] == {"state": "not_routed", "review_request_id": None}


def test_only_review_requests_and_executions_are_mutating_routes() -> None:
    mutating: set[tuple[str, str]] = set()
    for route in build_router().routes:
        assert isinstance(route, APIRoute)
        for method in route.methods or ():
            if method not in {"GET", "HEAD", "OPTIONS"}:
                mutating.add((method, route.path))
    assert mutating == {
        ("POST", "/domains/{domain}/review-requests"),
        ("POST", "/domains/{domain}/executions"),
    }


def test_no_put_patch_delete_routes() -> None:
    methods = {m for r in build_router().routes if isinstance(r, APIRoute) for m in r.methods or ()}
    assert methods.isdisjoint({"PUT", "PATCH", "DELETE"})


def test_detail_never_reports_executable() -> None:
    rec = make_rec(1)
    api = make_api(rec)
    detail = api.get(ALICE, f"/domains/{FINANCE}/items/{rec.recommendation_id.root}").json()
    assert detail["execution"] == {"executable": False, "reason": "action gates not passed"}

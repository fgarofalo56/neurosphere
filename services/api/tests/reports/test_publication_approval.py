"""Add-to-UI needs an approval by a different principal with config.manage (PRP-19 item 5)."""

from typing import Any

from reports_harness import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CAROL,
    DAVE,
    ERIN,
    Api,
    make_api,
    problem,
    report_body,
)


def _request(api: Api, who: str, report_id: str) -> Any:
    return api.call("POST", who, f"/{report_id}/publication")


def _decide(api: Api, who: str, report_id: str, decision: str, **kwargs: Any) -> Any:
    return api.call(
        "POST", who, f"/{report_id}/publication/decision", json={"decision": decision}, **kwargs
    )


def test_request_then_approve_by_another_principal() -> None:
    api = make_api()
    report = api.create()
    requested = _request(api, ALICE, report["id"])
    assert requested.status_code == 200, requested.text
    assert requested.json()["publication"]["state"] == "pending"
    approved = _decide(api, DAVE, report["id"], "approve")
    assert approved.status_code == 200, approved.text
    publication = approved.json()["publication"]
    assert publication["state"] == "approved"
    assert publication["decided_by"] != publication["requested_by"]


def test_the_owner_cannot_approve_even_when_holding_config_manage() -> None:
    api = make_api()
    report = api.create(ERIN)
    assert _request(api, ERIN, report["id"]).status_code == 200
    response = _decide(api, ERIN, report["id"], "approve")
    assert response.status_code == 403
    assert response.json()["reason"] == "self_approval_refused"
    state = api.call("GET", ERIN, f"/{report['id']}").json()["publication"]["state"]
    assert state == "pending"


def test_an_owner_without_config_manage_is_denied_before_the_report_is_read() -> None:
    api = make_api()
    report = api.create()
    _request(api, ALICE, report["id"])
    assert _decide(api, ALICE, report["id"], "approve").status_code == 403
    assert _decide(api, BOB, report["id"], "approve").status_code == 403


def test_only_report_create_holders_can_request_publication() -> None:
    api = make_api()
    report = api.create()
    api.share(ALICE, report["id"], BOB)
    assert _request(api, BOB, report["id"]).status_code == 403
    assert _request(api, DAVE, report["id"]).status_code == 403


def test_deciding_without_a_pending_request_is_a_conflict() -> None:
    api = make_api()
    report = api.create()
    response = _decide(api, DAVE, report["id"], "approve")
    assert response.status_code == 409
    assert problem(response)["reason"] == "publication_not_pending"


def test_reject_records_the_decision_and_the_report_stays_private() -> None:
    api = make_api()
    report = api.create()
    _request(api, ALICE, report["id"])
    response = api.call(
        "POST",
        DAVE,
        f"/{report['id']}/publication/decision",
        json={"decision": "reject", "reason": "needs a clearer title"},
    )
    assert response.status_code == 200
    assert response.json()["publication"]["state"] == "rejected"
    assert api.call("GET", CAROL, f"/{report['id']}").status_code == 404


def test_approved_report_is_visible_and_runs_under_each_viewers_own_scope() -> None:
    api = make_api()
    report = api.create()
    assert api.call("GET", CAROL, f"/{report['id']}").status_code == 404
    _request(api, ALICE, report["id"])
    _decide(api, DAVE, report["id"], "approve")
    response = api.run(CAROL, report["id"])
    assert response.status_code == 200, response.text
    names = [row["display_name"] for row in response.json()["chart_plan"]["spec"]["data"]["values"]]
    assert sorted(names) == ["Agent fin-1", "Agent fin-2"]
    assert [i["id"] for i in api.call("GET", CAROL).json()["items"]] == [report["id"]]


def test_editing_an_approved_report_resets_the_approval() -> None:
    api = make_api()
    report = api.create()
    _request(api, ALICE, report["id"])
    approved = _decide(api, DAVE, report["id"], "approve").json()
    updated = api.call(
        "PUT",
        ALICE,
        f"/{report['id']}",
        json=report_body("Renamed"),
        headers={"If-Match": approved["etag"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["publication"]["state"] == "none"
    assert api.call("GET", CAROL, f"/{report['id']}").status_code == 404


def test_a_reviewer_can_list_and_read_pending_definitions_but_not_run_them() -> None:
    api = make_api()
    report = api.create()
    quiet = api.create(body=report_body("Not requested"))
    _request(api, ALICE, report["id"])
    pending = api.call("GET", DAVE, "", params={"publication_state": "pending"}).json()
    assert [i["id"] for i in pending["items"]] == [report["id"]]
    assert quiet["id"] not in str(pending)
    assert api.call("GET", DAVE, f"/{report['id']}").status_code == 200
    assert api.call("GET", DAVE, f"/{quiet['id']}").status_code == 404
    assert api.run(DAVE, report["id"]).status_code == 404


def test_a_stale_if_match_on_the_decision_is_refused() -> None:
    api = make_api()
    report = api.create()
    pending = _request(api, ALICE, report["id"]).json()
    api.share(ALICE, report["id"], BOB)
    response = _decide(api, DAVE, report["id"], "approve", headers={"If-Match": pending["etag"]})
    assert response.status_code == 409
    assert problem(response)["code"] == "stale_version"


def test_views_carry_ui_hints_for_ownership_and_who_may_decide() -> None:
    api = make_api()
    report = api.create(ERIN)
    pending = _request(api, ERIN, report["id"]).json()
    assert pending["is_owner"] is True
    assert pending["can_decide_publication"] is False  # ERIN holds config.manage but owns it
    as_reviewer = api.call("GET", DAVE, f"/{report['id']}").json()
    assert as_reviewer["is_owner"] is False
    assert as_reviewer["can_decide_publication"] is True
    approved = _decide(api, DAVE, report["id"], "approve").json()
    assert approved["can_decide_publication"] is False

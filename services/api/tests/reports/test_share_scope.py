"""Sharing never shares scope: the viewer sees their own data, never the owner's (PRP-19 item 5)."""

from typing import Any

from reports_harness import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CAROL,
    ERIN,
    make_api,
    principal,
)


def _names(response: Any) -> list[str]:
    assert response.status_code == 200, response.text
    plan = response.json()["chart_plan"]
    return sorted(row["display_name"] for row in plan["spec"]["data"]["values"])


def test_owner_and_viewer_see_different_data_from_the_same_report() -> None:
    api = make_api()
    report = api.create()
    api.share(ALICE, report["id"], BOB)
    owner_rows = _names(api.run(ALICE, report["id"]))
    viewer_rows = _names(api.run(BOB, report["id"]))
    assert owner_rows == ["Agent fin-1", "Agent fin-2", "Agent ops-1"]
    assert viewer_rows == ["Agent fin-1", "Agent fin-2"]
    assert "Agent ops-1" not in str(api.responses[-1].text)


def test_an_unshared_reader_cannot_see_or_run_the_report() -> None:
    api = make_api()
    report = api.create()
    assert api.call("GET", CAROL, f"/{report['id']}").status_code == 404
    assert api.run(CAROL, report["id"]).status_code == 404
    listing = api.call("GET", CAROL).json()
    assert listing["items"] == []


def test_unsharing_removes_access() -> None:
    api = make_api()
    report = api.create()
    api.share(ALICE, report["id"], BOB)
    assert api.run(BOB, report["id"]).status_code == 200
    response = api.call("DELETE", ALICE, f"/{report['id']}/shares/{principal(BOB)}")
    assert response.status_code == 200
    assert response.json()["shares"] == []
    assert api.run(BOB, report["id"]).status_code == 404


def test_a_share_principal_sees_the_report_but_not_who_else_it_is_shared_with() -> None:
    api = make_api()
    report = api.create()
    api.share(ALICE, report["id"], BOB)
    api.share(ALICE, report["id"], CAROL)
    as_owner = api.call("GET", ALICE, f"/{report['id']}").json()
    as_viewer = api.call("GET", BOB, f"/{report['id']}").json()
    assert sorted(as_owner["shares"]) == sorted([principal(BOB), principal(CAROL)])
    assert as_viewer["shares"] == []
    assert [item["id"] for item in api.call("GET", BOB).json()["items"]] == [report["id"]]


def test_a_viewer_cannot_change_share_or_delete() -> None:
    api = make_api()
    report = api.create()
    api.share(ALICE, report["id"], BOB)
    # BOB is a viewer: no report.create in the domain, so the route denies before the report.
    share = api.call(
        "POST", BOB, f"/{report['id']}/shares", json={"principal_id": principal(CAROL)}
    )
    assert share.status_code == 403
    delete = api.call("DELETE", BOB, f"/{report['id']}", headers={"If-Match": report["etag"]})
    assert delete.status_code == 403


def test_a_non_owner_with_report_create_cannot_change_a_visible_report() -> None:
    api = make_api()
    report = api.create()
    api.share(ALICE, report["id"], ERIN)
    response = api.call(
        "POST", ERIN, f"/{report['id']}/shares", json={"principal_id": principal(CAROL)}
    )
    assert response.status_code == 403
    assert response.json()["reason"] == "not_owner"
    # ... and a report ERIN cannot see does not exist for her.
    other = api.create(ALICE)
    hidden = api.call(
        "POST", ERIN, f"/{other['id']}/shares", json={"principal_id": principal(CAROL)}
    )
    assert hidden.status_code == 404


def test_the_viewer_view_never_carries_the_owners_scope_or_result_data() -> None:
    api = make_api()
    report = api.create()
    api.share(ALICE, report["id"], BOB)
    api.run(ALICE, report["id"])
    text = api.call("GET", BOB, f"/{report['id']}").text
    assert "scope_hash" not in text
    assert "Agent ops-1" not in text

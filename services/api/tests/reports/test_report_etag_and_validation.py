"""ETag / If-Match concurrency and save-time validation (PRP-19 item 5)."""

import copy
from typing import Any

import pytest
from neurosphere_api.reports import InMemoryReportStore
from reports_harness import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CUSTOMER,
    FINANCE,
    agent_query,
    chart_plan,
    make_api,
    problem,
    report_body,
)


def test_update_with_the_current_etag_succeeds_and_issues_a_new_one() -> None:
    api = make_api()
    report = api.create()
    response = api.call(
        "PUT",
        ALICE,
        f"/{report['id']}",
        json=report_body("Renamed"),
        headers={"If-Match": report["etag"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Renamed"
    assert response.json()["etag"] != report["etag"]
    assert response.headers["ETag"] == response.json()["etag"]


def test_update_with_a_stale_etag_is_stale_version() -> None:
    api = make_api()
    report = api.create()
    api.share(ALICE, report["id"], BOB)  # bumps the ETag
    response = api.call(
        "PUT",
        ALICE,
        f"/{report['id']}",
        json=report_body("Renamed"),
        headers={"If-Match": report["etag"]},
    )
    assert response.status_code == 409
    assert problem(response)["code"] == "stale_version"
    assert api.call("GET", ALICE, f"/{report['id']}").json()["title"] == report["title"]


def test_update_and_delete_require_if_match() -> None:
    api = make_api()
    report = api.create()
    assert api.call("PUT", ALICE, f"/{report['id']}", json=report_body()).status_code == 422
    assert api.call("DELETE", ALICE, f"/{report['id']}").status_code == 422


def test_unquoted_if_match_is_accepted() -> None:
    api = make_api()
    report = api.create()
    response = api.call(
        "DELETE", ALICE, f"/{report['id']}", headers={"If-Match": report["etag"].strip('"')}
    )
    assert response.status_code == 204, response.text
    assert api.call("GET", ALICE, f"/{report['id']}").status_code == 404


def test_delete_with_a_stale_etag_keeps_the_report() -> None:
    api = make_api()
    report = api.create()
    response = api.call("DELETE", ALICE, f"/{report['id']}", headers={"If-Match": '"nope"'})
    assert response.status_code == 409
    assert api.call("GET", ALICE, f"/{report['id']}").status_code == 200


async def test_store_replace_is_compare_and_swap() -> None:
    api = make_api()
    report = api.create()
    stored = await api.store.get(CUSTOMER, FINANCE, report["id"])
    assert stored is not None
    first = await api.store.replace(stored, if_match=stored.etag or "")
    assert first.etag != stored.etag
    from neurosphere_core.errors import StaleVersionError

    with pytest.raises(StaleVersionError):
        await api.store.replace(stored, if_match=stored.etag or "")
    with pytest.raises(StaleVersionError):
        await api.store.delete(CUSTOMER, FINANCE, report["id"], if_match=stored.etag or "")


def test_the_saved_plan_is_the_validated_aliased_form_without_rows() -> None:
    api = make_api()
    plan = chart_plan()
    plan["spec"]["transform"] = [
        {
            "aggregate": [{"op": "sum", "field": "version", "as": "total"}],
            "groupby": ["display_name"],
        }
    ]
    plan["spec"]["encoding"]["y"] = {"field": "total", "type": "quantitative"}
    report = api.create(body=report_body(chart_plan=plan))
    saved = report["chart_plan"]
    assert saved["spec"]["data"]["values"] == []
    aggregate = saved["spec"]["transform"][0]["aggregate"][0]
    assert aggregate["as"] == "total"
    assert "as_" not in aggregate


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["spec"].update(data={"url": "https://example.test/x.json"}),
        lambda p: p["spec"].update(transform=[{"calculate": "datum.version * 2", "as": "d"}]),
        lambda p: p["spec"]["encoding"]["x"].update(field="missing"),
        lambda p: p["spec"].update(mark="geoshape"),
        lambda p: p.update(config={"axis": {"labelExpr": "datum.value"}}),
    ],
    ids=["url-data", "calculate", "missing-field", "mark-not-allowed", "config"],
)
def test_hostile_plans_are_rejected_before_storage(mutate: Any) -> None:
    api = make_api()
    plan = copy.deepcopy(chart_plan())
    mutate(plan)
    response = api.call("POST", ALICE, json=report_body(chart_plan=plan))
    assert response.status_code == 422, response.text
    assert problem(response)["code"] == "invalid_schema"
    assert api.call("GET", ALICE).json()["items"] == []


@pytest.mark.parametrize(
    "extra",
    [{"domain_id": "commercial:fabrikam:catalog:domain:x"}, {"customer_id": "fabrikam"}],
)
def test_query_spec_cannot_carry_scope_fields(extra: dict[str, Any]) -> None:
    api = make_api()
    response = api.call("POST", ALICE, json=report_body(query_spec={**agent_query(), **extra}))
    assert response.status_code == 422


def test_free_text_query_is_not_accepted() -> None:
    api = make_api()
    body = report_body()
    body["query_spec"] = "SELECT * FROM c"
    assert api.call("POST", ALICE, json=body).status_code == 422
    body["query_spec"] = {**agent_query(), "query": "SELECT * FROM c"}
    assert api.call("POST", ALICE, json=body).status_code == 422


def test_create_requires_report_create_in_the_domain() -> None:
    api = make_api()
    assert api.call("POST", BOB, json=report_body()).status_code == 403


def test_a_report_in_another_customers_partition_is_not_found() -> None:
    api = make_api()
    report = api.create()
    assert isinstance(api.store, InMemoryReportStore)
    other_domain = "commercial:contoso:catalog:domain:operations"
    response = api.h.client.get(
        f"/api/v1/reports/domains/{other_domain}/reports/{report['id']}",
        headers=api.h.auth(ALICE),
    )
    assert response.status_code == 404

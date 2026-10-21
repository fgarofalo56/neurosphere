"""Authorization at the dashboards route: the path domain is the TARGET, checked against the
derived scope. Outside the domain is 403 (never an empty 200), a policy-store outage is 503, and a
caller-supplied ``customer_id``/``domain_id`` query parameter never widens scope."""

import pytest

from neurosphere_api.dashboards import get_aggregate_reader
from neurosphere_api.dashboards.tests.support import (
    ALICE,
    BOB,
    FINANCE,
    METRICS,
    OPERATIONS,
    cost_point,
    make_api,
)


@pytest.mark.parametrize("metric", METRICS)
def test_viewer_of_a_denied_domain_gets_403_on_every_metric(metric: str) -> None:
    api = make_api()
    api.seed(cost_point(OPERATIONS, 1, "31337.42"))
    response = api.get(ALICE, OPERATIONS, metric)  # ALICE views FINANCE only
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "forbidden"
    assert "31337" not in response.text


@pytest.mark.parametrize("metric", METRICS)
def test_viewer_of_the_domain_is_allowed(metric: str) -> None:
    api = make_api()
    assert api.get(ALICE, FINANCE, metric).status_code == 200
    assert api.get(BOB, OPERATIONS, metric).status_code == 200


def test_unauthenticated_is_401() -> None:
    api = make_api()
    assert api.get(None, FINANCE, "cost").status_code == 401


def test_unknown_domain_is_403_not_an_empty_200() -> None:
    api = make_api()
    ghost = "commercial:contoso:catalog:domain:ghost"
    assert api.get(ALICE, ghost, "cost").status_code == 403


@pytest.mark.parametrize("metric", METRICS)
def test_policy_store_outage_is_503_fail_closed(metric: str) -> None:
    api = make_api()
    api.seed(cost_point(FINANCE, 1, "5"))
    api.h.repo.fail_with(ConnectionError("policy store down"))
    response = api.get(ALICE, FINANCE, metric)
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
    api = make_api()
    api.seed(cost_point(FINANCE, 1, "5.00"), cost_point(OPERATIONS, 1, "700.00"))

    allowed = api.get(ALICE, FINANCE, "cost", **params)
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["domain_id"] == FINANCE  # the path decides, not the query
    assert [s["total"]["value"] for s in body["series"]] == [5.0]

    denied = api.get(ALICE, OPERATIONS, "cost", **params)
    assert denied.status_code == 403
    # "700.0" not "700": the 403 body carries a random correlation UUID, and hex never has a "."
    assert "700.0" not in denied.text


def test_other_customers_data_is_not_readable_by_domain_name() -> None:
    api = make_api()
    other = "commercial:fabrikam:catalog:domain:finance"
    assert api.get(ALICE, other, "cost").status_code == 403


def test_reader_is_called_with_the_derived_customer_only() -> None:
    api = make_api()
    seen: list[tuple[str, str]] = []

    class Spy:
        async def query(self, customer_id: str, domain_id: str, *args: object, **kw: object):
            seen.append((customer_id, domain_id))
            return await api.store.query(customer_id, domain_id, *args, **kw)  # type: ignore[arg-type]

        async def status(self, customer_id: str):
            return await api.store.status(customer_id)

    api.use_reader(Spy())
    api.get(ALICE, FINANCE, "cost", customer_id="fabrikam")
    assert seen == [("contoso", FINANCE)]


def test_unconfigured_reader_fails_closed_503() -> None:
    api = make_api()
    api.h.app.dependency_overrides.pop(get_aggregate_reader)
    response = api.get(ALICE, FINANCE, "cost")
    assert response.status_code == 503
    assert response.json()["reason"] == "aggregates_unconfigured"

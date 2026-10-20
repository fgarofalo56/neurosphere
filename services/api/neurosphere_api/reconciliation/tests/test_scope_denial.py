"""A viewer of domain A cannot read domain B; outages fail closed; params never widen scope."""

from __future__ import annotations

from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    FINANCE,
    OPERATIONS,
)
from neurosphere_core.aggregates import InMemoryAggregateStore

from neurosphere_api.reconciliation import PREFIX

from .support import entry, fetch, make_api, make_store


def _both() -> InMemoryAggregateStore:
    return make_store(
        entry("fin", "10", {"gateway": "10", "app": "10", "billing": "10"}, domain=FINANCE),
        # A dotted amount cannot occur inside the random hex ids a problem body carries ("99"
        # did, which made the leak check below fail whenever an id contained "99").
        entry(
            "ops",
            "4321.98",
            {"gateway": "4321.98", "app": "4321.98", "billing": "4321.98"},
            domain=OPERATIONS,
        ),
    )


def test_a_viewer_of_domain_a_gets_403_for_domain_b_not_an_empty_200() -> None:
    h, client = make_api(_both(), viewer_of=FINANCE)
    response = client.get(f"{PREFIX}/domains/{OPERATIONS}", headers=h.auth(ALICE))
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "4321.98" not in response.text
    assert not {"reference", "references", "sources", "unknown_remainder"} & set(response.json())
    own = fetch(h, client, FINANCE)
    assert own["reference"]["amount"]["value"] == 10.0


def test_no_token_is_401() -> None:
    _, client = make_api(_both())
    assert client.get(f"{PREFIX}/domains/{FINANCE}").status_code == 401


def test_a_policy_store_outage_is_503() -> None:
    h, client = make_api(_both())
    h.repo.fail_with(ConnectionError("down"))
    response = client.get(f"{PREFIX}/domains/{FINANCE}", headers=h.auth(ALICE))
    assert response.status_code == 503
    assert response.json()["code"] == "dependency_transient"


def test_an_unset_reader_fails_closed_with_503() -> None:
    h, client = make_api(_both())
    del h.app.state.aggregate_reader
    response = client.get(f"{PREFIX}/domains/{FINANCE}", headers=h.auth(ALICE))
    assert response.status_code == 503
    assert response.json()["reason"] == "aggregate_reader_unconfigured"


def test_caller_scope_params_never_widen_scope() -> None:
    h, client = make_api(_both(), viewer_of=FINANCE)
    widened = client.get(
        f"{PREFIX}/domains/{OPERATIONS}",
        params={"domain_id": FINANCE, "customer_id": "contoso"},
        headers=h.auth(ALICE),
    )
    assert widened.status_code == 403
    narrowed = fetch(h, client, FINANCE, domain_id=OPERATIONS, customer_id="fabrikam")
    assert narrowed["domain_id"] == FINANCE
    assert narrowed["reference"]["amount"]["value"] == 10.0


def test_another_customers_data_in_the_same_domain_is_never_returned() -> None:
    store = make_store(
        entry("mine", "10", {"gateway": "10", "app": "10", "billing": "10"}),
        entry(
            "theirs",
            "500",
            {"gateway": "500", "app": "500", "billing": "500"},
            customer="fabrikam",
        ),
    )
    h, client = make_api(store)
    body = fetch(h, client, FINANCE, customer_id="fabrikam")
    assert body["reference"]["amount"]["value"] == 10.0

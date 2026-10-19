"""In-memory recommendation store: pagination, idempotent put, scope predicates, bounded q."""

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope

from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.recommendations import (
    MAX_QUERY_LENGTH,
    InMemoryRecommendationStore,
    RecommendationStore,
)
from neurosphere_core.scope import IdentityScope

FINANCE = "commercial:contoso:catalog:domain:finance"
OPERATIONS = "commercial:contoso:catalog:domain:operations"
PERSON = "commercial:contoso:entra:person:psn_0123456789abcdef"
EXAMPLES = (
    Path(__file__).resolve().parents[5]
    / "packages/contracts/schemas/recommendations/v1/examples/valid"
)


def example(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def make_scope(
    domains: list[str], *, cloud: str = "commercial", customer: str = "contoso"
) -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": cloud,
            "customer_id": customer,
            "principal": {
                "principal_id": PERSON.replace("commercial", cloud).replace("contoso", customer),
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": [d.replace("commercial", cloud) for d in domains],
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"scope").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def rec(n: int, *, domain: str = FINANCE, kind: str = "cost_spike") -> Recommendation:
    data = example("recommendation.cost-spike-scored.json")
    data["recommendation_id"] = f"commercial:contoso:neurosphere:recommendation:rec-{n:04d}"
    data["domain_id"] = domain
    data["kind"] = kind
    return Recommendation.model_validate(data)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_store_satisfies_protocol() -> None:
    assert isinstance(InMemoryRecommendationStore(), RecommendationStore)


def test_put_is_idempotent_by_recommendation_id() -> None:
    store = InMemoryRecommendationStore()
    scope = make_scope([FINANCE])
    first = rec(1)
    run(store.put(first))
    run(store.put(first))
    changed = rec(1, kind="unused_agent")
    run(store.put(changed))
    page = run(store.list(scope, FINANCE))
    assert [r.kind for r in page.items] == ["unused_agent"]


def test_pagination_walks_every_item_once_in_order() -> None:
    store = InMemoryRecommendationStore([rec(n) for n in (5, 1, 3, 2, 4)])
    scope = make_scope([FINANCE])
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        page = run(store.list(scope, FINANCE, cursor=cursor, limit=2))
        seen.extend(r.recommendation_id.root for r in page.items)
        pages += 1
        cursor = page.next_cursor
        if cursor is None:
            break
    assert pages == 3
    assert seen == sorted(seen)
    assert len(seen) == len(set(seen)) == 5


def test_exact_page_has_no_next_cursor() -> None:
    store = InMemoryRecommendationStore([rec(1), rec(2)])
    page = run(store.list(make_scope([FINANCE]), FINANCE, limit=2))
    assert len(page.items) == 2
    assert page.next_cursor is None


def test_invalid_cursor_and_limit_are_invalid_schema() -> None:
    store = InMemoryRecommendationStore([rec(1)])
    scope = make_scope([FINANCE])
    with pytest.raises(InvalidSchemaError):
        run(store.list(scope, FINANCE, cursor="!!notbase64"))
    with pytest.raises(InvalidSchemaError):
        run(store.list(scope, FINANCE, limit=0))


def test_other_domain_never_visible_even_in_allowed_list() -> None:
    store = InMemoryRecommendationStore([rec(1), rec(2, domain=OPERATIONS)])
    scope = make_scope([FINANCE, OPERATIONS])
    assert [r.domain_id.root for r in run(store.list(scope, FINANCE)).items] == [FINANCE]
    assert [r.domain_id.root for r in run(store.list(scope, OPERATIONS)).items] == [OPERATIONS]


def test_domain_outside_scope_is_empty_and_get_is_none() -> None:
    store = InMemoryRecommendationStore([rec(1, domain=OPERATIONS)])
    scope = make_scope([FINANCE])
    assert run(store.list(scope, OPERATIONS)).items == ()
    assert run(store.get(scope, OPERATIONS, rec(1).recommendation_id.root)) is None
    # Addressing it under an allowed domain does not reveal it either.
    assert run(store.get(scope, FINANCE, rec(1).recommendation_id.root)) is None


def test_other_customer_and_cloud_are_never_visible() -> None:
    store = InMemoryRecommendationStore([rec(1)])
    other_customer = make_scope([FINANCE.replace("contoso", "fabrikam")], customer="fabrikam")
    assert run(store.list(other_customer, FINANCE)).items == ()
    gov = make_scope([FINANCE], cloud="government")
    assert run(store.list(gov, FINANCE)).items == ()
    assert run(store.list(gov, FINANCE.replace("commercial", "government"))).items == ()


def test_get_returns_a_copy() -> None:
    store = InMemoryRecommendationStore([rec(1)])
    scope = make_scope([FINANCE])
    got = run(store.get(scope, FINANCE, rec(1).recommendation_id.root))
    assert got is not None
    got.advisory = True
    again = run(store.get(scope, FINANCE, rec(1).recommendation_id.root))
    assert again is not None
    assert again.advisory is False


def test_kind_filter_and_q_match_kind_and_subject_ids() -> None:
    other = example("recommendation.cost-spike-scored.json")
    other["recommendation_id"] = "commercial:contoso:neurosphere:recommendation:rec-0002"
    other["kind"] = "unused_agent"
    other["subject_ids"] = ["commercial:contoso:foundry:agent:billing-bot"]
    store = InMemoryRecommendationStore([rec(1), Recommendation.model_validate(other)])
    scope = make_scope([FINANCE])
    assert [r.kind for r in run(store.list(scope, FINANCE, kind="unused_agent")).items] == [
        "unused_agent"
    ]
    assert len(run(store.list(scope, FINANCE, q="BILLING-Bot")).items) == 1
    assert len(run(store.list(scope, FINANCE, q="COST_SPIKE")).items) == 1
    assert run(store.list(scope, FINANCE, q="no-such-thing")).items == ()


def test_q_is_length_capped_and_plain_text() -> None:
    store = InMemoryRecommendationStore([rec(1)])
    scope = make_scope([FINANCE])
    with pytest.raises(InvalidSchemaError):
        run(store.list(scope, FINANCE, q="a" * (MAX_QUERY_LENGTH + 1)))
    # Query-language characters are literal text, not operators.
    assert run(store.list(scope, FINANCE, q=".*")).items == ()

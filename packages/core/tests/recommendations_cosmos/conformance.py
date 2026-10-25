"""RecommendationStore protocol conformance checks, shared by every backend.

Each check takes a FRESH, empty store. ``CHECKS`` maps a check name to the coroutine function; the
in-memory + fake-container suite (``test_conformance.py``) and the emulator suite
(``tests/integration/stores_cosmos``) both parametrize over it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.paging.models import MAX_PAGE_SIZE
from neurosphere_core.recommendations import MAX_QUERY_LENGTH, RecommendationStore
from neurosphere_core.scope import IdentityScope

FINANCE = "commercial:contoso:catalog:domain:finance"
OPERATIONS = "commercial:contoso:catalog:domain:operations"
PERSON = "commercial:contoso:entra:person:psn_0123456789abcdef"
EXAMPLES = (
    Path(__file__).resolve().parents[4]
    / "packages/contracts/schemas/recommendations/v1/examples/valid"
)


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


def rec(
    n: int | str,
    *,
    domain: str = FINANCE,
    kind: str = "cost_spike",
    customer: str = "contoso",
    cloud: str = "commercial",
    subjects: list[str] | None = None,
) -> Recommendation:
    data: dict[str, Any] = json.loads(
        (EXAMPLES / "recommendation.cost-spike-scored.json").read_text(encoding="utf-8")
    )
    suffix = f"rec-{n:04d}" if isinstance(n, int) else n
    data["recommendation_id"] = f"commercial:contoso:neurosphere:recommendation:{suffix}"
    data["domain_id"] = domain
    data["kind"] = kind
    data["customer_id"] = customer
    data["cloud"] = cloud
    if subjects is not None:
        data["subject_ids"] = subjects
    return Recommendation.model_validate(data)


def ids(page: Any) -> list[str]:
    return [r.recommendation_id.root.rsplit(":", 1)[-1] for r in page.items]


Check = Callable[[RecommendationStore], Awaitable[None]]


async def check_satisfies_protocol(store: RecommendationStore) -> None:
    assert isinstance(store, RecommendationStore)


async def check_put_get_round_trip(store: RecommendationStore) -> None:
    scope = make_scope([FINANCE])
    original = rec(1)
    await store.put(original)
    assert await store.get(scope, FINANCE, original.recommendation_id.root) == original
    assert await store.get(scope, FINANCE, rec(2).recommendation_id.root) is None


async def check_put_is_idempotent_upsert(store: RecommendationStore) -> None:
    scope = make_scope([FINANCE])
    await store.put(rec(1))
    await store.put(rec(1))
    changed = rec(1, kind="unused_agent")
    await store.put(changed)
    page = await store.list(scope, FINANCE)
    assert page.items == (changed,)
    assert page.next_cursor is None


async def check_list_orders_by_id_and_pages_by_cursor(store: RecommendationStore) -> None:
    scope = make_scope([FINANCE])
    for n in (5, 1, 4, 2, 3):  # inserted out of order
        await store.put(rec(n))
    first = await store.list(scope, FINANCE, limit=2)
    assert ids(first) == ["rec-0001", "rec-0002"]
    assert first.next_cursor is not None
    second = await store.list(scope, FINANCE, cursor=first.next_cursor, limit=2)
    assert ids(second) == ["rec-0003", "rec-0004"]
    assert second.next_cursor is not None
    last = await store.list(scope, FINANCE, cursor=second.next_cursor, limit=2)
    assert ids(last) == ["rec-0005"]
    assert last.next_cursor is None
    exact = await store.list(scope, FINANCE, limit=5)
    assert len(exact.items) == 5
    assert exact.next_cursor is None  # exactly one page: no dangling cursor


async def check_kind_filter(store: RecommendationStore) -> None:
    scope = make_scope([FINANCE])
    await store.put(rec(1, kind="cost_spike"))
    await store.put(rec(2, kind="unused_agent"))
    page = await store.list(scope, FINANCE, kind="unused_agent")
    assert ids(page) == ["rec-0002"]


async def check_q_is_case_insensitive_substring_over_kind_and_subjects(
    store: RecommendationStore,
) -> None:
    scope = make_scope([FINANCE])
    await store.put(rec(1, kind="cost_spike", subjects=["commercial:contoso:catalog:agent:alpha"]))
    await store.put(rec(2, kind="unused_agent", subjects=["commercial:contoso:catalog:agent:beta"]))
    assert ids(await store.list(scope, FINANCE, q="SPIKE")) == ["rec-0001"]
    assert ids(await store.list(scope, FINANCE, q="  Beta ")) == ["rec-0002"]
    assert ids(await store.list(scope, FINANCE, q="agent:")) == ["rec-0001", "rec-0002"]
    assert ids(await store.list(scope, FINANCE, q="nothing-matches")) == []
    assert ids(await store.list(scope, FINANCE, q="   ")) == ["rec-0001", "rec-0002"]


async def check_q_is_data_not_query_language(store: RecommendationStore) -> None:
    scope = make_scope([FINANCE])
    await store.put(rec(1))
    hostile = "') OR 1=1 --"
    assert (await store.list(scope, FINANCE, q=hostile)).items == ()


async def check_bounds_and_invalid_input(store: RecommendationStore) -> None:
    scope = make_scope([FINANCE])
    with pytest.raises(InvalidSchemaError):
        await store.list(scope, FINANCE, q="x" * (MAX_QUERY_LENGTH + 1))
    with pytest.raises(InvalidSchemaError):
        await store.list(scope, FINANCE, cursor="!!not-base64!!")
    with pytest.raises(InvalidSchemaError):
        await store.list(scope, FINANCE, limit=0)
    with pytest.raises(InvalidSchemaError):
        await store.list(scope, FINANCE, limit=MAX_PAGE_SIZE + 1)
    await store.list(scope, FINANCE, q="x" * MAX_QUERY_LENGTH, limit=MAX_PAGE_SIZE)


async def check_ids_with_forbidden_key_characters_round_trip(store: RecommendationStore) -> None:
    scope = make_scope([FINANCE])
    slashed = rec("rec/with/slashes=1")
    await store.put(slashed)
    assert await store.get(scope, FINANCE, slashed.recommendation_id.root) == slashed
    assert (await store.list(scope, FINANCE)).items == (slashed,)


async def check_domain_outside_scope_is_empty(store: RecommendationStore) -> None:
    await store.put(rec(1, domain=OPERATIONS))
    scope = make_scope([FINANCE])
    assert (await store.list(scope, OPERATIONS)).items == ()
    assert await store.get(scope, OPERATIONS, rec(1).recommendation_id.root) is None


async def check_domain_isolation(store: RecommendationStore) -> None:
    both = make_scope([FINANCE, OPERATIONS])
    await store.put(rec(1, domain=FINANCE))
    await store.put(rec(2, domain=OPERATIONS))
    assert ids(await store.list(both, FINANCE)) == ["rec-0001"]
    assert ids(await store.list(both, OPERATIONS)) == ["rec-0002"]
    # Addressing an id through the wrong (but allowed) domain finds nothing.
    assert await store.get(both, OPERATIONS, rec(1).recommendation_id.root) is None
    assert await store.get(both, FINANCE, rec(2).recommendation_id.root) is None


async def check_customer_isolation(store: RecommendationStore) -> None:
    await store.put(rec(1, customer="contoso"))
    await store.put(rec(2, customer="fabrikam"))
    await store.put(rec(3, customer="fabrikam"))
    contoso = make_scope([FINANCE], customer="contoso")
    fabrikam = make_scope([FINANCE], customer="fabrikam")
    assert ids(await store.list(contoso, FINANCE)) == ["rec-0001"]
    assert ids(await store.list(fabrikam, FINANCE)) == ["rec-0002", "rec-0003"]
    # Fabrikam's recommendation is absent for contoso, even when addressed by exact id.
    assert await store.get(contoso, FINANCE, rec(2).recommendation_id.root) is None
    mine = await store.get(contoso, FINANCE, rec(1).recommendation_id.root)
    assert mine is not None
    assert mine.customer_id == "contoso"


async def check_cloud_isolation(store: RecommendationStore) -> None:
    await store.put(rec(1, cloud="government"))
    await store.put(rec(2, cloud="commercial"))
    commercial = make_scope([FINANCE], cloud="commercial")
    assert ids(await store.list(commercial, FINANCE)) == ["rec-0002"]
    assert await store.get(commercial, FINANCE, rec(1).recommendation_id.root) is None


async def check_same_id_under_another_domain_replaces_not_duplicates(
    store: RecommendationStore,
) -> None:
    # recommendation_id is caller-supplied, not derived from the domain, so a cross-domain
    # re-put is reachable; both backends key by id alone (the later put wins, no second copy).
    both = make_scope([FINANCE, OPERATIONS])
    await store.put(rec(1, domain=FINANCE))
    await store.put(rec(1, domain=OPERATIONS))
    assert ids(await store.list(both, FINANCE)) == []
    assert ids(await store.list(both, OPERATIONS)) == ["rec-0001"]
    assert await store.get(both, FINANCE, rec(1).recommendation_id.root) is None
    moved = await store.get(both, OPERATIONS, rec(1).recommendation_id.root)
    assert moved is not None
    assert moved.domain_id.root == OPERATIONS


CHECKS: dict[str, Check] = {
    name.removeprefix("check_"): fn
    for name, fn in sorted(globals().items())
    if name.startswith("check_")
}

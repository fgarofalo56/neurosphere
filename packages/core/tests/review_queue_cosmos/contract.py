"""Protocol-conformance suite for the catalog ``ReviewQueue`` (PRP-29 item 3).

Self-contained so ``tests/integration/stores_hitl`` can load it by path and run it against the
Cosmos emulator. ``ReviewQueueContract`` needs a ``queue`` fixture (an empty ``ReviewQueue``).
"""

from __future__ import annotations

import hashlib

import pytest
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.catalog import ReviewItem, ReviewQueue
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.scope import IdentityScope

FINANCE = "commercial:contoso:neurosphere:domain:finance"
RETAIL = "commercial:contoso:neurosphere:domain:retail"
OTHER = "commercial:fabrikam:neurosphere:domain:finance"
EDGE = "commercial:contoso:neurosphere:invokes:e-0001"
PERSON = "commercial:contoso:entra:person:psn_0123456789abcdef"
STEWARD = "commercial:contoso:entra:person:psn_steward000000001"


def make_scope(domains: list[str], customer: str = "contoso") -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": customer,
            "principal": {
                "principal_id": PERSON,
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": domains,
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"scope").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def make_item(
    item_id: str = "review:one",
    domain: str = FINANCE,
    at: str = "2026-10-17T10:00:00Z",
    customer: str = "contoso",
) -> ReviewItem:
    return ReviewItem(
        id=item_id,
        edge_id=EDGE,
        relation_type="invokes",
        cloud="commercial",
        customer_id=customer,
        domain_id=domain,
        reason="conflicts_with_lock",
        governing_override_id="commercial:contoso:neurosphere:edge_override:lock-1",
        observed_confidence=0.2,
        presented_confidence=0.82,
        new_evidence_ids=["trace:new-0001"],
        created_at=at,
    )


class ReviewQueueContract:
    async def test_satisfies_protocol(self, queue: ReviewQueue) -> None:
        assert isinstance(queue, ReviewQueue)

    async def test_enqueue_is_idempotent_by_id(self, queue: ReviewQueue) -> None:
        scope = make_scope([FINANCE])
        assert await queue.enqueue(scope, make_item()) is True
        assert await queue.enqueue(scope, make_item(at="2026-10-18T10:00:00Z")) is False
        found = await queue.get(scope, "review:one")
        assert found == make_item()  # the first write wins

    async def test_enqueue_outside_scope_is_forbidden(self, queue: ReviewQueue) -> None:
        with pytest.raises(ForbiddenError):
            await queue.enqueue(make_scope([RETAIL]), make_item(domain=FINANCE))
        with pytest.raises(ForbiddenError):
            await queue.enqueue(make_scope([OTHER], customer="fabrikam"), make_item(domain=FINANCE))
        assert await queue.list_open(make_scope([FINANCE, RETAIL])) == ()

    async def test_get_is_scope_filtered_and_missing_looks_the_same(
        self, queue: ReviewQueue
    ) -> None:
        await queue.enqueue(make_scope([FINANCE]), make_item())
        assert await queue.get(make_scope([FINANCE]), "review:one") is not None
        assert await queue.get(make_scope([RETAIL]), "review:one") is None
        assert await queue.get(make_scope([FINANCE]), "review:missing") is None
        assert await queue.get(make_scope([]), "review:one") is None

    async def test_list_open_is_oldest_first_scoped_and_clamped(self, queue: ReviewQueue) -> None:
        both = make_scope([FINANCE, RETAIL])
        await queue.enqueue(both, make_item("review:b", FINANCE, "2026-10-17T11:00:00Z"))
        await queue.enqueue(both, make_item("review:a", RETAIL, "2026-10-17T10:00:00Z"))
        await queue.enqueue(both, make_item("review:c", FINANCE, "2026-10-17T12:00:00Z"))
        listed = await queue.list_open(both)
        assert [i.id for i in listed] == ["review:a", "review:b", "review:c"]
        assert [i.id for i in await queue.list_open(both, limit=2)] == ["review:a", "review:b"]
        assert [i.id for i in await queue.list_open(both, limit=0)] == ["review:a"]  # clamp to 1
        only_finance = await queue.list_open(make_scope([FINANCE]))
        assert [i.id for i in only_finance] == ["review:b", "review:c"]
        assert await queue.list_open(make_scope([FINANCE], customer="fabrikam")) == ()

    async def test_resolve_marks_resolved_and_removes_from_open(self, queue: ReviewQueue) -> None:
        scope = make_scope([FINANCE])
        await queue.enqueue(scope, make_item())
        resolved = await queue.resolve(
            scope,
            "review:one",
            resolved_by=STEWARD,
            resolution="kept_curation",
            resolved_at="2026-10-18T09:00:00Z",
        )
        assert resolved.status == "resolved"
        assert resolved.resolved_by == STEWARD
        assert resolved.resolution == "kept_curation"
        assert resolved.resolved_at == "2026-10-18T09:00:00Z"
        assert await queue.get(scope, "review:one") == resolved
        assert await queue.list_open(scope) == ()
        # still idempotent after resolution: a replayed conflict does not reopen it
        assert await queue.enqueue(scope, make_item()) is False
        assert (await queue.get(scope, "review:one")).status == "resolved"  # type: ignore[union-attr]

    async def test_resolve_missing_or_out_of_scope_is_forbidden(self, queue: ReviewQueue) -> None:
        await queue.enqueue(make_scope([FINANCE]), make_item())
        for scope, item_id in (
            (make_scope([FINANCE]), "review:missing"),
            (make_scope([RETAIL]), "review:one"),
        ):
            with pytest.raises(ForbiddenError):
                await queue.resolve(
                    scope,
                    item_id,
                    resolved_by=STEWARD,
                    resolution="accepted_inference",
                    resolved_at="2026-10-18T09:00:00Z",
                )
        still = await queue.get(make_scope([FINANCE]), "review:one")
        assert still is not None and still.status == "open"

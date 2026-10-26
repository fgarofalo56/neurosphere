"""Protocol-conformance suite for ``HitlStore`` and ``DecisionStore`` (PRP-29 item 3).

Self-contained: no sibling imports, so ``tests/integration/stores_hitl`` loads this file by path
and runs the SAME assertions against the Cosmos emulator. ``HitlStoreContract`` and
``DecisionStoreContract`` are not collected themselves (no ``Test`` prefix); a concrete class
subclasses one and provides the fixtures named in its docstring.
"""

from __future__ import annotations

import hashlib
import itertools
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_contracts.actions.v1.approval_decision import ApprovalDecision
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.errors import (
    ForbiddenError,
    InvalidSchemaError,
    StaleVersionError,
)
from neurosphere_core.hitl import DecisionLog, DecisionStore, HitlStore, ReviewItem
from neurosphere_core.hitl.models import transition
from neurosphere_core.scope import IdentityScope

CUSTOMER = "contoso"
DOMAIN = "commercial:contoso:catalog:domain:retail"
OTHER_DOMAIN = "commercial:contoso:catalog:domain:finance"
OTHER_CUSTOMER = "fabrikam"
OTHER_CUSTOMER_DOMAIN = "commercial:fabrikam:catalog:domain:retail"
EDGE = "commercial:contoso:catalog:edge:e-0001"
T0 = datetime(2026, 10, 20, 9, 0, 0, tzinfo=UTC)
_counter = itertools.count(1)


def new_id() -> str:
    return str(uuid.UUID(int=next(_counter) + (4 << 76) + (2 << 62)))


def make_scope(
    domains: tuple[str, ...] = (DOMAIN,), customer: str = CUSTOMER, cloud: str = "commercial"
) -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": cloud,
            "customer_id": customer,
            "principal": {
                "principal_id": f"{cloud}:{customer}:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": list(domains),
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"scope").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def make_item(
    *,
    domain: str = DOMAIN,
    customer: str = CUSTOMER,
    kind: str = "relationship",
    created: datetime = T0,
    sla_hours: int = 24,
    expiry_hours: int = 72,
    item_id: str | None = None,
) -> ReviewItem:
    return ReviewItem.model_validate(
        {
            "item_id": item_id or new_id(),
            "kind": kind,
            "state": "pending",
            "cloud": "commercial",
            "customer_id": customer,
            "domain_id": domain,
            "subject_ref": EDGE,
            "created_at": created,
            "sla_due_at": created + timedelta(hours=sla_hours),
            "expires_at": created + timedelta(hours=expiry_hours),
            "policy_version": "v1",
        }
    )


def make_decision(
    item_id: str, decision_id: str | None = None, reason: str = "ok"
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "decision_id": decision_id or new_id(),
        "review_item_id": item_id,
        "review_kind": "insight_review",
        "intent_id": None,
        "approved_confirmation_hash": None,
        "reviewer": {
            "principal_pseudonym": "p-rev",
            "principal_kind": "user",
            "on_behalf_of": None,
        },
        "maker": None,
        "self_approval_allowed": False,
        "decision": "approved",
        "reason": reason,
        "policy_version": "v1",
        "decided_at": "2026-10-20T09:00:00.000000Z",
        "correlation_id": "corr-1",
    }


class HitlStoreContract:
    """Needs a ``store`` fixture (a ``HitlStore`` that starts empty)."""

    async def test_satisfies_protocol(self, store: HitlStore) -> None:
        assert isinstance(store, HitlStore)

    async def test_create_returns_item_with_etag_and_get_round_trips(
        self, store: HitlStore
    ) -> None:
        created = await store.create(make_item())
        assert created.etag
        assert await store.get(created.item_id) == created
        assert await store.get(new_id()) is None

    async def test_create_is_create_only(self, store: HitlStore) -> None:
        item = make_item()
        await store.create(item)
        with pytest.raises(StaleVersionError) as raised:
            await store.create(item)
        assert raised.value.reason == "review_item_exists"

    async def test_replace_is_etag_conditional(self, store: HitlStore) -> None:
        created = await store.create(make_item())
        assert created.etag is not None
        assigned = transition(
            created,
            "assigned",
            assignee_principal_id="commercial:contoso:entra:person:psn_a",
            assigned_at=T0,
        )
        replaced = await store.replace(assigned, if_match=created.etag)
        assert replaced.state_name == "assigned"
        assert replaced.etag and replaced.etag != created.etag
        with pytest.raises(StaleVersionError) as stale:
            await store.replace(assigned, if_match=created.etag)
        assert stale.value.reason == "etag_mismatch"
        stored = await store.get(created.item_id)
        assert stored is not None and stored.etag == replaced.etag

    async def test_replace_of_a_missing_item_is_stale(self, store: HitlStore) -> None:
        with pytest.raises(StaleVersionError) as stale:
            await store.replace(make_item(), if_match='"nope"')
        assert stale.value.reason == "etag_mismatch"

    async def test_list_is_oldest_first_and_pages_with_a_cursor(self, store: HitlStore) -> None:
        made = [
            await store.create(make_item(created=T0 + timedelta(minutes=m))) for m in (3, 1, 2, 4)
        ]
        by_age = sorted(made, key=lambda i: (i.created_at, i.item_id))
        scope = make_scope()
        first = await store.list(scope, DOMAIN, limit=3)
        assert [i.item_id for i in first.items] == [i.item_id for i in by_age[:3]]
        assert first.next_cursor is not None
        second = await store.list(scope, DOMAIN, cursor=first.next_cursor, limit=3)
        assert [i.item_id for i in second.items] == [by_age[3].item_id]
        assert second.next_cursor is None

    async def test_list_filters_by_kind_and_state(self, store: HitlStore) -> None:
        rel = await store.create(make_item(kind="relationship"))
        pol = await store.create(make_item(kind="policy_exception", created=T0 + timedelta(1)))
        assert rel.etag is not None
        assigned = transition(
            rel,
            "assigned",
            assignee_principal_id="commercial:contoso:entra:person:psn_a",
            assigned_at=T0,
        )
        await store.replace(assigned, if_match=rel.etag)
        scope = make_scope()
        kinds = await store.list(scope, DOMAIN, kind="policy_exception")
        assert [i.item_id for i in kinds.items] == [pol.item_id]
        states = await store.list(scope, DOMAIN, state="assigned")
        assert [i.item_id for i in states.items] == [rel.item_id]
        assert (await store.list(scope, DOMAIN, state="approved")).items == ()

    async def test_list_is_scope_filtered(self, store: HitlStore) -> None:
        mine = await store.create(make_item())
        await store.create(make_item(domain=OTHER_DOMAIN))
        await store.create(make_item(domain=OTHER_CUSTOMER_DOMAIN, customer=OTHER_CUSTOMER))
        scope = make_scope()
        page = await store.list(scope, DOMAIN)
        assert [i.item_id for i in page.items] == [mine.item_id]
        # a domain outside the scope is an empty page, not an error
        assert (await store.list(scope, OTHER_DOMAIN)).items == ()
        # another customer's domain is invisible even when listed in the scope's domains
        crossed = make_scope(domains=(OTHER_CUSTOMER_DOMAIN,))
        assert (await store.list(crossed, OTHER_CUSTOMER_DOMAIN)).items == ()

    async def test_list_rejects_bad_limit_and_cursor(self, store: HitlStore) -> None:
        scope = make_scope()
        for bad in (0, 501):
            with pytest.raises(InvalidSchemaError) as limit:
                await store.list(scope, DOMAIN, limit=bad)
            assert limit.value.reason == "invalid_limit"
        with pytest.raises(InvalidSchemaError) as cursor:
            await store.list(scope, DOMAIN, cursor="not-a-cursor")
        assert cursor.value.reason == "invalid_cursor"

    async def test_due_returns_earliest_deadline_first_and_is_bounded(
        self, store: HitlStore
    ) -> None:
        late = await store.create(make_item(sla_hours=10, expiry_hours=100))
        early = await store.create(make_item(sla_hours=2, expiry_hours=100, domain=OTHER_DOMAIN))
        future = await store.create(make_item(sla_hours=500, expiry_hours=900))
        now = T0 + timedelta(hours=12)
        found = await store.due(now)
        ids = [i.item_id for i in found]
        assert ids == [early.item_id, late.item_id]
        assert future.item_id not in ids
        assert [i.item_id for i in await store.due(now, limit=1)] == [early.item_id]
        for bad in (0, 501):
            with pytest.raises(InvalidSchemaError):
                await store.due(now, limit=bad)

    async def test_due_skips_final_items(self, store: HitlStore) -> None:
        created = await store.create(make_item(sla_hours=1, expiry_hours=2))
        assert created.etag is not None
        now = T0 + timedelta(hours=5)
        assert [i.item_id for i in await store.due(now)] == [created.item_id]
        expired = transition(created, "expired")
        await store.replace(expired, if_match=created.etag)
        assert await store.due(now) == []

    async def test_due_orders_equal_deadlines_by_item_id(self, store: HitlStore) -> None:
        a = await store.create(make_item(sla_hours=1, expiry_hours=2))
        b = await store.create(make_item(sla_hours=1, expiry_hours=2, domain=OTHER_DOMAIN))
        found = await store.due(T0 + timedelta(hours=3))
        assert [i.item_id for i in found] == sorted([a.item_id, b.item_id])

    async def test_hitl_store_roundtrips_a_maker_checker_item(self, store: HitlStore) -> None:
        maker = Actor.model_validate(
            {"principal_pseudonym": "p-maker", "principal_kind": "user", "on_behalf_of": None}
        )
        item = ReviewItem.model_validate(
            {
                **make_item().model_dump(mode="json"),
                "kind": "maker_checker",
                "action_kind": "model_swap",
                "intent_id": new_id(),
                "confirmation_hash": "sha256:" + hashlib.sha256(b"x").hexdigest(),
                "maker_principal_id": "commercial:contoso:entra:person:psn_maker",
                "maker": maker,
            }
        )
        created = await store.create(item)
        found = await store.get(item.item_id)
        assert found == created
        assert found is not None and found.maker == maker


class DecisionStoreContract:
    """Needs a ``rig`` fixture: ``(items, decisions)`` where ``decisions`` can resolve ``items``."""

    async def test_satisfies_protocol(self, rig: tuple[HitlStore, DecisionStore]) -> None:
        assert isinstance(rig[1], DecisionStore)

    async def test_create_get_and_list_in_insertion_order(
        self, rig: tuple[HitlStore, DecisionStore]
    ) -> None:
        items, decisions = rig
        first = await items.create(make_item())
        second = await items.create(make_item(domain=OTHER_DOMAIN))
        docs = [make_decision(first.item_id, reason=f"r{n}") for n in range(3)]
        other = make_decision(second.item_id)
        await decisions.create(docs[0]["decision_id"], docs[0])
        await decisions.create(other["decision_id"], other)
        await decisions.create(docs[1]["decision_id"], docs[1])
        await decisions.create(docs[2]["decision_id"], docs[2])
        assert await decisions.get(docs[1]["decision_id"]) == docs[1]
        assert await decisions.get(new_id()) is None
        assert await decisions.list_for_item(first.item_id) == docs
        assert await decisions.list_for_item(second.item_id) == [other]

    async def test_create_is_create_only(self, rig: tuple[HitlStore, DecisionStore]) -> None:
        items, decisions = rig
        item = await items.create(make_item())
        doc = make_decision(item.item_id)
        await decisions.create(doc["decision_id"], doc)
        changed = {**doc, "reason": "changed after the fact"}
        with pytest.raises(StaleVersionError) as raised:
            await decisions.create(doc["decision_id"], changed)
        assert raised.value.reason == "decision_exists"
        assert await decisions.get(doc["decision_id"]) == doc  # unchanged

    async def test_there_is_no_update_path(self, rig: tuple[HitlStore, DecisionStore]) -> None:
        _, decisions = rig
        for name in ("update", "replace", "upsert", "patch", "delete", "remove", "put", "save"):
            assert not hasattr(decisions, name), name

    async def test_decision_log_is_append_only_over_the_store(
        self, rig: tuple[HitlStore, DecisionStore]
    ) -> None:
        items, decisions = rig
        item = await items.create(make_item())
        audit = AuditRepository(InMemoryAuditStore())
        log = DecisionLog(audit, decisions)
        decision = ApprovalDecision.model_validate(make_decision(item.item_id))
        stored = await log.append(
            decision,
            cloud="commercial",
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
            scope_hash="sha256:" + hashlib.sha256(b"scope").hexdigest(),
        )
        assert stored.decision_id.root == decision.decision_id.root
        assert [d.decision_id.root for d in await log.list_for_item(item.item_id)] == [
            decision.decision_id.root
        ]
        for method in (log.update, log.delete, log.replace, log.upsert):
            with pytest.raises(ForbiddenError) as refused:
                method()
            assert refused.value.reason == "decision_append_only"
        with pytest.raises(StaleVersionError):
            await log.append(
                decision,
                cloud="commercial",
                customer_id=CUSTOMER,
                domain_id=DOMAIN,
                scope_hash="sha256:" + hashlib.sha256(b"scope").hexdigest(),
            )


__all__ = [
    "CUSTOMER",
    "DOMAIN",
    "OTHER_DOMAIN",
    "DecisionStoreContract",
    "HitlStoreContract",
    "make_decision",
    "make_item",
    "make_scope",
    "new_id",
]

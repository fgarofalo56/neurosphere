"""Same (principal, key) + same payload returns the original; nothing double-executes."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from neurosphere_core.actions import (
    CreateOutcome,
    InMemoryIntentStore,
    InvalidTransitionError,
    StoredIntent,
)
from neurosphere_core.errors import InvalidSchemaError, NeuroSphereError, StaleVersionError

from .action_helpers import CHECKER, CUSTOMER, DOMAIN, MAKER, Harness, request


async def test_store_create_is_idempotent_per_principal_and_key() -> None:
    h = Harness()
    stored = await h.drafted()
    store = h.store
    outcome = await store.create(stored.model_copy(update={"etag": None}))
    assert outcome == CreateOutcome(stored=outcome.stored, created=False)
    assert outcome.stored.intent_id == stored.intent_id
    page = await store.list(CUSTOMER, DOMAIN)
    assert [s.intent_id for s in page.items] == [stored.intent_id]


async def test_service_replay_returns_the_original_without_writing() -> None:
    h = Harness()
    first = await h.service.draft(MAKER, request(), customer_id=CUSTOMER, domain_id=DOMAIN)
    events = len(h.auditor.events)
    h.clock.advance(timedelta(minutes=3))
    again = await h.service.draft(
        MAKER, request(channel="mcp"), customer_id=CUSTOMER, domain_id=DOMAIN
    )
    assert first.created is True
    assert again.created is False
    assert again.stored.intent == first.stored.intent
    assert again.stored.intent.channel == "rest"  # the original, not the replay's channel
    assert len(h.auditor.events) == events
    assert h.store.create_calls == 1


async def test_key_reuse_with_a_different_payload_is_refused_and_audited() -> None:
    h = Harness()
    await h.drafted()
    with pytest.raises(InvalidSchemaError) as caught:
        await h.service.draft(
            MAKER, request(new_version="2026-09-01"), customer_id=CUSTOMER, domain_id=DOMAIN
        )
    assert caught.value.code == "invalid_schema"
    assert caught.value.reason == "idempotency_key_reused"
    assert h.denials() == [("action.draft", "idempotency_key_reused")]
    assert len((await h.store.list(CUSTOMER, DOMAIN)).items) == 1


async def test_key_reuse_in_another_domain_is_refused() -> None:
    h = Harness()
    await h.drafted()
    with pytest.raises(InvalidSchemaError) as caught:
        await h.service.draft(
            MAKER,
            request(),
            customer_id=CUSTOMER,
            domain_id="commercial:contoso:catalog:domain:finance",
        )
    assert caught.value.reason == "idempotency_key_reused"


async def test_store_level_reuse_is_detected_even_without_the_precheck() -> None:
    h = Harness()
    stored = await h.drafted()
    other = await Harness().drafted(request(new_version="2026-09-01"))
    clash = other.model_copy(update={"etag": None})
    assert clash.intent.idempotency_key == stored.intent.idempotency_key
    with pytest.raises(InvalidSchemaError) as caught:
        await h.store.create(clash)
    assert caught.value.reason == "idempotency_key_reused"


async def test_keys_are_scoped_per_principal() -> None:
    h = Harness()
    mine = await h.drafted()
    theirs = await h.drafted(who=CHECKER)
    assert mine.intent_id != theirs.intent_id
    assert len((await h.store.list(CUSTOMER, DOMAIN)).items) == 2


async def test_second_executing_transition_cannot_happen() -> None:
    h = Harness()
    presented = await h.awaiting_confirmation()
    executing = await h.confirm(presented)
    assert executing.state == "executing"
    with pytest.raises(InvalidTransitionError):
        await h.confirm(presented)
    # A writer holding the pre-confirmation copy loses on the ETag.
    stale = presented.model_copy(update={"requires_approval": True})
    with pytest.raises(StaleVersionError) as caught:
        await h.store.replace(stale, if_match=presented.etag or "")
    assert caught.value.reason == "intent_modified"
    into_executing = [t for t in h.transitions() if t[1] == "executing"]
    assert into_executing == [("awaiting_confirmation", "executing")]


async def test_concurrent_confirms_execute_once() -> None:
    h = Harness()
    presented = await h.awaiting_confirmation()
    results = await asyncio.gather(
        h.confirm(presented), h.confirm(presented), return_exceptions=True
    )
    winners = [r for r in results if isinstance(r, StoredIntent)]
    losers = [r for r in results if isinstance(r, NeuroSphereError)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert isinstance(losers[0], StaleVersionError | InvalidTransitionError)
    assert [t for t in h.transitions() if t[1] == "executing"] == [
        ("awaiting_confirmation", "executing")
    ]


async def test_replay_of_an_executed_draft_returns_it_and_does_not_reexecute() -> None:
    h = Harness()
    executing = await h.executing()
    again = await h.service.draft(MAKER, request(), customer_id=CUSTOMER, domain_id=DOMAIN)
    assert again.created is False
    assert again.stored.intent_id == executing.intent_id
    assert again.stored.state == "executing"
    assert len([t for t in h.transitions() if t[1] == "executing"]) == 1


async def test_only_one_worker_holds_the_execution_lease() -> None:
    h = Harness()
    executing = await h.executing()
    claimed = await h.service.begin_execution(executing.key, worker_id="worker-a")
    assert claimed.execution is not None
    assert claimed.execution.attempts == 1
    with pytest.raises(StaleVersionError) as caught:
        await h.service.begin_execution(executing.key, worker_id="worker-b")
    assert caught.value.reason == "execution_leased"
    # The same worker may re-claim (restart), and the attempt is counted.
    again = await h.service.begin_execution(executing.key, worker_id="worker-a")
    assert again.execution is not None
    assert again.execution.attempts == 2


async def test_find_by_idempotency_key_is_customer_scoped() -> None:
    store = InMemoryIntentStore()
    h = Harness(store=store)
    stored = await h.drafted()
    found = await store.find_by_idempotency_key(
        stored.principal_id, stored.intent.idempotency_key, customer_id=CUSTOMER
    )
    assert found is not None
    assert found.intent_id == stored.intent_id
    assert (
        await store.find_by_idempotency_key(
            stored.principal_id, stored.intent.idempotency_key, customer_id="fabrikam"
        )
        is None
    )

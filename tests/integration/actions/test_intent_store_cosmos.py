"""CosmosIntentStore and CosmosExecutionControl against the compose emulator (G12 evidence).

Run: ``docker compose up -d --wait`` then ``pytest -m integration tests/integration/actions``.
Each test gets its own container (deleted afterwards). Emulator limits (G12): no auth, no RU
accounting, no stored procedures; idempotency therefore relies only on create-only semantics
(409) and ETag-conditional replace (412), which is all the store uses. Passing here says nothing
about RBAC, RU cost or multi-region consistency on a real account.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import sys
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
import pytest_asyncio
from azure.cosmos.aio import ContainerProxy, DatabaseProxy
from neurosphere_core.actions import (
    ActionService,
    GrantTablePermissionRechecker,
    InvalidTransitionError,
    RecordingActionAuditor,
    StoredIntent,
    require_execution_enabled,
)
from neurosphere_core.actions.cosmos_store import (
    IDEMPOTENCY_PARTITION,
    INTENT_PARTITION_KEY_PATHS,
    CosmosExecutionControl,
    CosmosIntentStore,
    create_execution_control_container,
    create_intent_container,
)
from neurosphere_core.actions.models import idempotency_lookup_id
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    InvalidSchemaError,
    NeuroSphereError,
    StaleVersionError,
)

pytestmark = pytest.mark.integration

_HELPER = Path(__file__).resolve().parents[3] / "packages/core/tests/actions/action_helpers.py"


def _load_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("core_action_helpers", _HELPER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


helper = _load_helper()


@pytest.fixture(autouse=True)
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://localhost:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())


@pytest_asyncio.fixture
async def database() -> AsyncIterator[DatabaseProxy]:
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        yield await client.create_database_if_not_exists("ns_actions_it")


@pytest_asyncio.fixture
async def container(database: DatabaseProxy) -> AsyncIterator[ContainerProxy]:
    created = await create_intent_container(database, f"intents_{uuid.uuid4().hex[:10]}")
    try:
        yield created
    finally:
        await database.delete_container(created.id)


def _service(store: CosmosIntentStore, clock: Callable[[], datetime]) -> ActionService:
    rechecker = GrantTablePermissionRechecker()
    for permission in ("action.execute", "action.approve"):
        rechecker.grant(helper.MAKER_ID, helper.CUSTOMER, helper.DOMAIN, permission)
    return ActionService(
        store,
        auditor=RecordingActionAuditor(),
        rechecker=rechecker,
        clock=clock,
    )


async def _draft(service: ActionService, key: str = "idem-2026-10-20-cosmos-0001") -> StoredIntent:
    outcome = await service.draft(
        helper.MAKER, helper.request(key), customer_id=helper.CUSTOMER, domain_id=helper.DOMAIN
    )
    return outcome.stored


async def test_container_uses_the_hierarchical_key(container: ContainerProxy) -> None:
    key = (await container.read())["partitionKey"]
    assert key["paths"] == list(INTENT_PARTITION_KEY_PATHS)
    assert key["kind"] == "MultiHash"


async def test_create_replay_and_reuse(container: ContainerProxy) -> None:
    store = CosmosIntentStore(container)
    service = _service(store, helper.FakeClock())
    first = await service.draft(
        helper.MAKER, helper.request(), customer_id=helper.CUSTOMER, domain_id=helper.DOMAIN
    )
    assert first.created
    assert first.stored.etag
    # Store-level replay (bypassing the service precheck) returns the original.
    replay = await store.create(first.stored.model_copy(update={"etag": None}))
    assert not replay.created
    assert replay.stored.intent == first.stored.intent
    again = await service.draft(
        helper.MAKER, helper.request(), customer_id=helper.CUSTOMER, domain_id=helper.DOMAIN
    )
    assert not again.created
    assert again.stored.intent_id == first.stored.intent_id
    with pytest.raises(InvalidSchemaError) as caught:
        await service.draft(
            helper.MAKER,
            helper.request(new_version="2026-09-09"),
            customer_id=helper.CUSTOMER,
            domain_id=helper.DOMAIN,
        )
    assert caught.value.reason == "idempotency_key_reused"
    # Same reuse caught by the store itself (create-only lookup + digest compare).
    clash = await helper.Harness().drafted(helper.request(new_version="2026-09-09"))
    with pytest.raises(InvalidSchemaError) as caught:
        await store.create(clash.model_copy(update={"etag": None}))
    assert caught.value.reason == "idempotency_key_reused"
    page = await store.list(helper.CUSTOMER, helper.DOMAIN)
    assert [s.intent_id for s in page.items] == [first.stored.intent_id]


async def test_concurrent_creates_with_one_key_store_one_intent(container: ContainerProxy) -> None:
    store = CosmosIntentStore(container)
    first = await _draft(_service(store, helper.FakeClock()))
    copies = [first.model_copy(update={"etag": None}) for _ in range(5)]
    outcomes = await asyncio.gather(*(store.create(c) for c in copies))
    assert {o.stored.intent_id for o in outcomes} == {first.intent_id}
    assert not any(o.created for o in outcomes)


async def test_crash_between_lookup_and_intent_is_repaired(container: ContainerProxy) -> None:
    store = CosmosIntentStore(container)
    stored = await helper.Harness().drafted()
    orphan_id = "00000000-0000-4000-8000-0000000000aa"
    await container.create_item(
        body={
            "id": idempotency_lookup_id(stored.principal_id, stored.intent.idempotency_key),
            "doc_type": "idempotency",
            "customer_id": stored.customer_id,
            "domain_id": IDEMPOTENCY_PARTITION,
            "payload_digest": stored.payload_digest,
            "intent_domain_id": stored.domain_id,
            "intent_id": orphan_id,
        }
    )
    outcome = await store.create(stored.model_copy(update={"etag": None}))
    assert outcome.stored.intent_id == orphan_id
    again = await store.create(stored.model_copy(update={"etag": None}))
    assert not again.created
    assert again.stored.intent_id == orphan_id


async def test_replace_is_etag_conditional(container: ContainerProxy) -> None:
    store = CosmosIntentStore(container)
    stored = await _draft(_service(store, helper.FakeClock()))
    assert stored.etag is not None
    updated = await store.replace(
        stored.model_copy(update={"advisory": True}), if_match=stored.etag
    )
    assert updated.advisory is True
    assert updated.etag != stored.etag
    with pytest.raises(StaleVersionError) as caught:
        await store.replace(stored.model_copy(update={"advisory": False}), if_match=stored.etag)
    assert caught.value.reason == "intent_modified"
    fetched = await store.get(helper.CUSTOMER, helper.DOMAIN, stored.intent_id)
    assert fetched == updated
    assert await store.get(helper.CUSTOMER, helper.OTHER_DOMAIN, stored.intent_id) is None


async def test_service_lifecycle_executes_once(container: ContainerProxy) -> None:
    store = CosmosIntentStore(container)
    clock = helper.FakeClock()
    service = _service(store, clock)
    drafted = await _draft(service)
    await service.record_validation(drafted.key, helper.MAKER, [helper.passed()])
    presented = await service.present_confirmation(drafted.key, helper.MAKER)
    bound = presented.intent.confirmation_hash
    assert bound is not None

    async def confirm() -> StoredIntent:
        return await service.confirm(
            presented.key,
            helper.MAKER,
            confirmation_hash=bound.root,
            current_target_version=helper.TARGET_VERSION,
            requires_approval=False,
            advisory=False,
        )

    results = await asyncio.gather(confirm(), confirm(), confirm(), return_exceptions=True)
    winners = [r for r in results if isinstance(r, StoredIntent)]
    losers = [r for r in results if isinstance(r, NeuroSphereError)]
    assert len(winners) == 1
    assert len(losers) == 2
    assert all(isinstance(e, StaleVersionError | InvalidTransitionError) for e in losers)
    current = await service.get(presented.key)
    assert current.state == "executing"
    assert current.execution is not None


async def test_list_pages_and_cross_partition_due_scan(container: ContainerProxy) -> None:
    store = CosmosIntentStore(container)
    clock = helper.FakeClock()
    service = _service(store, clock)
    ids = []
    for index in range(5):
        clock.advance(timedelta(seconds=1))
        ids.append((await _draft(service, f"idem-2026-10-20-cosmos-p{index:04d}")).intent_id)
    other = await service.draft(
        helper.MAKER,
        helper.request("idem-2026-10-20-cosmos-other-01"),
        customer_id=helper.CUSTOMER,
        domain_id=helper.OTHER_DOMAIN,
    )
    first = await store.list(helper.CUSTOMER, helper.DOMAIN, limit=2)
    assert [s.intent_id for s in first.items] == ids[::-1][:2]
    second = await store.list(helper.CUSTOMER, helper.DOMAIN, limit=2, cursor=first.next_cursor)
    third = await store.list(helper.CUSTOMER, helper.DOMAIN, limit=2, cursor=second.next_cursor)
    assert [s.intent_id for s in second.items + third.items] == ids[::-1][2:]
    assert third.next_cursor is None
    assert (await store.list(helper.CUSTOMER, helper.DOMAIN, state="validated")).items == ()

    drafted_all = await store.list_in_states(["drafted"], limit=50)
    assert {s.intent_id for s in drafted_all} == {*ids, other.stored.intent_id}
    assert await store.list_in_states(["drafted"], due_before=clock.now) == []
    later = clock.now + timedelta(days=2)
    due = await store.list_in_states(["drafted"], due_before=later, limit=3)
    assert [s.intent_id for s in due] == ids[:3]  # oldest first, bounded

    clock.advance(timedelta(days=2))
    expired = await service.expire_due(limit=100)
    assert len(expired) == 6
    assert all(s.state == "expired" for s in expired)


async def test_execution_control_round_trip(database: DatabaseProxy) -> None:
    created = await create_execution_control_container(database, f"control_{uuid.uuid4().hex[:10]}")
    try:
        control = CosmosExecutionControl(created)
        assert (await control.get(helper.CUSTOMER)).disabled is False
        await control.set(
            helper.CUSTOMER,
            disabled=True,
            reason="incident",
            changed_by="p-admin01",
            now=helper.START,
        )
        with pytest.raises(CapabilityUnavailableError) as caught:
            await require_execution_enabled(control, helper.CUSTOMER)
        assert caught.value.reason == "emergency_disabled"
        assert (await control.get("fabrikam")).disabled is False
        state = await control.set(
            helper.CUSTOMER, disabled=False, reason=None, changed_by="p-admin01", now=helper.START
        )
        assert state.disabled is False
        assert (await control.get(helper.CUSTOMER)) == state
    finally:
        await database.delete_container(created.id)

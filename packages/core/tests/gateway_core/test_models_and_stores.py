"""Gateway models, capability mapping and the in-memory store contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    StaleVersionError,
)
from neurosphere_core.gateway import (
    DiagnosticsState,
    GatewayInventory,
    GatewayRegistration,
    GatewayStore,
    InMemoryGatewayStore,
    gateway_id_for,
)
from neurosphere_core.gateway.capability import capabilities_for, coverage_for
from pydantic import ValidationError

from .fake_arm import RID

T0 = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
CUSTOMER = "contoso"
DOMAIN = "commercial:contoso:catalog:domain:finance"


def _registration(n: int = 0, *, arm_id: str = RID, domain: str = DOMAIN) -> GatewayRegistration:
    return GatewayRegistration(
        id=gateway_id_for(CUSTOMER, domain, arm_id + str(n) if n else arm_id),
        customer_id=CUSTOMER,
        domain_id=domain,
        cloud="commercial",
        arm_resource_id=arm_id,
        name="apim-demo",
        tier="standard_v2",
        created_at=T0 + timedelta(seconds=n),
        updated_at=T0 + timedelta(seconds=n),
        registered_by="pseudo-abc",
    )


def test_model_validates_arm_id_shape() -> None:
    assert _registration().mode == "observe"
    with pytest.raises(ValidationError):
        _registration(arm_id="/subscriptions/x/resourceGroups/y/providers/Other/service/z")


def test_model_forbids_extra_and_non_observe_mode() -> None:
    data = _registration().model_dump()
    with pytest.raises(ValidationError):
        GatewayRegistration.model_validate({**data, "listSecrets": True})
    with pytest.raises(ValidationError):
        GatewayRegistration.model_validate({**data, "mode": "manage"})


def test_workspace_id_must_be_a_guid() -> None:
    data = _registration().model_dump()
    with pytest.raises(ValidationError):
        GatewayRegistration.model_validate({**data, "workspace_id": "not-a-guid"})


def test_gateway_id_is_deterministic_and_case_insensitive() -> None:
    assert gateway_id_for("c", "d", RID) == gateway_id_for("c", "d", RID.lower())
    assert gateway_id_for("c", "d", RID) != gateway_id_for("c", "other", RID)


def test_capabilities_follow_the_matrix() -> None:
    v2 = capabilities_for("standard_v2", "commercial")
    assert set(v2) >= {"llm_token_limit", "gateway_llm_logs", "gateway_mcp_logs", "mcp_server"}
    unknown = capabilities_for("unknown", "commercial")
    assert set(unknown.values()) == {"unverified"}
    # Government Consumption has a documented row: no LLM logs there.
    assert capabilities_for("consumption", "government")["gateway_llm_logs"] == "unavailable"


def test_coverage_counts_only_categories_the_tier_can_emit() -> None:
    caps = {"gateway_llm_logs": "available", "gateway_mcp_logs": "unavailable"}
    assert coverage_for(caps, DiagnosticsState(gateway_logs=True, gateway_llm_logs=True)) == 1.0
    assert coverage_for(caps, DiagnosticsState(gateway_logs=True)) == 0.5
    assert coverage_for({}, DiagnosticsState()) == 0.0
    # An unverified category is still expected (it may exist).
    assert coverage_for({}, DiagnosticsState(gateway_logs=True)) == pytest.approx(1 / 3)


async def test_store_satisfies_protocol() -> None:
    assert isinstance(InMemoryGatewayStore(), GatewayStore)


async def test_create_get_and_duplicate_conflict() -> None:
    store = InMemoryGatewayStore()
    created = await store.create(_registration())
    assert created.etag
    got = await store.get(CUSTOMER, DOMAIN, created.id)
    assert got == created
    assert await store.get(CUSTOMER, "commercial:contoso:catalog:domain:hr", created.id) is None
    with pytest.raises(StaleVersionError) as info:
        await store.create(_registration())
    assert info.value.reason == "gateway_already_registered"


async def test_replace_is_etag_conditional() -> None:
    store = InMemoryGatewayStore()
    created = await store.create(_registration())
    changed = created.model_copy(update={"last_sync_status": "ok"})
    assert created.etag is not None
    saved = await store.replace(changed, if_match=created.etag)
    assert saved.etag != created.etag
    with pytest.raises(StaleVersionError) as info:
        await store.replace(changed, if_match=created.etag)
    assert info.value.reason == "gateway_modified"


async def test_list_is_partition_scoped_newest_first_with_cursor() -> None:
    store = InMemoryGatewayStore()
    for n in range(1, 4):
        await store.create(_registration(n))
    await store.create(_registration(9, domain="commercial:contoso:catalog:domain:hr"))
    first = await store.list(CUSTOMER, DOMAIN, limit=2)
    assert len(first.items) == 2
    assert first.next_cursor is not None
    second = await store.list(CUSTOMER, DOMAIN, cursor=first.next_cursor, limit=2)
    assert len(second.items) == 1
    assert second.next_cursor is None
    created = [r.created_at for r in (*first.items, *second.items)]
    assert created == sorted(created, reverse=True)
    with pytest.raises(InvalidSchemaError):
        await store.list(CUSTOMER, DOMAIN, cursor="garbage")


async def test_inventory_is_replaced_not_merged() -> None:
    store = InMemoryGatewayStore()
    reg = await store.create(_registration())
    from neurosphere_core.gateway import ApiEntry

    first = GatewayInventory(
        gateway_id=reg.id, taken_at=T0, apis=[ApiEntry(id="a"), ApiEntry(id="b")]
    )
    second = GatewayInventory(
        gateway_id=reg.id, taken_at=T0 + timedelta(hours=1), apis=[ApiEntry(id="c")]
    )
    await store.put_inventory(CUSTOMER, DOMAIN, first)
    await store.put_inventory(CUSTOMER, DOMAIN, second)
    got = await store.get_inventory(CUSTOMER, DOMAIN, reg.id)
    assert got is not None
    assert [a.id for a in got.apis] == ["c"]
    assert await store.get_inventory(CUSTOMER, DOMAIN, "gw-" + "f" * 32) is None


async def test_outage_is_never_empty() -> None:
    store = InMemoryGatewayStore()
    store.fail_with(DependencyTransientError("down", reason="gateway_store_unavailable"))
    with pytest.raises(DependencyTransientError):
        await store.list(CUSTOMER, DOMAIN)
    with pytest.raises(DependencyTransientError):
        await store.get(CUSTOMER, DOMAIN, "gw-" + "0" * 32)

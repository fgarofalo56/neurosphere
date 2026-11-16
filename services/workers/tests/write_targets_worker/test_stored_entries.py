"""PRP-54 item 2: write targets registered from stored entries, keyed by domain."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from action_executor.apim_support import ARM_ID, GW, registration  # pyright: ignore[reportMissingImports]
from action_executor.executor_support import CUSTOMER, DOMAIN, FakeCredential  # pyright: ignore[reportMissingImports]
from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_connector_apim_gateway import ApimGatewayConnector, ApplyRecord, InMemoryApim
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.gateway import InMemoryGatewayRecordStore, InMemoryGatewayStore
from neurosphere_workers.actions import DEFAULT_ACTION_CONNECTORS, resolve_connector
from neurosphere_workers.runtime.factories import (
    WriteTargetEntry,
    WriteTargetSeams,
    WriteTargetSources,
    register_write_targets,
)
from neurosphere_workers.runtime.settings import ApimWriteSettings, FoundryWriteSettings

COMMERCIAL = Settings(env="local", cloud=CloudName.COMMERCIAL)
DOMAIN_B = "commercial:contoso:catalog:domain:finance"
GW_B = "gw-" + "e" * 32
ARM_B = ARM_ID.replace("apim-demo", "apim-b")


async def _gateway_store() -> InMemoryGatewayStore:
    store = InMemoryGatewayStore()
    await store.create(registration())
    other = registration(domain=DOMAIN_B).model_copy(
        update={"id": GW_B, "arm_resource_id": ARM_B, "name": "apim-b"}
    )
    await store.create(other)
    return store


async def _register(
    entries: list[WriteTargetEntry],
    store: InMemoryGatewayStore | None,
    *,
    registry: WriteTargetRegistry | None = None,
) -> WriteTargetRegistry:
    registry = registry if registry is not None else WriteTargetRegistry()
    seams = WriteTargetSeams(
        credential=FakeCredential(),  # type: ignore[arg-type]
        apim_arm=InMemoryApim(),
        apim_records=InMemoryGatewayRecordStore(ApplyRecord),
    )
    async with ClientLifetime() as lifetime:
        await register_write_targets(
            registry,
            settings=COMMERCIAL,
            customer_id=CUSTOMER,
            lifetime=lifetime,
            foundry=FoundryWriteSettings(),
            apim=ApimWriteSettings(),
            sources=WriteTargetSources(gateway_store=store),
            seams=seams,
            entries=entries,
        )
    return registry


def _skips(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        str(getattr(r, "reason", ""))
        for r in caplog.records
        if getattr(r, "event", None) == "write_target.skipped"
    ]


def _bound(connector: Any) -> str:
    assert isinstance(connector, ApimGatewayConnector)
    return str(connector.gateway.gateway_id)


async def test_two_gateways_two_domains_each_domain_reaches_its_own_gateway() -> None:
    registry = await _register(
        [WriteTargetEntry("apim", ARM_ID), WriteTargetEntry("apim", ARM_B)],
        await _gateway_store(),
    )
    assert registry.names() == ("apim-gateway",)
    assert registry.target_keys("apim-gateway") == tuple(sorted([DOMAIN, DOMAIN_B]))
    a = resolve_connector(
        registry, DEFAULT_ACTION_CONNECTORS, "gateway_mode_change", target_key=DOMAIN
    )
    b = resolve_connector(
        registry, DEFAULT_ACTION_CONNECTORS, "gateway_mode_change", target_key=DOMAIN_B
    )
    assert _bound(a) == GW
    assert _bound(b) == GW_B


async def test_a_domain_without_a_target_is_advisory() -> None:
    registry = await _register([WriteTargetEntry("apim", ARM_ID)], await _gateway_store())
    with pytest.raises(Exception) as ei:
        resolve_connector(
            registry, DEFAULT_ACTION_CONNECTORS, "gateway_mode_change", target_key="other:dom"
        )
    assert getattr(ei.value, "reason", None) == "capability_unavailable"


async def test_an_unbuildable_entry_is_skipped_and_the_rest_register(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="neurosphere.workers.runtime")
    unknown = ARM_ID.replace("apim-demo", "apim-unregistered")
    registry = await _register(
        [WriteTargetEntry("apim", unknown), WriteTargetEntry("apim", ARM_B)],
        await _gateway_store(),
    )
    assert registry.target_keys("apim-gateway") == (DOMAIN_B,)
    assert _skips(caplog) == ["gateway_not_registered"]


async def test_the_second_entry_for_one_domain_is_refused(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="neurosphere.workers.runtime")
    registry = await _register(
        [WriteTargetEntry("apim", ARM_ID), WriteTargetEntry("apim", ARM_ID)],
        await _gateway_store(),
    )
    assert registry.target_keys("apim-gateway") == (DOMAIN,)
    assert _skips(caplog) == ["write_target_duplicate_domain"]


async def test_a_disabled_entry_is_silent() -> None:
    registry = await _register(
        [WriteTargetEntry("apim", ARM_ID, enabled=False)], await _gateway_store()
    )
    assert registry.names() == ()


async def test_a_gateway_in_another_cloud_is_never_registered(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="neurosphere.workers.runtime")
    store = InMemoryGatewayStore()
    await store.create(registration(cloud="government"))
    registry = await _register([WriteTargetEntry("apim", ARM_ID)], store)
    assert registry.names() == ()
    assert _skips(caplog) == ["gateway_cloud_mismatch"]


async def test_a_malformed_foundry_entry_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="neurosphere.workers.runtime")
    registry = await _register([WriteTargetEntry("foundry", "/subscriptions/x")], None)
    assert registry.names() == ()
    assert _skips(caplog) == ["foundry_config_invalid"]


async def test_no_entries_keeps_the_env_path() -> None:
    registry = WriteTargetRegistry()
    async with ClientLifetime() as lifetime:
        await register_write_targets(
            registry,
            settings=COMMERCIAL,
            customer_id=CUSTOMER,
            lifetime=lifetime,
            foundry=FoundryWriteSettings(),
            apim=ApimWriteSettings(),
            entries=(),
        )
    assert registry.names() == ()

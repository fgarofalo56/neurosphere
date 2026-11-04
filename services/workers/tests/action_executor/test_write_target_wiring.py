"""Write-target registration from settings (PRP-35 item 4, issue #132).

``register_write_targets`` is what the executor worker (``build_actions``) and the API
composition both call: nothing enabled -> empty registry; Foundry/APIM registered only when
enabled, complete and write-capable; advisory (Government, permission shortfall) and
cross-cloud targets are skipped with a logged reason and never registered; one connector per
name (first wins).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest
from neurosphere_connector.write import WriteRequest, WriteTargetRegistry
from neurosphere_connector_apim_gateway import ApimGatewayConnector, ApplyRecord, InMemoryApim
from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.gateway import InMemoryGatewayRecordStore, InMemoryGatewayStore
from neurosphere_workers.actions import DEFAULT_ACTION_CONNECTORS, resolve_connector
from neurosphere_workers.runtime.factories import (
    SUPPORTED_WRITE_CONNECTORS,
    WriteTargetSeams,
    WriteTargetSources,
    load_write_target_settings,
    register_write_targets,
)
from neurosphere_workers.runtime.settings import ApimWriteSettings, FoundryWriteSettings

from .apim_support import GW, registration
from .executor_support import (
    CUSTOMER,
    DOMAIN,
    FOUNDRY_SWAP_OPS,
    SUB,
    TARGET_ID,
    TARGET_VERSION,
    CountingConnector,
    FakeArm,
    FakeCredential,
)

COMMERCIAL = Settings(env="local", cloud=CloudName.COMMERCIAL)
GOVERNMENT = Settings(env="local", cloud=CloudName.GOVERNMENT)
WRITE_PERMS = {"value": [{"actions": ["Microsoft.CognitiveServices/*"], "notActions": []}]}
READ_PERMS = {"value": [{"actions": ["Microsoft.CognitiveServices/*/read"], "notActions": []}]}
FOUNDRY_ON = FoundryWriteSettings(
    enabled=True,
    subscription_id=SUB,
    resource_group="rg-ai",
    account="acct1",
    location="eastus2",
)
OFF = FoundryWriteSettings()
APIM_OFF = ApimWriteSettings()
APIM_ON = ApimWriteSettings(enabled=True, gateway_id=GW, domain_id=DOMAIN)


class PermissionedArm(FakeArm):
    """The executor tests' Foundry ARM plus the Permissions - List For Resource read."""

    def __init__(self, permissions: dict[str, Any]) -> None:
        super().__init__()
        self.permissions = permissions

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/providers/Microsoft.Authorization/permissions"):
            self.requests.append(request)
            return httpx.Response(200, json=self.permissions)
        return super()._handle(request)


def _swap_request() -> WriteRequest:
    return WriteRequest(
        target=TargetRef(canonical_id=TARGET_ID, entity_type="model_deployment"),
        target_version=TARGET_VERSION,
        proposed_diff=ProposedDiff(
            format="json_patch",
            operations=[PatchOperation.model_validate(op) for op in FOUNDRY_SWAP_OPS],
        ),
    )


async def _register(
    *,
    settings: Settings = COMMERCIAL,
    foundry: FoundryWriteSettings = OFF,
    apim: ApimWriteSettings = APIM_OFF,
    arm: FakeArm | None = None,
    store: InMemoryGatewayStore | None = None,
    apim_arm: InMemoryApim | None = None,
    registry: WriteTargetRegistry | None = None,
) -> WriteTargetRegistry:
    registry = registry if registry is not None else WriteTargetRegistry()
    seams = WriteTargetSeams(
        credential=FakeCredential(),  # type: ignore[arg-type]
        foundry_http=None if arm is None else arm.client(),
        apim_arm=apim_arm,
        apim_records=InMemoryGatewayRecordStore(ApplyRecord),
    )
    async with ClientLifetime() as lifetime:
        await register_write_targets(
            registry,
            settings=settings,
            customer_id=CUSTOMER,
            lifetime=lifetime,
            foundry=foundry,
            apim=apim,
            sources=WriteTargetSources(gateway_store=store),
            seams=seams,
        )
    return registry


def _skips(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        str(getattr(r, "reason", ""))
        for r in caplog.records
        if getattr(r, "event", None) == "write_target.skipped"
    ]


# -- nothing configured ---------------------------------------------------------------------------


async def test_nothing_enabled_leaves_the_registry_empty_and_builds_nothing() -> None:
    registry = WriteTargetRegistry()
    async with ClientLifetime() as lifetime:
        names = await register_write_targets(
            registry,
            settings=COMMERCIAL,
            customer_id=CUSTOMER,
            lifetime=lifetime,
            foundry=OFF,
            apim=APIM_OFF,
        )
    assert names == ()
    assert registry.names() == ()
    # The executor fails such an intent closed: no connector call, no pretend change.
    with pytest.raises(CapabilityUnavailableError):
        resolve_connector(registry, DEFAULT_ACTION_CONNECTORS, "model_deployment_swap")


def test_settings_default_off_and_read_their_own_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("NS_FOUNDRY_ENABLED", "NS_APIM_ENABLED", "NS_APIM_GATEWAY_ID"):
        monkeypatch.delenv(name, raising=False)
    foundry, apim = load_write_target_settings()
    assert (foundry.enabled, apim.enabled) == (False, False)
    monkeypatch.setenv("NS_FOUNDRY_ENABLED", "true")
    monkeypatch.setenv("NS_FOUNDRY_ACCOUNT", "acct1")
    monkeypatch.setenv("NS_APIM_GATEWAY_ID", GW)
    foundry, apim = load_write_target_settings()
    assert foundry.enabled and foundry.account == "acct1" and not foundry.complete
    assert apim.gateway_id == GW and not apim.enabled
    monkeypatch.setenv("NS_APIM_ENABLED", "perhaps")
    with pytest.raises(ValueError):
        load_write_target_settings()


def test_registered_names_are_the_action_connector_names() -> None:
    assert frozenset({"foundry-model-swap", "apim-gateway"}) == SUPPORTED_WRITE_CONNECTORS


# -- Foundry --------------------------------------------------------------------------------------


async def test_foundry_flag_and_fake_arm_register_the_swap_and_a_dry_run_returns_a_real_diff() -> (
    None
):
    arm = PermissionedArm(WRITE_PERMS)
    registry = await _register(foundry=FOUNDRY_ON, arm=arm)
    assert registry.names() == ("foundry-model-swap",)
    connector = resolve_connector(
        registry, DEFAULT_ACTION_CONNECTORS, "model_deployment_swap", "model_deployment"
    )
    planned = await connector.dry_run(_swap_request())
    assert planned.would_change is True
    assert planned.target_version == TARGET_VERSION
    assert [op.path for op in planned.planned_diff.operations] == [
        "/properties/model/name",
        "/properties/model/name",
        "/properties/model/version",
    ]
    assert arm.puts == []  # a dry run writes nothing


async def test_a_permission_shortfall_yields_the_advisory_connector_which_is_not_registered(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="neurosphere.workers.runtime")
    arm = PermissionedArm(READ_PERMS)
    registry = await _register(foundry=FOUNDRY_ON, arm=arm)
    assert registry.names() == ()
    assert _skips(caplog) == ["connector_advisory"]
    assert arm.puts == []


async def test_government_yields_the_advisory_connector_and_no_arm_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="neurosphere.workers.runtime")
    arm = PermissionedArm(WRITE_PERMS)
    registry = await _register(settings=GOVERNMENT, foundry=FOUNDRY_ON, arm=arm)
    assert registry.names() == ()
    assert _skips(caplog) == ["connector_advisory"]
    assert arm.requests == []  # never rerouted to a Commercial host


@pytest.mark.parametrize(
    ("update", "reason"),
    [
        ({"location": None}, "foundry_config_incomplete"),
        ({"subscription_id": "not-a-guid"}, "foundry_config_invalid"),
        ({"account": "bad/../name"}, "foundry_config_invalid"),
    ],
)
async def test_incomplete_or_malformed_foundry_config_is_skipped(
    caplog: pytest.LogCaptureFixture, update: dict[str, Any], reason: str
) -> None:
    caplog.set_level(logging.WARNING, logger="neurosphere.workers.runtime")
    arm = PermissionedArm(WRITE_PERMS)
    registry = await _register(foundry=FOUNDRY_ON.model_copy(update=update), arm=arm)
    assert registry.names() == ()
    assert _skips(caplog) == [reason]
    assert arm.requests == []


async def test_a_disabled_foundry_target_is_never_contacted() -> None:
    arm = PermissionedArm(WRITE_PERMS)
    registry = await _register(foundry=FOUNDRY_ON.model_copy(update={"enabled": False}), arm=arm)
    assert registry.names() == ()
    assert arm.requests == []


async def test_a_duplicate_name_is_skipped_and_the_first_connector_stays(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="neurosphere.workers.runtime")
    first = CountingConnector("foundry-model-swap")
    registry = WriteTargetRegistry()
    registry.register(first)
    await _register(foundry=FOUNDRY_ON, arm=PermissionedArm(WRITE_PERMS), registry=registry)
    assert registry.names() == ("foundry-model-swap",)
    assert registry.get("foundry-model-swap") is first
    assert _skips(caplog) == ["write_target_duplicate"]


# -- APIM -----------------------------------------------------------------------------------------


async def _gateways(**kwargs: Any) -> InMemoryGatewayStore:
    store = InMemoryGatewayStore()
    await store.create(registration(**kwargs))
    return store


async def test_apim_with_an_in_memory_gateway_registers_the_gateway_connector() -> None:
    store = await _gateways()
    registry = await _register(apim=APIM_ON, store=store, apim_arm=InMemoryApim())
    assert registry.names() == ("apim-gateway",)
    connector = registry.get("apim-gateway")
    assert isinstance(connector, ApimGatewayConnector)
    assert connector.gateway.gateway_id == GW


async def test_foundry_and_apim_together_register_both() -> None:
    store = await _gateways()
    registry = await _register(
        foundry=FOUNDRY_ON,
        arm=PermissionedArm(WRITE_PERMS),
        apim=APIM_ON,
        store=store,
        apim_arm=InMemoryApim(),
    )
    assert registry.names() == ("apim-gateway", "foundry-model-swap")


async def test_a_government_gateway_is_advisory_and_not_registered(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="neurosphere.workers.runtime")
    apim = InMemoryApim()
    store = await _gateways(cloud="government")
    registry = await _register(settings=GOVERNMENT, apim=APIM_ON, store=store, apim_arm=apim)
    assert registry.names() == ()
    assert _skips(caplog) == ["connector_advisory"]
    assert apim.calls == []


@pytest.mark.parametrize(
    ("apim_settings", "store_kwargs", "reason"),
    [
        (APIM_ON, {"cloud": "government"}, "gateway_cloud_mismatch"),
        (
            APIM_ON,
            {"domain": "commercial:contoso:catalog:domain:finance"},
            "gateway_not_registered",
        ),
        (APIM_ON.model_copy(update={"domain_id": None}), {}, "apim_config_incomplete"),
        (APIM_ON.model_copy(update={"gateway_id": "gw-nope"}), {}, "apim_config_invalid"),
    ],
)
async def test_unusable_apim_targets_are_skipped_with_a_reason(
    caplog: pytest.LogCaptureFixture,
    apim_settings: ApimWriteSettings,
    store_kwargs: dict[str, Any],
    reason: str,
) -> None:
    caplog.set_level(logging.WARNING, logger="neurosphere.workers.runtime")
    apim = InMemoryApim()
    store = await _gateways(**store_kwargs)
    registry = await _register(apim=apim_settings, store=store, apim_arm=apim)
    assert registry.names() == ()
    assert _skips(caplog) == [reason]
    assert apim.calls == []


async def test_apim_without_a_gateway_registry_is_skipped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="neurosphere.workers.runtime")
    registry = await _register(apim=APIM_ON, store=None, apim_arm=InMemoryApim())
    assert registry.names() == ()
    assert _skips(caplog) == ["gateway_store_unconfigured"]

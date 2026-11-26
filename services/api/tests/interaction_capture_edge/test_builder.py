"""PRP-103 item 4: the ``interactions`` composition builder and component ``interaction_capture``.

The builder is driven directly over a hand-made :class:`CompositionState` (no emulator, no
network): the ``STORED_SETTINGS`` snapshot carries the ``interaction_capture`` setting, the audit
repository is published as the data builder would, and the ingest service sits on ``app.state``
as ``main.create``'s bootstrap leaves it. Startup hooks are awaited explicitly.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from fastapi import FastAPI
from neurosphere_api.admin.system.stored import STORED_SETTINGS
from neurosphere_api.ingest import InMemoryPublisher
from neurosphere_api.ingest.capture import EdgeCapture, EdgeCaptureStats
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    BuildContext,
    CompositionState,
    default_builders,
    interactions,
)
from neurosphere_api.runtime.overrides import CompositionOverrides
from neurosphere_api.runtime.status import OPTIONAL_COMPONENTS, ComponentRegistry
from neurosphere_contracts.admin.v1.system_setting import SystemSetting
from neurosphere_core.admin.runtime import StoredSetting, StoredSettingsSnapshot
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.interactions import (
    ENV_INTERACTION_LOCAL_KEY_FILE,
    InMemoryCapturePolicyStore,
    InMemoryInteractionStore,
    parse_capture_policy,
)

from . import edge_helpers as h
from .edge_helpers import CUSTOMER, DOMAIN, STRUCTURED, TELEMETRY_TYPE

COMPONENT = "interaction_capture"


def _account_id(provider: str = "Microsoft.Storage/storageAccounts/stnscontent") -> str:
    # Subscription GUID built at runtime (no GUID-shaped literal in the source).
    return f"/subscriptions/{uuid.uuid4()}/resourceGroups/rg-ns/providers/{provider}"


def _capture_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kek_provider": "local_development",
        "kek_uri": None,
        "content_storage_account_resource_id": _account_id(),
        "content_container": "interaction-content",
        "credential": {"kind": "managed_identity", "managed_identity_client_id": None},
        "shed_capture_at_queue_percent": 75,
        "max_content_chars_per_interaction": 4096,
    }
    body.update(overrides)
    return body


def _snapshot(*, enabled: bool = True, **body: Any) -> StoredSettingsSnapshot:
    setting = SystemSetting.model_validate(
        {
            "schema_version": "1.0.0",
            "setting_key": "interaction_capture",
            "enabled": enabled,
            "interaction_capture": _capture_body(**body),
        }
    )
    entry = StoredSetting(
        "interaction_capture",  # pyright: ignore[reportArgumentType]
        "system.interaction_capture",
        setting,
        1,
        '"etag-1"',
    )
    return StoredSettingsSnapshot(
        status="loaded", entries=MappingProxyType({"interaction_capture": entry})
    )


class SpyPolicyStore(InMemoryCapturePolicyStore):
    """Counts every read so a test can prove the policy container is never touched."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    async def list(self, **kwargs: Any) -> Any:  # type: ignore[override]
        self.calls.append("list")
        return await super().list(**kwargs)

    async def get(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        self.calls.append("get")
        return await super().get(*args, **kwargs)


class Harness:
    def __init__(
        self,
        tmp_path: Path,
        *,
        env: str = "local",
        snapshot: StoredSettingsSnapshot | None = None,
        backends: dict[str, object] | None = None,
        environ: dict[str, str] | None = None,
        ingest: bool = True,
    ) -> None:
        self.publisher = InMemoryPublisher()
        self.registration = h.producer()
        self.app = FastAPI()
        if ingest:
            self.app.state.ingest_service = h.service(self.publisher, self.registration)
        self.cosmos_calls: list[int] = []
        self.audit = h.RecordingAudit()
        env_values = {ENV_INTERACTION_LOCAL_KEY_FILE: str(tmp_path / "kek.bin"), **(environ or {})}

        def no_cosmos() -> Any:
            self.cosmos_calls.append(1)
            from neurosphere_api.runtime.builders import ComponentUnavailableError

            raise ComponentUnavailableError("cosmos_unconfigured")

        self.state = CompositionState(
            app=self.app,
            settings=Settings(env=env, cloud=CloudName.COMMERCIAL),  # type: ignore[arg-type]
            overrides=CompositionOverrides(
                backends=MappingProxyType(dict(backends or {})),
                cosmos_client_factory=no_cosmos,
            ),
            registry=ComponentRegistry(),
            environ=env_values,
            lifetime=ClientLifetime(),
        )
        if snapshot is not None:
            self.state.shared[STORED_SETTINGS.name] = snapshot
        self.state.shared[AUDIT_REPOSITORY.name] = self.audit
        interactions.build(BuildContext(self.state, interactions.BUILDER))

    async def start(self) -> None:
        for _name, hook in self.state.startup:
            await hook()

    @property
    def status(self) -> tuple[str, str | None]:
        return (
            self.state.registry.get(COMPONENT).state,
            self.app.state.interaction_capture_off_reason,
        )

    async def send(self, data: dict[str, Any]) -> Any:
        return await self.app.state.ingest_service.ingest_events(
            self.registration,
            json.dumps(h.ce(TELEMETRY_TYPE, data)).encode(),
            STRUCTURED,
            correlation_id="req-builder-1",
        )


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_AUTH_CUSTOMER_ID", CUSTOMER)
    for name in (interactions.ENV_QUEUE_CAPACITY, "NS_INTERACTION_CAPTURE_MAX_ITEMS_PER_REQUEST"):
        monkeypatch.delenv(name, raising=False)


def _retention(opt_in: bool = True) -> dict[str, object]:
    return {"retention_policy": h.retention(opt_in=opt_in)}


# --- registration -------------------------------------------------------------------------------


def test_component_is_optional_and_the_builder_runs_after_edge_and_lifecycle() -> None:
    assert COMPONENT in OPTIONAL_COMPONENTS
    names = [spec.name for spec in default_builders()]
    assert names.index("edge") < names.index("lifecycle") < names.index("interactions")
    assert interactions.BUILDER in default_builders()
    assert interactions.BUILDER.components == (COMPONENT,)


# --- off by default -----------------------------------------------------------------------------


async def test_off_by_default_is_disabled_setting_off_with_no_io(tmp_path: Path) -> None:
    spy = SpyPolicyStore()
    harness = Harness(tmp_path, backends={"interaction_capture_policy_store": spy, **_retention()})
    await harness.start()
    assert harness.status == ("disabled", "setting_off")
    assert not harness.state.registry.get(COMPONENT).blocks_readiness
    assert harness.state.startup == []
    assert spy.calls == []
    assert harness.cosmos_calls == []
    assert harness.app.state.interaction_capture is None
    assert harness.app.state.interaction_capture_stats is None
    assert harness.app.state.interaction_capture_policy_store is None
    assert harness.app.state.ingest_service.capture is None
    assert not (tmp_path / "kek.bin").exists()  # no key wrapper was built


async def test_setting_present_but_disabled_reads_nothing(tmp_path: Path) -> None:
    spy = SpyPolicyStore()
    harness = Harness(
        tmp_path,
        snapshot=_snapshot(enabled=False),
        backends={"interaction_capture_policy_store": spy, **_retention()},
    )
    await harness.start()
    assert harness.status == ("disabled", "setting_off")
    assert spy.calls == []
    assert harness.cosmos_calls == []
    assert not (tmp_path / "kek.bin").exists()


async def test_setting_on_but_retention_off_is_retention_not_enabled(tmp_path: Path) -> None:
    spy = SpyPolicyStore()
    harness = Harness(
        tmp_path,
        snapshot=_snapshot(),
        backends={"interaction_capture_policy_store": spy, **_retention(opt_in=False)},
    )
    await harness.start()
    assert harness.status == ("disabled", "retention_not_enabled")
    assert spy.calls == []
    assert harness.app.state.ingest_service.capture is None


async def test_no_ingest_service_is_ingest_disabled(tmp_path: Path) -> None:
    harness = Harness(tmp_path, snapshot=_snapshot(), backends=_retention(), ingest=False)
    assert harness.status == ("disabled", "ingest_disabled")


# --- configuration missing outside local --------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ({"kek_provider": "key_vault_key", "kek_uri": None}, "key_vault_not_configured"),
        (
            {
                "kek_provider": "key_vault_key",
                "kek_uri": "https://ns-kv.vault.azure.net/keys/ns-content-kek",
                "content_storage_account_resource_id": _account_id(
                    "Microsoft.KeyVault/vaults/ns-kv"
                ),
            },
            "blob_not_configured",
        ),
        ({"kek_provider": "local_development"}, "local_key_not_allowed"),
        (
            {
                "kek_provider": "key_vault_key",
                "kek_uri": "https://ns-kv.vault.usgovcloudapi.net/keys/ns-content-kek",
            },
            "key_host_refused",
        ),
        (
            {
                "kek_provider": "key_vault_key",
                "kek_uri": "https://ns-kv.vault.azure.net/keys/ns-content-kek",
            },
            "cosmos_unconfigured",
        ),
    ],
)
async def test_missing_configuration_outside_local_is_disabled_and_ingest_serves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: dict[str, Any], reason: str
) -> None:
    monkeypatch.setenv("NS_ENV", "dev")
    harness = Harness(tmp_path, env="dev", snapshot=_snapshot(**body), backends=_retention())
    await harness.start()
    state, off = harness.status
    assert (state, off) == ("disabled", reason)
    assert not harness.state.registry.get(COMPONENT).blocks_readiness
    assert harness.app.state.ingest_service.capture is None

    mark = h.canary()
    result = await harness.send(h.telemetry_data("evt-off-1", domain_id=DOMAIN, prompt=mark))
    assert result.accepted == 1
    (message,) = harness.publisher.messages
    assert "payload_ref" not in message.data or message.data["payload_ref"] is None
    assert mark not in message.to_bytes().decode()


async def test_bad_queue_capacity_names_the_variable(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=interactions.ENV_QUEUE_CAPACITY) as info:
        interactions.queue_capacity_from_env({interactions.ENV_QUEUE_CAPACITY: "lots"})
    assert "lots" not in str(info.value)
    with pytest.raises(ValueError, match=interactions.ENV_QUEUE_CAPACITY):
        interactions.queue_capacity_from_env({interactions.ENV_QUEUE_CAPACITY: "0"})
    assert interactions.queue_capacity_from_env({}) == interactions.DEFAULT_QUEUE_CAPACITY
    assert interactions.queue_capacity_from_env({interactions.ENV_QUEUE_CAPACITY: "8"}) == 8

    harness = Harness(
        tmp_path,
        snapshot=_snapshot(),
        backends=_retention(),
        environ={interactions.ENV_QUEUE_CAPACITY: "lots"},
    )
    assert harness.status == ("disabled", "capture_env_invalid")


# --- local, seeded policy: active ---------------------------------------------------------------


async def test_local_seeded_policy_is_ok_and_attaches_the_edge(tmp_path: Path) -> None:
    harness = Harness(tmp_path, snapshot=_snapshot(), backends=_retention())
    assert harness.status == ("disabled", "startup_pending")
    policy_store = harness.app.state.interaction_capture_policy_store
    assert isinstance(policy_store, InMemoryCapturePolicyStore)
    await policy_store.create(parse_capture_policy(h.policy_doc()))

    await harness.start()

    assert harness.status == ("ok", None)
    edge = harness.app.state.interaction_capture
    assert isinstance(edge, EdgeCapture)
    assert harness.app.state.ingest_service.capture is edge
    assert isinstance(harness.app.state.interaction_capture_stats, EdgeCaptureStats)
    assert harness.app.state.interaction_capture_stats is edge.stats
    assert edge.status() is None
    assert edge.max_items_per_request == 100
    assert edge.pipeline.shed_threshold == 48  # 75 % of the default queue capacity 64
    assert isinstance(edge.pipeline._store, InMemoryInteractionStore)  # pyright: ignore[reportPrivateUsage]
    assert harness.cosmos_calls  # the shared client was asked for first

    mark = h.canary()
    result = await harness.send(
        h.telemetry_data("evt-on-1", domain_id=DOMAIN, prompt=f"hello {mark}")
    )
    assert result.accepted == 1
    (message,) = harness.publisher.messages
    ref = message.data["payload_ref"]
    assert ref["redaction_state"] in ("redacted", "not_required")
    assert ref["capture_policy_id"] == h.POLICY_ID
    assert ref["pointer"] == f"interaction:{ref['interaction_id']}"
    assert mark not in message.to_bytes().decode()
    assert edge.stats.snapshot()["captured"] == 1
    assert [d.operation for _chain, d in harness.audit.drafts] == ["interaction.capture"]


async def test_local_without_policy_is_disabled_no_policy(tmp_path: Path) -> None:
    harness = Harness(tmp_path, snapshot=_snapshot(), backends=_retention())
    await harness.start()
    assert harness.status == ("disabled", "no_policy")
    assert isinstance(harness.app.state.interaction_capture, EdgeCapture)  # status route reads it
    assert harness.app.state.ingest_service.capture is None  # inactive: ingest path unchanged


async def test_policy_store_failure_at_startup_is_disabled_not_failed(tmp_path: Path) -> None:
    class Broken(InMemoryCapturePolicyStore):
        async def list(self, **kwargs: Any) -> Any:  # type: ignore[override]
            raise RuntimeError("store down")

    harness = Harness(
        tmp_path,
        snapshot=_snapshot(),
        backends={"interaction_capture_policy_store": Broken(), **_retention()},
    )
    await harness.start()
    assert harness.status == ("disabled", "policy_store_unavailable")
    assert not harness.state.registry.get(COMPONENT).blocks_readiness
    assert harness.app.state.ingest_service.capture is None


async def test_hung_policy_read_times_out_as_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Hung(InMemoryCapturePolicyStore):
        async def list(self, **kwargs: Any) -> Any:  # type: ignore[override]
            await asyncio.Event().wait()

    monkeypatch.setattr(interactions, "_POLICY_READ_TIMEOUT_SECONDS", 0.05)
    harness = Harness(
        tmp_path,
        snapshot=_snapshot(),
        backends={"interaction_capture_policy_store": Hung(), **_retention()},
    )
    await harness.start()
    assert harness.status == ("disabled", "policy_store_unavailable")
    assert harness.app.state.ingest_service.capture is None

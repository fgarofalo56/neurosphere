"""Vault credential handling: no leaks anywhere, rotation applies without restart."""

from __future__ import annotations

import copy
import json
import logging
import pickle

import pytest
from neurosphere_connector import (
    BaseConnector,
    CredentialBroker,
    SecretValue,
    StaticCredentialResolver,
    build_manifest,
)
from neurosphere_contracts.connectors.v1.connector_manifest import (
    ConnectorManifest,
    CredentialRef,
    Granularity,
)
from neurosphere_core.errors import CapabilityUnavailableError, DependencyTransientError
from pydantic import BaseModel, ConfigDict

# Assembled at runtime so secret scanners never see a literal credential-shaped string.
SECRET = "s3cr" + "et-value-" + "Zx9Qm4Lr7Tb2"
SECRET_2 = "rot4ted-" + "Yh5Kd1Np6Wc8"
REF = CredentialRef(
    name="api_key", vault_ref="https://kv-test01.vault.azure.net/secrets/provider-api-key"
)


def _manifest() -> ConnectorManifest:
    return build_manifest(
        name="demo_connector",
        version="0.1.0",
        capabilities=["telemetry_ingest"],
        supported_clouds=["commercial"],
        granularity=Granularity(time_grain="event", subject_level="request"),
        credential_refs=[REF],
    )


class _Demo(BaseConnector):
    @property
    def manifest(self) -> ConnectorManifest:
        return _manifest()

    async def call_provider(self) -> str:
        secret = await self.credential("api_key")
        return secret.reveal()


class _Holder(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    s: SecretValue


def _resolver() -> StaticCredentialResolver:
    return StaticCredentialResolver({REF.vault_ref: SECRET})


def test_secret_wrapper_never_exposes_value() -> None:
    s = SecretValue(SECRET)
    h = _Holder(s=s)
    rendered = [repr(s), str(s), f"{s}", f"{s!r}", repr(h), str(h)]
    rendered.append(json.dumps(h.model_dump(mode="json")))
    rendered.append(json.dumps(h.model_dump(mode="python"), default=str))
    rendered.append(h.model_dump_json())
    assert all(SECRET not in r for r in rendered)
    assert s.reveal() == SECRET
    assert copy.deepcopy(s) is s
    with pytest.raises(TypeError):
        pickle.dumps(s)


async def test_manifest_carries_reference_only() -> None:
    connector = _Demo(credentials=CredentialBroker(_resolver(), [REF]))
    await connector.call_provider()
    dumped = connector.manifest.model_dump_json()
    assert SECRET not in dumped
    assert REF.vault_ref in dumped


async def test_value_never_reaches_logs_or_exceptions(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    class Leaky(StaticCredentialResolver):
        async def resolve(self, ref: CredentialRef) -> SecretValue:
            raise RuntimeError(f"vault said no for {SECRET}")

    bad = _Demo(credentials=CredentialBroker(Leaky({}), [REF]))
    with pytest.raises(DependencyTransientError) as info:
        await bad.call_provider()
    assert SECRET not in str(info.value)
    assert SECRET not in repr(info.value)
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__

    broker = CredentialBroker(_resolver(), [REF])
    await broker.get("api_key")
    await broker.notify_rotated("api_key")
    assert caplog.records, "expected log records to be captured"
    for record in caplog.records:
        assert SECRET not in record.getMessage()
        assert SECRET not in json.dumps(record.__dict__, default=str)
    assert SECRET not in caplog.text


async def test_undeclared_credential_is_capability_unavailable() -> None:
    broker = CredentialBroker(_resolver(), [REF])
    with pytest.raises(CapabilityUnavailableError):
        await broker.get("nope")


async def test_rotation_hook_runs_and_next_call_uses_new_value() -> None:
    resolver = _resolver()
    broker = CredentialBroker(resolver, [REF])
    seen: list[str] = []
    async_seen: list[str] = []

    async def async_hook(name: str) -> None:
        async_seen.append(name)

    broker.on_rotation(seen.append)
    broker.on_rotation(async_hook)
    connector = _Demo(credentials=broker)

    assert await connector.call_provider() == SECRET
    resolver.rotate(REF, SECRET_2)  # source-signalled rotation, no restart
    await broker.drain_rotation_hooks()
    assert seen == ["api_key"]
    assert async_seen == ["api_key"]
    assert await connector.call_provider() == SECRET_2


async def test_manual_notify_rotated_invalidates_cache() -> None:
    values = {REF.vault_ref: SECRET}

    class Plain:
        async def resolve(self, ref: CredentialRef) -> SecretValue:
            return SecretValue(values[ref.vault_ref])

    broker = CredentialBroker(Plain(), [REF])
    connector = _Demo(credentials=broker)
    assert await connector.call_provider() == SECRET
    values[REF.vault_ref] = SECRET_2
    assert await connector.call_provider() == SECRET  # cached until signalled
    await broker.notify_rotated("api_key")
    assert await connector.call_provider() == SECRET_2

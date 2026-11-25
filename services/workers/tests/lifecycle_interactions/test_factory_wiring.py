"""PRP-103 item 7: ``_lifecycle_targets`` registers ``interaction_content`` only when configured.

Configuration is ``NS_INTERACTION_CONTENT_CONTAINER`` plus the blob access the archive uses (the
Azurite connection string under ``NS_ENV=local``). The index and content backends come as a pair:
a partial configuration registers nothing for interactions (logged, fail closed).
"""

from __future__ import annotations

import base64
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.clients.factories import ENV_BLOB_CONNECTION_STRING
from neurosphere_core.cloud import Settings
from neurosphere_core.interactions.lifecycle_delete import KIND_INTERACTION
from neurosphere_workers.runtime.factories import RuntimeConfig, _lifecycle_targets
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings

ENV_CONTAINER = "NS_INTERACTION_CONTENT_CONTAINER"
INDEX_CONTAINER = "interaction_index"


def _cfg() -> RuntimeConfig:
    return RuntimeConfig(
        Settings(env="local"),
        WorkerSettings(),
        StoreSettings(),
        AuthSettings(customer_id="synthco"),  # type: ignore[arg-type]
    )


def _connection_string() -> str:
    # A syntactically valid, throwaway connection string (no network is touched).
    key = base64.b64encode(b"not-a-real-key").decode()
    return (
        "DefaultEndpointsProtocol=http;AccountName=devaccount;"
        f"AccountKey={key};BlobEndpoint=http://127.0.0.1:10000/devaccount;"
    )


async def _kinds() -> list[tuple[str, str]]:
    async with ClientLifetime() as lifetime:
        registry = _lifecycle_targets(_cfg(), cast(Any, MagicMock()), lifetime)
        return sorted((t.target_kind, t.container) for t in registry.targets())


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (ENV_CONTAINER, ENV_BLOB_CONNECTION_STRING):
        monkeypatch.delenv(name, raising=False)


async def test_unset_settings_leave_the_registry_as_it_was() -> None:
    names = await _kinds()
    assert (KIND_INTERACTION, INDEX_CONTAINER) not in names
    assert [kind for kind, _ in names] == ["catalog", "ledger"]


async def test_set_settings_register_the_interaction_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_CONTAINER, "interaction-content")
    monkeypatch.setenv(ENV_BLOB_CONNECTION_STRING, _connection_string())
    names = await _kinds()
    assert (KIND_INTERACTION, INDEX_CONTAINER) in names
    # The archive shares the connection string, so it registers too; the others are untouched.
    assert {kind for kind, _ in names} >= {"catalog", "ledger", KIND_INTERACTION}


async def test_partial_configuration_registers_no_interaction_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The container is named (the index side is always reachable) but there is no blob access:
    # both backends are withheld together, so the target is absent and requests for it fail
    # closed as unknown_target. Never an index-only half store.
    monkeypatch.setenv(ENV_CONTAINER, "interaction-content")
    names = await _kinds()
    assert (KIND_INTERACTION, INDEX_CONTAINER) not in names
    assert [kind for kind, _ in names] == ["catalog", "ledger"]

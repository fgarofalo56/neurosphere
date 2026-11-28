"""PRP-104 item 8: the worker binds the index-only interaction finding reader when configured."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.clients.factories import ENV_COSMOS_KEY
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.governance.policy.readers import InteractionFindingReaderAdapter
from neurosphere_core.governance.policy.rules import InteractionFindingReader
from neurosphere_core.interactions import CosmosInteractionIndex
from neurosphere_workers.policy_eval import assembly
from neurosphere_workers.policy_eval.assembly import interaction_finding_reader
from neurosphere_workers.runtime.factories import RuntimeConfig
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings

TENANT = "11111111-2222-4333-8444-555555555555"
OBJECT_ID = "66666666-7777-4888-9999-aaaaaaaaaaaa"
CONTAINER_ENV = "NS_INTERACTION_CONTENT_CONTAINER"


def _config(env: str = "local", *, account: str | None = None) -> RuntimeConfig:
    store = StoreSettings(cosmos_account=account) if account else StoreSettings()  # type: ignore[call-arg]
    return RuntimeConfig(
        Settings(env=env, cloud=CloudName.COMMERCIAL),  # type: ignore[arg-type]
        WorkerSettings(tenant_id=TENANT, object_id=OBJECT_ID),  # type: ignore[call-arg]
        store,
        AuthSettings(customer_id="synthco"),  # type: ignore[arg-type]
    )


class _Spy:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.containers: list[tuple[str, str]] = []

    def create(self, settings: Any, *, lifetime: Any, account: Any = None) -> Any:
        self.calls.append({"account": account})
        spy = self

        class _Db:
            def __init__(self, name: str) -> None:
                self.name = name

            def get_container_client(self, container: str) -> str:
                spy.containers.append((self.name, container))
                return container

        class _Client:
            def get_database_client(self, name: str) -> _Db:
                return _Db(name)

        return _Client()


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> _Spy:
    created = _Spy()
    monkeypatch.setattr(assembly, "create_cosmos_client", created.create)
    monkeypatch.delenv(CONTAINER_ENV, raising=False)
    monkeypatch.delenv(ENV_COSMOS_KEY, raising=False)
    return created


async def test_configured_local_binds_the_index_only_adapter(
    spy: _Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CONTAINER_ENV, "interaction-content")
    monkeypatch.setenv(ENV_COSMOS_KEY, "emulator-placeholder")
    cfg = _config()
    async with ClientLifetime() as lifetime:
        reader = interaction_finding_reader(cfg, lifetime)
    assert isinstance(reader, InteractionFindingReaderAdapter)
    assert isinstance(reader, InteractionFindingReader)
    assert spy.containers == [(cfg.store.database, "interaction_index")]
    source = reader._source  # pyright: ignore[reportPrivateUsage]
    assert isinstance(source._index, CosmosInteractionIndex)  # type: ignore[attr-defined]
    # Index only: nothing that could read or decrypt content is reachable from the reader.
    assert not hasattr(source, "read_content")


async def test_configured_cloud_uses_the_cosmos_account(
    spy: _Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CONTAINER_ENV, "interaction-content")
    async with ClientLifetime() as lifetime:
        reader = interaction_finding_reader(_config("dev", account="acct-ns"), lifetime)
    assert isinstance(reader, InteractionFindingReaderAdapter)
    assert spy.calls == [{"account": "acct-ns"}]


@pytest.mark.parametrize(
    ("container", "key", "env", "account"),
    [
        (None, "emulator-placeholder", "local", None),  # no interaction storage configured
        ("  ", "emulator-placeholder", "local", None),  # blank is unset
        ("interaction-content", None, "local", None),  # no emulator key locally
        ("interaction-content", None, "dev", None),  # no Cosmos account outside local
    ],
)
async def test_not_configured_is_unbound(
    spy: _Spy,
    monkeypatch: pytest.MonkeyPatch,
    container: str | None,
    key: str | None,
    env: str,
    account: str | None,
) -> None:
    if container is not None:
        monkeypatch.setenv(CONTAINER_ENV, container)
    if key is not None:
        monkeypatch.setenv(ENV_COSMOS_KEY, key)
    async with ClientLifetime() as lifetime:
        reader = interaction_finding_reader(_config(env, account=account), lifetime)
    assert reader is None
    assert spy.calls == []

"""PRP-32 item 5: the hosted mode of ``sbx_seed_stack.py`` / ``sbx_grant_operator.py`` (no network).

Fake clients only: every factory must receive a credential, never a key, and nothing may be created.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "sandbox" / "sbx_seed_stack.py"
DEPLOYMENT = "demo-0001"
TENANT = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
WORKER_OID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
OPERATOR_OID = "55555555-5555-4555-8555-555555555555"
VAULT = "nsdemo-kv.vault.azure.net"
SECRET_URI = f"https://{VAULT}/secrets/pseudonym"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sbx_seed_stack_hosted_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


seed = _load()


def _registration(tmp_path: Path) -> Path:
    doc = {
        "schema": 1,
        "deployment_id": DEPLOYMENT,
        "cloud": "AzureCloud",
        "cosmos_host": "nsdemo-cosmos.documents.azure.com",
        "eventhubs_host": "nsdemo-ehns.servicebus.windows.net",
        "blob_host": "nsdemoarchive.blob.core.windows.net",
        "key_vault_host": VAULT,
        "database": "neurosphere",
        "event_hub": "telemetry",
        "archive_container": "ns-archive",
        "pseudonym_secret_uri": SECRET_URI,
        "workers_object_id": WORKER_OID,
        "customer_id": "synthco",
    }
    path = tmp_path / "registration.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _env(**extra: str) -> dict[str, str]:
    env = {
        "NS_ENV": "prod",
        "NS_CLOUD": "commercial",
        "NS_LIVE_APPROVED": "1",
        "NS_SANDBOX_HOSTED_DEPLOYMENT_ID": DEPLOYMENT,
        "NS_AUTH_TENANT_ID": TENANT,
    }
    env.update(extra)
    return env


# -- configuration ------------------------------------------------------------------------------


def test_hosted_config_comes_from_the_registration_and_carries_no_key(tmp_path: Path) -> None:
    config = seed.resolve_hosted_config("small", OPERATOR_OID, _env(), _registration(tmp_path))
    assert config.cosmos_endpoint == "https://nsdemo-cosmos.documents.azure.com/"
    assert config.hosted.eventhubs_fqdn == "nsdemo-ehns.servicebus.windows.net"
    assert (config.database, config.hub_name, config.archive_container, config.customer) == (
        "neurosphere",
        "telemetry",
        "ns-archive",
        "synthco",
    )
    assert config.worker_object_id == WORKER_OID
    assert (config.cosmos_key, config.eventhubs_connection, config.blob_connection) == ("", "", "")
    names = set(config.environ())
    assert not {n for n in names if "KEY" in n or "CONNECTION" in n}


def test_hosted_config_refuses_local_env_and_keys_and_approval(tmp_path: Path) -> None:
    registration = _registration(tmp_path)
    with pytest.raises(seed.ConfigError):
        seed.resolve_hosted_config("small", None, _env(NS_ENV="local"), registration)
    with pytest.raises(seed.GuardError):
        key_name = "NS_COSMOS_" + "KEY"
        seed.resolve_hosted_config("small", None, _env(**{key_name: "x" * 8}), registration)
    env = _env()
    del env["NS_LIVE_APPROVED"]
    with pytest.raises(seed.GuardError):
        seed.resolve_hosted_config("small", None, env, registration)


def test_local_path_still_refuses_a_hosted_env() -> None:
    with pytest.raises(seed.ConfigError):
        seed.resolve_config("small", None, {"NS_ENV": "prod"})


def test_main_hosted_refuses_without_approval_before_any_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a credential or client was built")

    for name in ("new_credential", "new_async_credential", "new_cosmos", "new_producer"):
        monkeypatch.setattr(seed, name, boom)
    env = _env()
    del env["NS_LIVE_APPROVED"]
    code = seed.main(["--hosted", str(_registration(tmp_path))], env=env)
    assert code == seed.EXIT_REFUSED


# -- clients ------------------------------------------------------------------------------------


class FakeCredential:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def __aenter__(self) -> FakeCredential:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self.close()


class FakeAsyncCredential(FakeCredential):
    async def close(self) -> None:  # type: ignore[override]
        self.closed = True


class _Recorder:
    """Any attribute is a callable returning another recorder; ``create*``/``delete*`` fail."""

    def __init__(self, calls: list[str], path: str = "") -> None:
        self._calls = calls
        self._path = path

    def __getattr__(self, name: str) -> Any:
        full = f"{self._path}.{name}".lstrip(".")
        self._calls.append(full)
        if name.startswith(("create", "delete", "replace")):
            raise AssertionError(f"hosted mode must not call {full}")
        return _Recorder(self._calls, full)

    def __call__(self, *_a: Any, **_k: Any) -> _Recorder:
        return self


class FakeCosmos(_Recorder):
    def __init__(self, endpoint: str, credential: Any, calls: list[str]) -> None:
        super().__init__(calls)
        self.endpoint = endpoint
        self.credential = credential

    async def __aenter__(self) -> FakeCosmos:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    def close(self) -> None:
        return None


def test_clients_receive_credentials_never_keys_and_nothing_is_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    seen: dict[str, Any] = {}
    sync_credential, async_credential = FakeCredential(), FakeAsyncCredential()

    def cosmos(endpoint: str, credential: Any) -> FakeCosmos:
        seen["cosmos"] = (endpoint, credential)
        return FakeCosmos(endpoint, credential, calls)

    def sync_cosmos(endpoint: str, credential: Any) -> FakeCosmos:
        seen["sync_cosmos"] = (endpoint, credential)
        return FakeCosmos(endpoint, credential, calls)

    monkeypatch.setattr(seed, "new_credential", lambda: sync_credential)
    monkeypatch.setattr(seed, "new_async_credential", lambda: async_credential)
    monkeypatch.setattr(seed, "new_cosmos", cosmos)
    monkeypatch.setattr(seed, "new_sync_cosmos", sync_cosmos)
    material = "k" * 48
    monkeypatch.setenv("NS_ENV", "prod")
    monkeypatch.setenv("NS_CLOUD", "commercial")
    monkeypatch.setenv("NS_AUTH_PSEUDONYM_KEY", material)
    monkeypatch.setenv("NS_AUTH_PSEUDONYM_KEY_REFERENCE", SECRET_URI)

    config = seed.resolve_hosted_config("small", OPERATOR_OID, _env(), _registration(tmp_path))

    async def run() -> Any:
        async with AsyncExitStack() as stack:
            return await seed.open_hosted_backends(config, stack)

    backends = asyncio.run(run())
    assert seen["cosmos"] == (config.cosmos_endpoint, async_credential)
    assert seen["sync_cosmos"] == (config.cosmos_endpoint, sync_credential)
    assert isinstance(backends.hub, seed.HostedHubSeam)
    assert not [c for c in calls if c.split(".")[-1].startswith(("create", "delete", "replace"))]
    assert sync_credential.closed and async_credential.closed


def test_hosted_hub_builds_its_producer_from_a_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str, Any]] = []
    credential = FakeCredential()
    monkeypatch.setattr(
        seed, "new_producer", lambda ns, hub, cred: seen.append((ns, hub, cred)) or object()
    )
    hub = seed.HostedHubSeam("ns.servicebus.windows.net", "telemetry", credential)
    hub._producer()  # pyright: ignore[reportPrivateUsage]
    assert seen == [("ns.servicebus.windows.net", "telemetry", credential)]


def test_archive_container_is_built_from_an_account_url_and_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str, Any]] = []
    credential = FakeCredential()

    class Blobs:
        def list_blobs(self) -> list[int]:
            return [1, 2, 3]

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        seed, "new_archive_container", lambda url, c, cred: seen.append((url, c, cred)) or Blobs()
    )
    config = seed.resolve_hosted_config("small", None, _env(), _registration(tmp_path))
    landing = seed.CosmosLanding(
        _Recorder([]),  # pyright: ignore[reportArgumentType]
        config,
        archive_client=lambda: seed.new_archive_container(
            config.hosted.blob_account_url, config.archive_container, credential
        ),
    )
    assert landing._blobs() == 3  # pyright: ignore[reportPrivateUsage]
    assert seen == [("https://nsdemoarchive.blob.core.windows.net/", "ns-archive", credential)]


# -- pseudonym key from Key Vault ---------------------------------------------------------------


def test_pseudonym_secret_is_read_over_rest_with_a_bearer_token_only() -> None:
    value = "v" * 48
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"value": value})

    class Credential:
        def get_token(self, scope: str) -> Any:
            assert scope == "https://vault.azure.net/.default"
            return type("Token", (), {"token": "tok"})()

    env = seed.grants.hosted_pseudonym_env(
        {"pseudonym_secret_uri": SECRET_URI},
        f"https://{VAULT}/",
        Credential(),
        httpx.MockTransport(handler),
    )
    assert env == {"NS_AUTH_PSEUDONYM_KEY": value, "NS_AUTH_PSEUDONYM_KEY_REFERENCE": SECRET_URI}
    assert seen[0].url.host == VAULT
    assert seen[0].url.path == "/secrets/pseudonym"
    assert seen[0].headers["authorization"] == "Bearer tok"


def test_pseudonym_secret_on_another_vault_is_refused() -> None:
    with pytest.raises(seed.GuardError):
        seed.grants.fetch_pseudonym_secret(
            "https://other.vault.azure.net/secrets/pseudonym",
            vault_endpoint=f"https://{VAULT}/",
            token="t",
            transport=httpx.MockTransport(lambda _r: httpx.Response(500)),
        )


def test_pseudonym_secret_http_failure_does_not_leak_the_body() -> None:
    body = "secret-" + "body"
    with pytest.raises(seed.GuardError) as caught:
        seed.grants.fetch_pseudonym_secret(
            SECRET_URI,
            vault_endpoint=f"https://{VAULT}/",
            token="t",
            transport=httpx.MockTransport(lambda _r: httpx.Response(403, text=body)),
        )
    assert body not in str(caught.value)

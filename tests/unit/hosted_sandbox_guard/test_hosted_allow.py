"""PRP-32 item 5: ``require_hosted_endpoint`` admits only the registered host (no network).

Credential-shaped strings are assembled at runtime so no secret-looking literal is committed.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "sandbox" / "sbx_guard.py"
DEPLOYMENT = "demo-0001"
HOSTS = {
    "cosmos": "nsdemo-cosmos.documents.azure.com",
    "eventhubs": "nsdemo-ehns.servicebus.windows.net",
    "blob": "nsdemoarchive.blob.core.windows.net",
    "keyvault": "nsdemo-kv.vault.azure.net",
}


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sbx_guard_hosted_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load()


def _registration(tmp_path: Path, **overrides: Any) -> Path:
    doc: dict[str, Any] = {
        "schema": 1,
        "deployment_id": DEPLOYMENT,
        "cloud": "AzureCloud",
        "cosmos_host": HOSTS["cosmos"],
        "eventhubs_host": HOSTS["eventhubs"],
        "blob_host": HOSTS["blob"],
        "key_vault_host": HOSTS["keyvault"],
        "database": "neurosphere",
        "event_hub": "telemetry",
        "archive_container": "ns-archive",
        "pseudonym_secret_uri": f"https://{HOSTS['keyvault']}/secrets/pseudonym",
        "workers_object_id": "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5",
        "customer_id": "synthco",
    }
    doc.update(overrides)
    path = tmp_path / "registration.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _env(**extra: str) -> dict[str, str]:
    env = {"NS_LIVE_APPROVED": "1", "NS_SANDBOX_HOSTED_DEPLOYMENT_ID": DEPLOYMENT}
    env.update(extra)
    return env


def _call(
    url: str,
    registration: Path,
    env: dict[str, str] | None = None,
    kind: str = "cosmos",
) -> str:
    return guard.require_hosted_endpoint(
        url, kind=kind, env=_env() if env is None else env, registration_path=registration
    )


@pytest.mark.parametrize("kind", sorted(HOSTS))
def test_exact_registered_host_is_allowed(tmp_path: Path, kind: str) -> None:
    registration = _registration(tmp_path)
    assert _call(f"https://{HOSTS[kind]}", registration, kind=kind) == f"https://{HOSTS[kind]}/"


def test_default_port_and_trailing_slash_are_normalized(tmp_path: Path) -> None:
    registration = _registration(tmp_path)
    url = f"https://{HOSTS['cosmos'].upper()}:443/"
    assert _call(url, registration) == f"https://{HOSTS['cosmos']}/"


def test_another_commercial_cosmos_host_is_refused(tmp_path: Path) -> None:
    registration = _registration(tmp_path)
    with pytest.raises(guard.GuardError):
        _call("https://someone-else.documents.azure.com", registration)


def test_government_suffix_is_refused(tmp_path: Path) -> None:
    gov = "nsdemo-cosmos.documents.azure.us"
    registration = _registration(tmp_path, cosmos_host=gov)
    with pytest.raises(guard.GuardError):
        _call(f"https://{gov}", registration)


def test_registered_host_outside_the_commercial_suffix_is_refused(tmp_path: Path) -> None:
    registration = _registration(tmp_path, cosmos_host="evil.documents.azure.com.example.org")
    with pytest.raises(guard.GuardError):
        _call("https://evil.documents.azure.com.example.org", registration)


def test_loopback_through_the_hosted_function_is_refused(tmp_path: Path) -> None:
    registration = _registration(tmp_path)
    for url in ("https://127.0.0.1", "https://localhost", "http://127.0.0.1:8081"):
        with pytest.raises(guard.GuardError):
            _call(url, registration)


def test_missing_registration_is_refused(tmp_path: Path) -> None:
    with pytest.raises(guard.GuardError):
        _call(f"https://{HOSTS['cosmos']}", tmp_path / "absent.json")


def test_garbled_registration_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "registration.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(guard.GuardError):
        _call(f"https://{HOSTS['cosmos']}", path)


def test_deployment_id_mismatch_is_refused(tmp_path: Path) -> None:
    registration = _registration(tmp_path)
    env = _env()
    env["NS_SANDBOX_HOSTED_DEPLOYMENT_ID"] = "another-deployment"
    with pytest.raises(guard.GuardError):
        _call(f"https://{HOSTS['cosmos']}", registration, env)


def test_missing_deployment_id_is_refused(tmp_path: Path) -> None:
    registration = _registration(tmp_path)
    with pytest.raises(guard.GuardError):
        _call(f"https://{HOSTS['cosmos']}", registration, {"NS_LIVE_APPROVED": "1"})


def test_non_commercial_registration_cloud_is_refused(tmp_path: Path) -> None:
    registration = _registration(tmp_path, cloud="AzureUSGovernment")
    with pytest.raises(guard.GuardError):
        _call(f"https://{HOSTS['cosmos']}", registration)


def test_cosmos_key_in_env_is_refused(tmp_path: Path) -> None:
    registration = _registration(tmp_path)
    env = _env(**{"NS_SANDBOX_" + "COSMOS_KEY": "dummy" + "-value"})
    with pytest.raises(guard.GuardError) as caught:
        _call(f"https://{HOSTS['cosmos']}", registration, env)
    assert "dummy" not in str(caught.value)


def test_eventhubs_connection_string_in_env_is_refused(tmp_path: Path) -> None:
    registration = _registration(tmp_path)
    conn = ";".join(["Endpoint=sb://x", "SharedAccessKeyName=n", "SharedAccessKey=" + "abc"])
    env = _env(NS_EVENTHUBS_CONNECTION_STRING=conn)
    with pytest.raises(guard.GuardError) as caught:
        _call(f"https://{HOSTS['eventhubs']}", registration, env, kind="eventhubs")
    assert "SharedAccess" not in str(caught.value)


def test_blob_connection_string_in_env_is_refused(tmp_path: Path) -> None:
    registration = _registration(tmp_path)
    env = _env(NS_BLOB_CONNECTION_STRING="AccountName=x;AccountKey=" + "abc")
    with pytest.raises(guard.GuardError):
        _call(f"https://{HOSTS['blob']}", registration, env, kind="blob")


def test_approval_unset_is_refused(tmp_path: Path) -> None:
    registration = _registration(tmp_path)
    env = {"NS_SANDBOX_HOSTED_DEPLOYMENT_ID": DEPLOYMENT}
    with pytest.raises(guard.GuardError):
        _call(f"https://{HOSTS['cosmos']}", registration, env)
    env["NS_LIVE_APPROVED"] = "0"
    with pytest.raises(guard.GuardError):
        _call(f"https://{HOSTS['cosmos']}", registration, env)


def test_url_with_userinfo_is_refused_without_echoing_it(tmp_path: Path) -> None:
    registration = _registration(tmp_path)
    user, credential = "operator", "pw" + "-" + "hunter2"
    with pytest.raises(guard.GuardError) as caught:
        _call(f"https://{user}:{credential}@{HOSTS['cosmos']}", registration)
    assert user not in str(caught.value)
    assert credential not in str(caught.value)


def test_url_with_query_or_fragment_is_refused(tmp_path: Path) -> None:
    registration = _registration(tmp_path)
    for suffix in ("?key=1", "#frag"):
        with pytest.raises(guard.GuardError):
            _call(f"https://{HOSTS['cosmos']}/{suffix}", registration)


def test_http_scheme_is_refused(tmp_path: Path) -> None:
    registration = _registration(tmp_path)
    with pytest.raises(guard.GuardError):
        _call(f"http://{HOSTS['cosmos']}", registration)


def test_non_default_port_is_refused(tmp_path: Path) -> None:
    registration = _registration(tmp_path)
    with pytest.raises(guard.GuardError):
        _call(f"https://{HOSTS['cosmos']}:8081", registration)


def test_path_is_refused(tmp_path: Path) -> None:
    registration = _registration(tmp_path)
    with pytest.raises(guard.GuardError):
        _call(f"https://{HOSTS['cosmos']}/dbs", registration)


def test_unknown_kind_is_refused(tmp_path: Path) -> None:
    registration = _registration(tmp_path)
    with pytest.raises(guard.GuardError):
        _call(f"https://{HOSTS['cosmos']}", registration, kind="search")


def test_local_path_is_unchanged() -> None:
    assert guard.require_local_endpoint("http://127.0.0.1:8081") == "http://127.0.0.1:8081"
    with pytest.raises(guard.GuardError):
        guard.require_local_endpoint(f"https://{HOSTS['cosmos']}")

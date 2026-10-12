# pyright: reportMissingImports=false
"""Prefix and endpoint guards. The unit tests need no stack; the last one does."""

from __future__ import annotations

import pytest
from sbx_guard import (
    ENV_COSMOS_ENDPOINT,
    ENV_EVENTHUBS_CONN,
    GuardError,
    cosmos_settings,
    eventhubs_connection_string,
    require_local_endpoint,
    require_sandbox_name,
)

from .conftest import run_cli


@pytest.mark.parametrize(
    "name", ["neurosphere", "prod-sandbox-x", "Sandbox-x", "sandbox", "", "sandbox-"]
)
def test_non_sandbox_names_are_refused(name: str) -> None:
    with pytest.raises(GuardError):
        require_sandbox_name(name, "database")


def test_sandbox_names_are_accepted() -> None:
    assert require_sandbox_name("sandbox-neurosphere") == "sandbox-neurosphere"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.documents.azure.com:443/",
        "https://acct.documents.azure.us/",
        "http://10.0.0.5:8081",
        "http://cosmos:8081",
        "http://localhost.evil.com:8081",
        "http://127.0.0.1.evil.com",
        "",
    ],
)
def test_non_local_cosmos_endpoints_are_refused(url: str) -> None:
    with pytest.raises(GuardError):
        require_local_endpoint(url)
    with pytest.raises(GuardError):
        cosmos_settings({ENV_COSMOS_ENDPOINT: url})


@pytest.mark.parametrize(
    "url", ["http://localhost:8081", "http://127.0.0.1:8081", "http://[::1]:8081"]
)
def test_loopback_endpoints_are_accepted(url: str) -> None:
    assert require_local_endpoint(url) == url


def test_remote_event_hubs_connection_string_is_refused_without_leaking_it() -> None:
    secret_marker = "do-not-leak-" + "this"
    conn = f"Endpoint=sb://ns.servicebus.windows.net/;SharedAccessKeyName=k;SharedAccessKey={secret_marker}"
    with pytest.raises(GuardError) as excinfo:
        eventhubs_connection_string({ENV_EVENTHUBS_CONN: conn})
    assert secret_marker not in str(excinfo.value)


def test_default_event_hubs_connection_string_is_local() -> None:
    conn = eventhubs_connection_string({})
    assert conn.startswith("Endpoint=sb://localhost;")


def test_cli_refuses_remote_endpoint_offline() -> None:
    """The refusal happens before any network call, so this needs no stack."""
    import os
    import subprocess
    import sys

    from .conftest import CLI, REPO_ROOT

    env = dict(os.environ, **{ENV_COSMOS_ENDPOINT: "https://acct.documents.azure.com:443/"})
    result = subprocess.run(
        [sys.executable, str(CLI), "reset"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 3
    assert "refused" in result.stderr


@pytest.mark.integration
def test_cli_never_touches_non_sandbox_databases(stack: None) -> None:
    """Create a decoy non-sandbox database; reset must leave it alone."""
    from azure.cosmos import CosmosClient
    from sbx_guard import cosmos_settings as settings

    endpoint, key = settings()
    client = CosmosClient(endpoint, credential=key)
    client.create_database_if_not_exists(id="decoy-not-sandbox")
    try:
        result = run_cli("reset")
        assert result.returncode == 0, result.stderr
        names = [d["id"] for d in client.list_databases()]
        assert "decoy-not-sandbox" in names
        assert not [n for n in names if n.startswith("sandbox-")]
    finally:
        client.delete_database("decoy-not-sandbox")

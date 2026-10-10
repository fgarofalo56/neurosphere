"""Fixtures for the PRP-01 contract suite.

The suite must run with ``NO_NETWORK=1`` and no credentials. The autouse fixture below makes
that a property of the suite rather than a promise: any attempt to open a network
connection from the test process raises :class:`NetworkBlockedError`. Subprocesses started
by the drift and TypeScript tests are not covered by this patch; they get ``UV_OFFLINE=1``
and only run local tools.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest
from contract_support import SCHEMA_ROOT, NetworkBlockedError, load_json


def _blocked(*_args: Any, **_kwargs: Any) -> Any:
    raise NetworkBlockedError("network access is disabled in tests/contracts (NO_NETWORK)")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
    yield


@pytest.fixture(scope="session")
def confirmation_hash_definition() -> dict[str, Any]:
    return load_json(SCHEMA_ROOT / "actions" / "v1" / "confirmation-hash.json")


@pytest.fixture(scope="session")
def transitions() -> dict[str, Any]:
    return load_json(SCHEMA_ROOT / "actions" / "v1" / "transitions.json")


@pytest.fixture(scope="session")
def error_codes() -> dict[str, Any]:
    return load_json(SCHEMA_ROOT / "errors" / "v1" / "error-codes.json")


@pytest.fixture(scope="session")
def id_corpus() -> dict[str, Any]:
    return load_json(SCHEMA_ROOT / "catalog" / "v1" / "id-corpus.json")


@pytest.fixture(scope="session")
def validator_context(confirmation_hash_definition: dict[str, Any]) -> dict[str, Any]:
    return {"confirmation_hash": confirmation_hash_definition}

"""Fixtures for the worker-roles integration test. Needs the compose emulators ALREADY running.

This suite never starts or stops docker compose; when an emulator does not answer it skips.
``.env`` is never read. Every name is unique per run.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from .support import (
    COSMOS_ENDPOINT,
    EVENTHUBS_CONNECTION,
    WORKER_OBJECT_ID,
    WORKER_TENANT_ID,
    azurite_connection_string,
    dummy_cosmos_key,
    emulators_up,
)


@pytest.fixture
def run_id() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
def worker_env(monkeypatch: pytest.MonkeyPatch, run_id: str) -> Iterator[dict[str, str]]:
    if not emulators_up():
        pytest.skip("compose emulators (cosmos, azurite, eventhubs) are not running")
    env = {
        "NS_ENV": "local",
        "NS_COSMOS_ENDPOINT": COSMOS_ENDPOINT,
        "NS_COSMOS_KEY": dummy_cosmos_key(),
        "NS_EVENTHUBS_CONNECTION_STRING": EVENTHUBS_CONNECTION,
        "NS_BLOB_CONNECTION_STRING": azurite_connection_string(),
        "NS_STORE_DATABASE": f"it_wr_{run_id}",
        "NS_INGESTION_CHECKPOINT_CONTAINER": f"ns-ckpt-{run_id}",
        "NS_INGESTION_MAX_WAIT_SECONDS": "1",
        "NS_ARCHIVE_CONTAINER": f"ns-arch-{run_id}",
        "NS_QUARANTINE_CONTAINER": f"ns-quar-{run_id}",
        "NS_AUTH_CUSTOMER_ID": "synthco",
        "NS_WORKER_TENANT_ID": WORKER_TENANT_ID,
        "NS_WORKER_OBJECT_ID": WORKER_OBJECT_ID,
        "NS_WORKER_POLL_SECONDS": "1",
        "NS_WORKER_HEALTH_PORT": "0",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("NS_CLOUD", raising=False)
    yield env

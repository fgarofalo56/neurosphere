"""PRP-29 item 10: the stack seed against the compose emulators, workers running in-process.

Needs the emulators ALREADY running (Cosmos 8081, Event Hubs 5672, Azurite 10000); this suite never
starts, stops or restarts compose (``compose_stack`` only probes; export
``NS_PROBE_COSMOS_URL=http://127.0.0.1:8081/``). The ``ingestion``, ``projections`` and
``aggregates`` roles run in this process while the seed CLI runs in a thread, exactly as the
compose ``workers`` service runs beside the compose ``seed`` job. A throwaway database and
throwaway blob containers are used and removed afterwards.

Run: ``NS_PROBE_COSMOS_URL=http://127.0.0.1:8081/ MSYS_NO_PATHCONV=1 uv run pytest -q -m integration
tests/integration/real_stack/test_seed.py``. Emulator limits (G12): no auth and no RU accounting.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import importlib.util
import json
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest
from azure.storage.blob.aio import ContainerClient
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.stores import ensure_local_containers
from neurosphere_workers.runtime.factories import RuntimeConfig, role_factories
from neurosphere_workers.runtime.supervisor import RoleSupervisor

pytestmark = pytest.mark.integration

SCRIPT: Final = Path(__file__).resolve().parents[3] / "scripts" / "sandbox" / "sbx_seed_stack.py"
ENDPOINT: Final = "http://127.0.0.1:8081"
TENANT: Final = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
WORKER_OID: Final = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
OPERATOR_OID: Final = "7d2e3f40-5b6c-4d7e-8f90-a1b2c3d4e5f6"
ROLES: Final = ("ingestion", "projections", "aggregates")
AZURITE_SHORTHAND: Final = "UseDevelopmentStorage=true;"


def _load_seed() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sbx_seed_stack_integration", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _azurite_connection() -> str:
    """The development account's full connection string, assembled from the SDK at runtime."""
    probe = ContainerClient.from_connection_string(AZURITE_SHORTHAND, "probe")
    credential = probe.credential
    name, secret = credential.account_name, credential.account_key  # type: ignore[union-attr]
    endpoint = probe.primary_endpoint.rsplit("/", 1)[0]
    return (
        "DefaultEndpointsProtocol=http;"
        + f"AccountName={name};"
        + f"AccountKey={secret};BlobEndpoint={endpoint};"
    )


def _eventhubs_connection() -> str:
    parts = [
        "Endpoint=sb://127.0.0.1",
        "SharedAccessKeyName=RootManageSharedAccessKey",
        "SharedAccessKey=" + "SAS_KEY" + "_VALUE",
        "UseDevelopmentEmulator=true",
    ]
    return ";".join(parts) + ";"


@pytest.fixture
def seed_env(
    monkeypatch: pytest.MonkeyPatch, emulator_env: None, compose_stack: None
) -> Iterator[dict[str, str]]:
    run = uuid.uuid4().hex[:8]
    env = {
        "NS_ENV": "local",
        "NS_COSMOS_ENDPOINT": ENDPOINT,
        "NS_COSMOS_KEY": base64.b64encode(b"emulator-ignores-this").decode(),
        "NS_EVENTHUBS_CONNECTION_STRING": _eventhubs_connection(),
        "NS_BLOB_CONNECTION_STRING": _azurite_connection(),
        "NS_STORE_DATABASE": f"it_seed_{run}",
        "NS_INGESTION_CHECKPOINT_CONTAINER": f"ns-ckpt-{run}",
        "NS_INGESTION_MAX_WAIT_SECONDS": "1",
        "NS_ARCHIVE_CONTAINER": f"ns-arch-{run}",
        "NS_QUARANTINE_CONTAINER": f"ns-quar-{run}",
        "NS_AUTH_CUSTOMER_ID": "synthco",
        "NS_AUTH_TENANT_ID": TENANT,
        "NS_WORKER_TENANT_ID": TENANT,
        "NS_WORKER_OBJECT_ID": WORKER_OID,
        "NS_WORKER_POLL_SECONDS": "1",
        "NS_WORKER_HEALTH_PORT": "0",
        "NS_SEED_POLL_SECONDS": "3",
        "NS_SEED_WAIT_SECONDS": "420",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    for name in ("NS_CLOUD", "NS_AUTH_PSEUDONYM_KEY", "NS_AUTH_PSEUDONYM_KEY_REFERENCE"):
        monkeypatch.delenv(name, raising=False)
    yield env


def _summary(captured: str) -> dict[str, Any]:
    lines = [line for line in captured.splitlines() if line.strip()]
    assert len(lines) == 1, f"stdout must be exactly the JSON summary, got {lines!r}"
    return json.loads(lines[0])


async def test_seed_fills_every_category_and_a_rerun_is_idempotent(
    seed_env: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    seed = _load_seed()
    cfg = RuntimeConfig.from_env()
    database = cfg.store.database
    supervisor = RoleSupervisor(role_factories(cfg, ROLES))
    runner: asyncio.Task[None] | None = None
    first: dict[str, Any] = {}
    second: dict[str, Any] = {}
    codes: list[int] = []
    states: dict[str, str] = {}

    async with ClientLifetime() as lifetime:
        cosmos = create_cosmos_client(cfg.settings, lifetime=lifetime)
        try:
            await ensure_local_containers(cosmos, Settings(env="local"), database=database)
            runner = asyncio.create_task(supervisor.run())

            codes.append(
                await asyncio.to_thread(
                    seed.main, ["--profile", "small", "--operator-object-id", OPERATOR_OID]
                )
            )
            first_out = capsys.readouterr()
            states = {r["name"]: f"{r['state']}:{r['reason']}" for r in supervisor.snapshot()}
            if codes[-1] == 0:
                first = _summary(first_out.out)
                codes.append(
                    await asyncio.to_thread(
                        seed.main, ["--profile", "small", "--operator-object-id", OPERATOR_OID]
                    )
                )
                second_out = capsys.readouterr()
                if codes[-1] == 0:
                    second = _summary(second_out.out)
            else:
                pytest.fail(f"seed exited {codes[-1]}: {first_out.err[-2000:]} roles={states}")
        finally:
            supervisor.request_shutdown()
            if runner is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(runner, timeout=120)
            with contextlib.suppress(Exception):
                await cosmos.delete_database(database)
            for name in (
                seed_env["NS_ARCHIVE_CONTAINER"],
                seed_env["NS_QUARANTINE_CONTAINER"],
                seed_env["NS_INGESTION_CHECKPOINT_CONTAINER"],
            ):
                with contextlib.suppress(Exception):
                    async with ContainerClient.from_connection_string(
                        seed_env["NS_BLOB_CONNECTION_STRING"], name
                    ) as blob:
                        await blob.delete_container()

    print("FIRST RUN SUMMARY:", json.dumps(first, sort_keys=True))
    print("SECOND RUN SUMMARY:", json.dumps(second, sort_keys=True))
    assert codes == [0, 0], codes
    assert set(first["seeded"]) == set(seed.CATEGORIES)
    empty = sorted(name for name, count in first["seeded"].items() if count <= 0)
    assert not empty, f"categories with nothing seeded: {empty}; first={first}; roles={states}"
    assert first["skipped_existing"] == 0, first

    assert set(second["seeded"]) == set(seed.CATEGORIES)
    created = {name: count for name, count in second["seeded"].items() if count}
    assert not created, f"the re-run created documents: {created}"
    assert second["skipped_existing"] > 0

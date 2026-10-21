"""PRP-18 item 7: the viewport and realtime delta path on the Cosmos vNext emulator.

Marked ``integration`` (needs the default compose emulators: ``docker compose up -d --wait``);
CI never runs it. The hot aggregates live in a Cosmos container unique to this run. The async
Cosmos client is bound to the event loop that created it, so one blocking portal hosts the
client, the HTTP requests and the websocket sessions (the TestClient is handed that portal).
Convention matches ``tests/integration/dashboards``: skip only when docker is not installed, FAIL
when the emulator is unreachable (never a silent green).

Not proved here (recorded OPEN): a live Cosmos account (G12 emulator parity), RU cost and index
policy of the aggregate queries, and the production bootstrap that sets ``app.state`` (none exists
yet; ``compose`` in ``support.py`` stands in for it).
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from contextlib import suppress
from typing import Any

import anyio.from_thread
import pytest
from azure.cosmos import PartitionKey
from fastapi.testclient import TestClient
from neurosphere_core.aggregates.cosmos import PARTITION_KEY_PATH, CosmosAggregateStore
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings

from integration.ingestion.support import emulator_env

from .scenarios import check_delta_and_scope, check_revocation_closes_socket, check_viewport
from .support import FINANCE, OPERATIONS, Wiring, compose, seed_aggregates

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _emulator_env() -> Iterator[None]:
    patch = pytest.MonkeyPatch()
    for name, value in emulator_env().items():
        patch.setenv(name, value)
    patch.delenv("NS_CLOUD", raising=False)
    try:
        yield
    finally:
        patch.undo()


@pytest.fixture
def cosmos_wiring() -> Iterator[tuple[Wiring, TestClient]]:
    """The composed app over a run-unique Cosmos aggregate container, on one shared event loop."""
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    database = f"it_map_{uuid.uuid4().hex[:8]}"
    lifetime = ClientLifetime()
    holder: dict[str, Any] = {}

    async def open_store() -> CosmosAggregateStore:
        cosmos = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        holder["cosmos"] = cosmos
        try:
            db = await cosmos.create_database_if_not_exists(database)
            container = await db.create_container_if_not_exists(
                id="aggregates", partition_key=PartitionKey(path=PARTITION_KEY_PATH)
            )
            store = CosmosAggregateStore(container)
            await seed_aggregates(store, FINANCE, OPERATIONS)
        except Exception as exc:
            await lifetime.aclose()
            holder["failed"] = f"{type(exc).__name__}: {exc}"
            raise
        return store

    async def close() -> None:
        with suppress(Exception):
            await holder["cosmos"].delete_database(database)
        await lifetime.aclose()

    with anyio.from_thread.start_blocking_portal() as portal:
        try:
            store = portal.call(open_store)
        except Exception:
            pytest.fail(
                f"cosmos emulator unreachable or unusable ({holder.get('failed')}); "
                "run: docker compose up -d --wait"
            )
        try:
            wired = compose(store)
            client = wired.client()
            client.portal = (
                portal  # requests and sockets run on the loop the Cosmos client lives on
            )
            yield wired, client
        finally:
            portal.call(close)


def test_viewport_reads_the_cosmos_aggregates(cosmos_wiring: tuple[Wiring, TestClient]) -> None:
    wired, client = cosmos_wiring
    check_viewport(wired, client)


def test_realtime_delta_comes_from_cosmos_and_stays_scoped(
    cosmos_wiring: tuple[Wiring, TestClient],
) -> None:
    wired, client = cosmos_wiring
    check_delta_and_scope(wired, client)


def test_revocation_fan_out_closes_the_session_on_the_cosmos_backed_app(
    cosmos_wiring: tuple[Wiring, TestClient],
) -> None:
    wired, client = cosmos_wiring
    check_revocation_closes_socket(wired, client)

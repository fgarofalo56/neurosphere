"""PRP-19 item 7: the copilot and reports wiring over the Cosmos vNext emulator.

Marked ``integration`` (needs the default compose emulators: ``docker compose up -d --wait``);
CI never runs it. The conversation and report containers are created by the same
``create_conversation_container`` / ``create_report_container`` helpers a deployment's bootstrap
uses, in a database unique to this run. The async Cosmos client is bound to the event loop that
created it, so one blocking portal hosts the client and the HTTP requests (the TestClient is
handed that portal). Convention matches ``tests/integration/map``: skip only when docker is not
installed, FAIL when the emulator is unreachable (never a silent green).

Not proved here (recorded OPEN): a live Cosmos account (G12 emulator parity: no RBAC, no RU
accounting, TTL eviction timing) and the production bootstrap that sets ``app.state`` (none exists
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
from neurosphere_api.copilot import CosmosConversationStore, create_conversation_container
from neurosphere_api.reports import CosmosReportStore, create_report_container
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings

from integration.ingestion.support import emulator_env

from .scenarios import (
    check_action_suggestion_is_a_draft,
    check_conversation_stream_and_ownership,
    check_report_runs_per_viewer_scope,
)
from .support import Wiring, compose

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
def cosmos_wiring() -> Iterator[Wiring]:
    """The composed app over run-unique Cosmos containers, on one shared event loop."""
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    database = f"it_copilot_{uuid.uuid4().hex[:8]}"
    lifetime = ClientLifetime()
    holder: dict[str, Any] = {}

    async def open_stores() -> tuple[CosmosConversationStore, CosmosReportStore]:
        cosmos = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        holder["cosmos"] = cosmos
        try:
            db = await cosmos.create_database_if_not_exists(database)
            conversations = await create_conversation_container(db, "conversations")
            reports = await create_report_container(db, "reports")
        except Exception as exc:
            await lifetime.aclose()
            holder["failed"] = f"{type(exc).__name__}: {exc}"
            raise
        return CosmosConversationStore(conversations), CosmosReportStore(reports)

    async def close() -> None:
        with suppress(Exception):
            await holder["cosmos"].delete_database(database)
        await lifetime.aclose()

    with anyio.from_thread.start_blocking_portal() as portal:
        try:
            conversation_store, report_store = portal.call(open_stores)
        except Exception:
            pytest.fail(
                f"cosmos emulator unreachable or unusable ({holder.get('failed')}); "
                "run: docker compose up -d --wait"
            )
        try:
            wired = compose(conversation_store=conversation_store, report_store=report_store)
            wired.client.portal = portal  # requests run on the loop the Cosmos client lives on
            yield wired
        finally:
            portal.call(close)


def test_stream_order_and_conversation_isolation_on_the_cosmos_stores(
    cosmos_wiring: Wiring,
) -> None:
    check_conversation_stream_and_ownership(cosmos_wiring)


def test_a_shared_report_runs_under_each_viewers_own_scope_on_cosmos(
    cosmos_wiring: Wiring,
) -> None:
    check_report_runs_per_viewer_scope(cosmos_wiring)


def test_an_action_suggestion_is_a_draft_on_the_cosmos_backed_app(cosmos_wiring: Wiring) -> None:
    check_action_suggestion_is_a_draft(cosmos_wiring)

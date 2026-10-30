"""Harness for the grant publish API tests (PRP-34 item 5). Offline.

Reuses the mode-switch environment (real authz, action plane, gateway store, the REAL APIM write
connector over ``InMemoryApim``) and adds the grant translator to the connector, the in-memory
catalog repository holding a Grant, and the connector apply-record store as the API lookup.

This directory has no ``__init__.py``: import by module name.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import httpx
from gateway_mode_harness import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    GATEWAY_ID,
    ModeEnv,
    make_mode_env,
    manage_fields,
    registration,
)
from neurosphere_api.catalog import get_clock, get_repository
from neurosphere_connector.write import WriteRequest
from neurosphere_connector_apim_gateway import ApimGatewayConnector
from neurosphere_connector_apim_gateway.grants import GrantPublicationTranslator
from neurosphere_contracts.actions.v1.action_state import ActionState
from neurosphere_core.actions import ExecutionRecord
from neurosphere_core.catalog import CatalogEntity
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.catalog.repo.documents import parse_entity

CATALOG: Final = "/api/v1/catalog"
ACTIONS: Final = "/api/v1/actions"
_EXAMPLE = (
    Path(__file__).resolve().parents[4]
    / "packages/contracts/schemas/catalog/v1/examples/valid"
    / "grant.user-model-deployment-token-limits.json"
)
GRANT_ID: Final = "commercial:contoso:neurosphere:grant:finance/analyst-gpt-4o"
API_ID: Final = "llm"
KEY_A: Final = "idem-grant-publish-000001"
KEY_B: Final = "idem-grant-publish-000002"


def grant_doc(**patch: Any) -> dict[str, Any]:
    doc = json.loads(_EXAMPLE.read_text(encoding="utf-8"))
    doc.update(domain_id=FINANCE, **patch)
    return doc


@dataclass
class GrantEnv:
    env: ModeEnv
    repo: InMemoryCatalogRepository
    connector: ApimGatewayConnector
    clock_now: datetime

    def call(self, method: str, who: str | None, path: str, **kw: Any) -> httpx.Response:
        return self.env.call(method, who, path, **kw)

    def publish(self, who: str | None, **body: Any) -> httpx.Response:
        payload = {
            "gateway_id": GATEWAY_ID,
            "api_id": API_ID,
            "access": "subscription",
            "idempotency_key": KEY_A,
            **body,
        }
        return self.call("POST", who, f"{CATALOG}/grants/{GRANT_ID}/publish", json=payload)

    def unpublish(self, who: str | None, **body: Any) -> httpx.Response:
        payload = {"idempotency_key": KEY_B, **body}
        return self.call("POST", who, f"{CATALOG}/grants/{GRANT_ID}/unpublish", json=payload)

    def record(self, who: str | None, intent_id: str) -> httpx.Response:
        return self.call(
            "POST",
            who,
            f"{CATALOG}/grants/{GRANT_ID}/publication",
            json={"intent_id": intent_id},
        )

    def execute(self, intent_id: str) -> None:
        """Run the intent through the REAL connector (what the worker does after approval) and
        mark it succeeded with the verified execution record."""

        async def run() -> None:
            stored = await self.env.intents.get("contoso", FINANCE, intent_id)
            assert stored is not None
            request = WriteRequest(
                target=stored.intent.target,
                target_version=stored.intent.target_version,
                proposed_diff=stored.intent.proposed_diff,
            )
            applied = await self.connector.apply(request)
            verified = await self.connector.verify(request)
            assert all(c.matched for c in verified.checks)
            done = stored.model_copy(
                update={
                    "intent": stored.intent.model_copy(update={"state": ActionState("succeeded")}),
                    "execution": ExecutionRecord(
                        phase="done",
                        verify_matched=True,
                        apply_result=applied.model_dump(mode="json"),
                    ),
                }
            )
            assert stored.etag is not None
            await self.env.intents.replace(done, if_match=stored.etag)

        asyncio.run(run())

    def stored(self) -> CatalogEntity:
        async def run() -> CatalogEntity | None:
            scope = await self._scope()
            return await self.repo.get_entity(scope, GRANT_ID)

        found = asyncio.run(run())
        assert found is not None
        return found

    async def _scope(self) -> Any:
        from gateway_mode_harness import OPERATOR  # pyright: ignore[reportMissingImports]

        claims = await self.env.h.validator.authenticate(self.env.h.auth(OPERATOR)["Authorization"])
        return (await self.env.h.deriver.derive(claims)).scope


def make_grant_env(
    *, grant: dict[str, Any] | None = None, manage: bool = True, wire_records: bool = True
) -> GrantEnv:
    env = make_mode_env(seed=registration(**manage_fields()) if manage else None)
    connector = env.registry.get("apim-gateway")
    assert isinstance(connector, ApimGatewayConnector)
    connector.register_translator(GrantPublicationTranslator())
    env.apim.seed("apis/llm", {"displayName": "LLM", "path": "llm"})
    repo = InMemoryCatalogRepository()
    now = datetime(2027, 1, 15, 12, 0, tzinfo=UTC)
    env.h.app.dependency_overrides[get_repository] = lambda: repo
    env.h.app.dependency_overrides[get_clock] = lambda: lambda: now
    if wire_records:
        env.h.app.state.apim_apply_records = env.records
    out = GrantEnv(env, repo, connector, now)

    async def seed() -> None:
        scope = await out._scope()
        await repo.create_entity(scope, parse_entity(grant or grant_doc()))

    asyncio.run(seed())
    return out

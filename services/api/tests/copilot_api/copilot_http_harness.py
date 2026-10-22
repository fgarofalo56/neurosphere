"""The HTTP stack for the copilot API tests: real authz, real action plane, the copilot router.

Built on the PRP-17 action-plane harness (``services/api/tests/actions_api``), which already wires
dev-issuer tokens, an in-memory policy store, the real ``ActionService`` and a fake write
connector that explodes on ``apply``. The copilot router and its collaborators are added to that
app. No network, no emulator.

People (all customer ``contoso``): ALICE steward on FINANCE, BOB steward on FINANCE, CAROL viewer
on FINANCE, DAVE admin on FINANCE, ERIN viewer on FINANCE + steward on OPERATIONS.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from action_plane_harness import Api, make_api  # pyright: ignore[reportMissingImports]
from copilot_api_harness import (  # pyright: ignore[reportMissingImports]
    ScriptedAdapter,
    World,
    make_world,
)
from neurosphere_api.copilot import (
    ChartPlanValidator,
    CopilotSettings,
    InMemoryConversationStore,
    build_router,
    configure_copilot,
)

COPILOT_PREFIX = "/api/v1/copilot"


@dataclass
class Http:
    api: Api
    world: World
    store: Any
    model: ScriptedAdapter

    @property
    def client(self) -> Any:
        return self.api.h.client

    def headers(self, who: str) -> dict[str, str]:
        return self.api.h.auth(who)

    def create(self, who: str) -> Any:
        return self.client.post(f"{COPILOT_PREFIX}/conversations", headers=self.headers(who))

    def send(
        self, who: str, conversation_id: str, text: str = "What changed in finance?", **context: Any
    ) -> Any:
        return self.client.post(
            f"{COPILOT_PREFIX}/conversations/{conversation_id}/messages",
            headers=self.headers(who),
            json={"text": text, "context": context},
        )

    def ask(
        self, who: str, text: str = "What changed in finance?", **context: Any
    ) -> list[tuple[str, dict[str, Any]]]:
        """Create a conversation, send one message, return the parsed SSE events."""
        created = self.create(who)
        assert created.status_code == 201, created.text
        response = self.send(who, created.json()["id"], text, **context)
        assert response.status_code == 200, response.text
        return parse_sse(response.text)


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        lines = block.split("\n")
        assert len(lines) == 2, "each event is exactly one event: line and one data: line"
        assert lines[0].startswith("event: ") and lines[1].startswith("data: "), block
        name = lines[0].removeprefix("event: ")
        events.append((name, json.loads(lines[1].removeprefix("data: "))))
    return events


def make_http(
    model: ScriptedAdapter,
    *,
    world: World | None = None,
    store: Any = None,
    settings: CopilotSettings | None = None,
    chart_validator: ChartPlanValidator | None = None,
    configured: bool = True,
    action_plane: bool = True,
    extra_policies: Sequence[Any] = (),
) -> Http:
    api = make_api(wire=action_plane)
    for policy in extra_policies:
        api.h.repo.put_principal(policy)
    resolved: World = make_world() if world is None else world
    store = store if store is not None else InMemoryConversationStore()
    app = api.h.app
    app.include_router(build_router(), prefix=COPILOT_PREFIX)
    if configured:
        configure_copilot(
            app,
            model_adapter=model,
            conversation_store=store,
            evidence_reader=resolved.evidence,
            settings=settings,
            chart_validator=chart_validator,
            clock=lambda: datetime.fromtimestamp(api.h.clock(), UTC),
        )
        app.state.catalog_repository = resolved.catalog
        app.state.aggregate_reader = resolved.metrics
        app.state.recommendation_store = resolved.recs
    return Http(api=api, world=resolved, store=store, model=model)

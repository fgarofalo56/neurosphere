"""Buttons, chat and MCP share ONE composed ``ActionService`` (PRP-29 item 8, CLAUDE.md).

Asserted by identity: each channel's OWN resolution (the REST route dependency, the copilot's
optional-plane dependency, the MCP tool ports) returns the very object the planes builder
PUBLISHED as ``ACTION_SERVICE``. Then end to end: a REST draft, a chat draft and an MCP draft all
land in the one composed intent store, each ``drafted`` and never confirmed or executed.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from neurosphere_api.actions import get_action_plane
from neurosphere_api.copilot.dependencies import get_optional_action_plane
from neurosphere_api.mcp.server.tools import StatePorts
from neurosphere_api.runtime.builders import ACTION_SERVICE, BuildContext
from neurosphere_core.actions import ActionService
from starlette.requests import Request

from .planes_helpers import (
    ALICE,
    CUSTOMER,
    FINANCE,
    MCP_ENV,
    ch,
    compose_planes,
    configure_auth_env,
    cs,
    mcp_token,
)

INTENTS = f"/api/v1/actions/domains/{FINANCE}/intents"
CONVERSATIONS = "/api/v1/copilot/conversations"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    for name, value in MCP_ENV.items():
        monkeypatch.setenv(name, value)


def _drafting_model() -> Any:
    return ch.ScriptedAdapter(
        ch.call("propose_action", cs.draft_args()),
        ch.say("I drafted the swap for you to confirm [cite:r1]."),
    )


def _request(app: Any) -> Request:
    return Request({"type": "http", "app": app, "headers": []})


def test_every_channel_resolves_the_one_published_executor() -> None:
    published: list[object] = []

    def probe(ctx: BuildContext) -> None:
        published.append(ctx.shared(ACTION_SERVICE))

    planes = compose_planes(model_adapter=_drafting_model(), mcp_validator=True, probe=probe)
    for name in ("action_plane", "copilot", "mcp_server"):
        assert planes.registry.get(name).state == "ok", planes.registry.get(name)
    [executor] = published
    assert isinstance(executor, ActionService)
    app = planes.app

    rest = get_action_plane(_request(app)).actions  # REST / button route dependency
    chat_plane = get_optional_action_plane(_request(app))  # copilot route dependency
    assert chat_plane is not None
    mcp = StatePorts(app).action_plane().actions  # MCP tool ports
    assert rest is executor
    assert chat_plane.actions is executor
    assert mcp is executor
    assert app.state.action_service is executor


def _sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        lines = [line for line in block.split("\n") if line]
        if len(lines) == 2 and lines[0].startswith("event: ") and lines[1].startswith("data: "):
            events.append((lines[0].removeprefix("event: "), json.loads(lines[1][6:])))
    return events


async def test_rest_chat_and_mcp_drafts_land_in_the_same_store_and_never_execute() -> None:
    planes = compose_planes(model_adapter=_drafting_model(), mcp_validator=True)
    app = planes.app
    headers = planes.auth(ALICE)
    rest_body = {
        **cs.draft_args(new_version="2026-07-01"),
        "evidence": [],
        "idempotency_key": "idem-2026-10-25-shared-rest-01",
        "channel": "rest",
    }
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url=f"https://{cs.MCP_HOST}") as client,
    ):
        rest = await client.post(INTENTS, json=rest_body, headers=headers)
        assert rest.status_code == 201, rest.text
        created = await client.post(CONVERSATIONS, headers=headers)
        assert created.status_code == 201, created.text
        chat = await client.post(
            f"{CONVERSATIONS}/{created.json()['id']}/messages",
            headers=headers,
            json={"text": "Swap the chat deployment to the newer model", "context": {}},
        )
        assert chat.status_code == 200, chat.text
        drafted = await cs.call_tool(client, mcp_token(planes), "draft_action", cs.draft_args())
    suggestions = [data for name, data in _sse(chat.text) if name == "action_suggestion"]
    assert len(suggestions) == 1, chat.text
    [mcp] = cs.records(drafted)
    ids = {
        "rest": rest.json()["intent"]["intent_id"],
        "chat": suggestions[0]["intent_id"],
        "mcp": mcp["data"]["intent_id"],
    }
    assert len(set(ids.values())) == 3
    store: Any = planes.backends["intent_store"]
    for channel, intent_id in sorted(ids.items()):
        stored = await store.get(CUSTOMER, FINANCE, intent_id)
        assert stored is not None, channel
        assert stored.state == "drafted", channel
        assert stored.intent.channel == channel
        assert stored.intent.confirmation_hash is None

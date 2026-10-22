"""Prompts are redacted before they leave the boundary (PRP-19 item 3, clarification 13)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import httpx
import pytest
from azure.core.credentials import AccessToken
from neurosphere_core.copilot.models import (
    AdapterConfig,
    ApprovedEndpointAdapter,
    ConversationTurn,
    FoundryAgentAdapter,
    ModelAdapter,
    ModelRequest,
    ToolCallRequest,
    ToolSpec,
    redact_request,
    redact_text,
)
from neurosphere_core.copilot.models.recorded import (
    load_http_recording,
    replay_transport,
)
from pydantic import ValidationError


class _Credential:
    async def get_token(self, *_scopes: str, **_kwargs: Any) -> AccessToken:
        return AccessToken(f"tok-{uuid.uuid4().hex}", int(time.time()) + 3600)

    async def close(self) -> None:
        return None


def _sensitive() -> dict[str, str]:
    """PII- and secret-shaped synthetic values, generated per run (never hardcoded)."""
    return {
        "email": f"{uuid.uuid4().hex[:10]}@{uuid.uuid4().hex[:6]}.example",
        "guid": str(uuid.uuid4()),
        "jwt": f"eyJ{uuid.uuid4().hex}.eyJ{uuid.uuid4().hex}.{uuid.uuid4().hex}",
        "ssn": "-".join(["123", "45", "6789"]),
        "card": " ".join(["4111"] * 4),
        "password": uuid.uuid4().hex,
        "bearer": uuid.uuid4().hex,
    }


def _request(v: dict[str, str]) -> ModelRequest:
    return ModelRequest(
        system=f"Operator contact {v['email']} for escalations.",
        turns=(
            ConversationTurn(
                role="user",
                content=(
                    f"My id is {v['guid']}, SSN {v['ssn']}, card {v['card']}, "
                    f"token {v['jwt']}, password={v['password']}"
                ),
            ),
            ConversationTurn(
                role="assistant",
                tool_calls=(
                    ToolCallRequest(
                        call_id="call_1",
                        tool_name="catalog_search",
                        arguments={"query": v["email"], "nested": {"ids": [v["guid"]]}},
                    ),
                ),
            ),
            ConversationTurn(
                role="tool",
                tool_call_id="call_1",
                content=json.dumps({"owner": v["email"], "auth": f"Bearer {v['bearer']}"}),
            ),
        ),
        tools=(
            ToolSpec(
                name="catalog_search",
                description=f"Search; maintained by {v['email']}",
                parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            ),
        ),
    )


@pytest.mark.parametrize("kind", ["approved_endpoint", "foundry_agent"])
async def test_sensitive_values_never_reach_the_outbound_body(kind: str) -> None:
    values = _sensitive()
    captured: list[httpx.Request] = []
    transport = replay_transport(load_http_recording("text_answer", kind), captured)
    adapter: ModelAdapter
    if kind == "approved_endpoint":
        adapter = ApprovedEndpointAdapter(
            AdapterConfig(
                kind="approved_endpoint",
                endpoint="https://ns-test.openai.azure.us",
                deployment="gpt-4o",
            ),
            cloud="government",
            credential=_Credential(),  # pyright: ignore[reportArgumentType]
            transport=transport,
        )
    else:
        adapter = FoundryAgentAdapter(
            AdapterConfig(
                kind="foundry_agent",
                endpoint="https://ns-test.services.ai.azure.us/api/projects/ns",
                deployment="ns-copilot",
                oauth_scope="https://ai.azure.us/.default",
            ),
            cloud="government",
            credential=_Credential(),  # pyright: ignore[reportArgumentType]
            transport=transport,
        )
    _ = [event async for event in adapter.stream(_request(values))]
    body = captured[0].content.decode("utf-8")
    leaked = {name for name, value in values.items() if value in body}
    assert not leaked, leaked
    for marker in ("[email]", "[id]", "[ssn]", "[card]", "[token]", "[credential]"):
        assert marker in body, marker


def test_redact_text_is_value_independent_and_idempotent() -> None:
    v = _sensitive()
    once = redact_text(f"{v['email']} {v['guid']} {v['ssn']}")
    assert once == "[email] [id] [ssn]"
    assert redact_text(once) == once


def test_ordinary_text_is_untouched() -> None:
    text = "Which model costs less for summarization in domain finance?"
    assert redact_text(text) == text


def test_redact_request_leaves_structure_and_ids_of_calls() -> None:
    v = _sensitive()
    redacted = redact_request(_request(v))
    assert [t.role for t in redacted.turns] == ["user", "assistant", "tool"]
    assert redacted.turns[1].tool_calls[0].call_id == "call_1"
    assert redacted.turns[2].tool_call_id == "call_1"
    assert v["email"] not in redacted.model_dump_json()


@pytest.mark.parametrize("field", ["domain_id", "customer_id", "tenant_id", "scope"])
def test_tool_manifest_with_a_scope_field_is_refused(field: str) -> None:
    with pytest.raises(ValidationError):
        ToolSpec(
            name="t",
            description="d",
            parameters={
                "type": "object",
                "properties": {"outer": {"type": "object", "properties": {field: {}}}},
            },
        )

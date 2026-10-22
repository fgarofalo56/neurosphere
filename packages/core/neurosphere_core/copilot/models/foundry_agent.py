"""Optional Foundry Agent Service adapter (REST, Responses shape, api-version ``v1``).

No SDK: ``azure-ai-projects`` is deliberately not a dependency (licence gate), so this speaks
the documented REST shape through httpx with a ``https://ai.azure.com/.default`` token.
The Government feature set of Agent Service is partial; availability is decided by the
capability matrix in :mod:`~neurosphere_core.copilot.models.gating`, and this adapter still
refuses an endpoint outside the deployment's cloud.

Wire shape (verify against the live service before the optional live gate):
``POST {project_endpoint}/openai/responses?api-version=v1`` with an ``agent_reference`` and
function tools; the stream carries ``response.output_text.delta``,
``response.output_item.done`` (``function_call`` items) and ``response.completed``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Final

import httpx
from azure.core.credentials_async import AsyncTokenCredential

from neurosphere_core.copilot.models.endpoints import (
    AdapterConfig,
    Cloud,
    require_endpoint,
    token_scope,
)
from neurosphere_core.copilot.models.normalize import (
    invalid_response,
    normalize_tool_call,
    stop_reason_for,
)
from neurosphere_core.copilot.models.protocol import AdapterDescriptor
from neurosphere_core.copilot.models.redaction import redact_request
from neurosphere_core.copilot.models.rest import (
    REQUEST_TIMEOUT,
    bearer_headers,
    error_for_status,
    sse_data,
)
from neurosphere_core.copilot.models.types import (
    ActionSuggestion,
    Completed,
    ModelEvent,
    ModelRequest,
    TextDelta,
    ToolCallRequested,
    Usage,
)
from neurosphere_core.errors import CapabilityUnavailableError

API_VERSION: Final = "v1"


def build_body(request: ModelRequest, agent_name: str) -> dict[str, Any]:
    """Responses-API body from an already-redacted request."""
    items: list[dict[str, Any]] = []
    for turn in request.turns:
        if turn.role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": turn.tool_call_id,
                    "output": turn.content,
                }
            )
            continue
        if turn.content:
            items.append({"role": turn.role, "content": turn.content})
        items.extend(
            {
                "type": "function_call",
                "call_id": c.call_id,
                "name": c.tool_name,
                "arguments": json.dumps(c.arguments),
            }
            for c in turn.tool_calls
        )
    body: dict[str, Any] = {
        "agent": {"type": "agent_reference", "name": agent_name},
        "instructions": request.system,
        "input": items,
        "stream": True,
        "max_output_tokens": request.max_output_tokens,
    }
    if request.tools:
        body["tools"] = [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in request.tools
        ]
    return body


class FoundryAgentAdapter:
    """Streams a Foundry Agent Service response through the shared action contract."""

    def __init__(
        self,
        config: AdapterConfig,
        *,
        cloud: Cloud,
        credential: AsyncTokenCredential,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if config.kind != "foundry_agent":
            raise CapabilityUnavailableError("wrong_adapter_kind", "config is not foundry_agent")
        if not config.deployment:
            raise CapabilityUnavailableError("agent_missing", "no agent name configured")
        self._endpoint = require_endpoint(cloud, config.endpoint)
        self._agent = config.deployment
        self._api_version = config.api_version or API_VERSION
        self._scope = token_scope(config, cloud)
        self._credential = credential
        self._transport = transport
        self._descriptor = AdapterDescriptor(kind="foundry_agent", name=config.deployment)

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    @property
    def url(self) -> str:
        return f"{self._endpoint}/openai/responses?api-version={self._api_version}"

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        body = build_body(redact_request(request), self._agent)
        headers = await bearer_headers(self._credential, self._scope, request.correlation_id)
        calls: list[ToolCallRequested | ActionSuggestion] = []
        status: str | None = None
        usage = Usage()
        async with (
            httpx.AsyncClient(transport=self._transport, timeout=REQUEST_TIMEOUT) as client,
            client.stream("POST", self.url, json=body, headers=headers) as response,
        ):
            if response.status_code >= 400:
                await response.aread()
                raise error_for_status(response)
            async for data in sse_data(response):
                try:
                    event: dict[str, Any] = json.loads(data)
                except ValueError as exc:
                    raise invalid_response("model stream event is not JSON") from exc
                kind = event.get("type")
                if kind == "response.output_text.delta":
                    text = event.get("delta")
                    if text:
                        yield TextDelta(text=text)
                elif kind == "response.output_item.done":
                    item: dict[str, Any] = event.get("item") or {}
                    if item.get("type") == "function_call":
                        call_id = str(item.get("call_id") or "")
                        name = str(item.get("name") or "")
                        if not call_id or not name:
                            raise invalid_response("tool call is missing its id or name")
                        arguments = str(item.get("arguments") or "")
                        calls.append(normalize_tool_call(call_id, name, arguments))
                elif kind == "response.completed":
                    done: dict[str, Any] = event.get("response") or {}
                    status = done.get("status") or "completed"
                    reported: dict[str, Any] = done.get("usage") or {}
                    usage = Usage(
                        input_tokens=reported.get("input_tokens"),
                        output_tokens=reported.get("output_tokens"),
                    )
                elif kind in ("response.failed", "error"):
                    raise invalid_response("agent run failed")
                elif kind == "response.incomplete":
                    status = "max_output_tokens"
        for call in calls:
            yield call
        yield Completed(
            stop_reason=stop_reason_for(status, saw_tool_calls=bool(calls)), usage=usage
        )

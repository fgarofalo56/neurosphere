"""Approved-endpoint adapter: Azure OpenAI-style streaming chat completions with tool calling.

The endpoint comes from deployment config and must belong to the deployment's cloud
(see :mod:`~neurosphere_core.copilot.models.endpoints`). The transport is injectable so tests
replay recorded HTTP fixtures and never open a socket.
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
    Completed,
    ModelEvent,
    ModelRequest,
    TextDelta,
    Usage,
)
from neurosphere_core.errors import CapabilityUnavailableError

DEFAULT_API_VERSION: Final = "2024-10-21"


def build_body(request: ModelRequest) -> dict[str, Any]:
    """Chat-completions request body from an already-redacted request."""
    messages: list[dict[str, Any]] = [{"role": "system", "content": request.system}]
    for turn in request.turns:
        if turn.role == "tool":
            messages.append(
                {"role": "tool", "tool_call_id": turn.tool_call_id, "content": turn.content}
            )
        elif turn.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": turn.content or None,
                    "tool_calls": [
                        {
                            "id": c.call_id,
                            "type": "function",
                            "function": {"name": c.tool_name, "arguments": json.dumps(c.arguments)},
                        }
                        for c in turn.tool_calls
                    ],
                }
            )
        else:
            messages.append({"role": turn.role, "content": turn.content})
    body: dict[str, Any] = {
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_completion_tokens": request.max_output_tokens,
    }
    if request.tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
    return body


class ApprovedEndpointAdapter:
    """Streams chat completions from a deployment-config endpoint."""

    def __init__(
        self,
        config: AdapterConfig,
        *,
        cloud: Cloud,
        credential: AsyncTokenCredential,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if config.kind != "approved_endpoint":
            raise CapabilityUnavailableError(
                "wrong_adapter_kind", "config is not approved_endpoint"
            )
        if not config.deployment:
            raise CapabilityUnavailableError("deployment_missing", "no deployment name configured")
        self._endpoint = require_endpoint(cloud, config.endpoint)
        self._deployment = config.deployment
        self._api_version = config.api_version or DEFAULT_API_VERSION
        self._scope = token_scope(config, cloud)
        self._credential = credential
        self._transport = transport
        self._descriptor = AdapterDescriptor(kind="approved_endpoint", name=config.deployment)

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    @property
    def url(self) -> str:
        return (
            f"{self._endpoint}/openai/deployments/{self._deployment}/chat/completions"
            f"?api-version={self._api_version}"
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        body = build_body(redact_request(request))
        headers = await bearer_headers(self._credential, self._scope, request.correlation_id)
        calls: dict[int, dict[str, str]] = {}
        finish: str | None = None
        usage = Usage()
        async with (
            httpx.AsyncClient(transport=self._transport, timeout=REQUEST_TIMEOUT) as client,
            client.stream("POST", self.url, json=body, headers=headers) as response,
        ):
            if response.status_code >= 400:
                await response.aread()
                raise error_for_status(response)
            async for data in sse_data(response):
                if data == "[DONE]":
                    break
                try:
                    chunk: dict[str, Any] = json.loads(data)
                except ValueError as exc:
                    raise invalid_response("model stream chunk is not JSON") from exc
                reported = chunk.get("usage")
                if isinstance(reported, dict):
                    usage = Usage(
                        input_tokens=reported.get("prompt_tokens"),  # pyright: ignore[reportUnknownMemberType]
                        output_tokens=reported.get("completion_tokens"),  # pyright: ignore[reportUnknownMemberType]
                    )
                for choice in chunk.get("choices") or []:
                    delta: dict[str, Any] = choice.get("delta") or {}
                    text = delta.get("content")
                    if text:
                        yield TextDelta(text=text)
                    for part in delta.get("tool_calls") or []:
                        slot = calls.setdefault(
                            int(part.get("index", 0)), {"id": "", "name": "", "args": ""}
                        )
                        fn: dict[str, Any] = part.get("function") or {}
                        slot["id"] = part.get("id") or slot["id"]
                        slot["name"] = fn.get("name") or slot["name"]
                        slot["args"] += fn.get("arguments") or ""
                    finish = choice.get("finish_reason") or finish
        for index in sorted(calls):
            slot = calls[index]
            if not slot["id"] or not slot["name"]:
                raise invalid_response("tool call is missing its id or name")
            yield normalize_tool_call(slot["id"], slot["name"], slot["args"])
        yield Completed(
            stop_reason=stop_reason_for(finish, saw_tool_calls=bool(calls)), usage=usage
        )

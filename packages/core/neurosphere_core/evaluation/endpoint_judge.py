"""Endpoint judge (PRP-16 round 2, item 7): a ``Judge`` over an approved chat-completions endpoint.

Non-streaming POST to an Azure OpenAI-style deployment; the rubric verdict is requested as a JSON
object and parsed strictly. The endpoint must belong to the deployment cloud (a Government judge
never calls a Commercial host and vice versa); that check runs at construction, before any
request. The payload is redacted before transmission. Identity is a caller-supplied
``AsyncTokenCredential`` (managed identity), never a key. The transport is injectable so tests
replay recorded HTTP fixtures and never open a socket.

A verdict that is not valid JSON, or does not match the schema, is an abstention with a recorded
reason, never a fabricated score. HTTP errors go through the error taxonomy (``error_for_status``)
and are never scored.

Usage reaches the budget ledger through ``JudgeResponse.input_tokens`` / ``output_tokens``, taken
from the response ``usage`` block (zero when the endpoint reports none).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Final

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from neurosphere_core.copilot.models.endpoints import (
    AdapterConfig,
    Cloud,
    require_endpoint,
    token_scope,
)
from neurosphere_core.copilot.models.redaction import redact_value
from neurosphere_core.copilot.models.rest import REQUEST_TIMEOUT, bearer_headers, error_for_status
from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.evaluation.judge import JudgeRequest, JudgeResponse

__all__ = ["EndpointJudge", "Verdict"]

_log = logging.getLogger(__name__)

DEFAULT_API_VERSION: Final = "2024-10-21"
MAX_COMPLETION_TOKENS: Final = 400

SYSTEM_PROMPT: Final = (
    "You are an evaluation judge. Score the submitted agent output against the named rubric "
    "dimension. Reply with a single JSON object and nothing else: "
    '{"abstain": false, "score": <number between 0 and 1>, "reason": "<short reason>"} '
    'or, if you cannot judge, {"abstain": true, "score": null, "reason": "<why>"}.'
)


class Verdict(BaseModel):
    """The strict schema of the judge's JSON reply."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    abstain: bool
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _consistent(self) -> Verdict:
        if self.abstain != (self.score is None):
            raise ValueError("score must be null exactly when the judge abstains")
        return self


class EndpointJudge:
    """Scores one request per non-streaming chat completion; implements ``Judge``."""

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
        self.abstention_reasons: list[str] = []

    @property
    def url(self) -> str:
        return (
            f"{self._endpoint}/openai/deployments/{self._deployment}/chat/completions"
            f"?api-version={self._api_version}"
        )

    def _body(self, request: JudgeRequest) -> dict[str, Any]:
        content = {
            "rubric_id": request.rubric_id,
            "rubric_version": request.rubric_version,
            "dimension": request.dimension,
            "item_id": request.item_id,
            "payload": redact_value(request.payload),
        }
        return {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(content, sort_keys=True)},
            ],
            "stream": False,
            "temperature": 0,
            "max_completion_tokens": MAX_COMPLETION_TOKENS,
            "response_format": {"type": "json_object"},
        }

    def _abstain(self, reason: str, input_tokens: int, output_tokens: int) -> JudgeResponse:
        self.abstention_reasons.append(reason)
        _log.info("endpoint judge abstained: %s", reason)
        return JudgeResponse(
            value=None, abstained=True, input_tokens=input_tokens, output_tokens=output_tokens
        )

    async def score(self, request: JudgeRequest) -> JudgeResponse:
        headers = await bearer_headers(self._credential, self._scope, request.item_id)
        headers["Accept"] = "application/json"
        async with httpx.AsyncClient(
            transport=self._transport, timeout=REQUEST_TIMEOUT, follow_redirects=False
        ) as client:
            response = await client.post(self.url, json=self._body(request), headers=headers)
        if response.status_code >= 400:
            raise error_for_status(response)
        try:
            doc: Any = response.json()
        except ValueError:
            return self._abstain("response body is not JSON", 0, 0)
        input_tokens, output_tokens = _usage(doc)
        content = _message_content(doc)
        if content is None:
            return self._abstain("response has no message content", input_tokens, output_tokens)
        try:
            verdict = Verdict.model_validate_json(content)
        except ValidationError:
            return self._abstain(
                "verdict is not valid JSON for the rubric schema", input_tokens, output_tokens
            )
        if verdict.abstain:
            self.abstention_reasons.append(verdict.reason or "judge abstained")
        return JudgeResponse(
            value=verdict.score,
            abstained=verdict.abstain,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def _usage(doc: Any) -> tuple[int, int]:
    usage = doc.get("usage") if isinstance(doc, dict) else None
    if not isinstance(usage, dict):
        return 0, 0
    return _count(usage.get("prompt_tokens")), _count(usage.get("completion_tokens"))  # pyright: ignore[reportUnknownMemberType]


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _message_content(doc: Any) -> str | None:
    if not isinstance(doc, dict):
        return None
    choices = doc.get("choices")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if not isinstance(choices, list) or not choices:
        return None
    first: Any = choices[0]  # pyright: ignore[reportUnknownVariableType]
    message: Any = first.get("message") if isinstance(first, dict) else None  # pyright: ignore[reportUnknownMemberType]
    content: Any = message.get("content") if isinstance(message, dict) else None  # pyright: ignore[reportUnknownMemberType]
    return content if isinstance(content, str) else None

"""EndpointJudge over recorded HTTP fixtures (httpx.MockTransport): no socket, no paid call."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx
import pytest
from azure.core.credentials import AccessToken
from neurosphere_core.copilot.models.endpoints import AdapterConfig, Cloud
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    ForbiddenError,
    RateLimitedError,
    UnauthorizedError,
)
from neurosphere_core.evaluation.endpoint_judge import EndpointJudge
from neurosphere_core.evaluation.judge import Judge, JudgeRequest

FIXTURES = Path(__file__).parent / "fixtures" / "endpoint_judge"
_SSN = "-".join(("123", "45", "6789"))
COMMERCIAL = "https://acct-eval.openai.azure.com"
GOVERNMENT = "https://acct-eval.openai.azure.us"
REPO_ROOT = Path(__file__).resolve().parents[4]


class _Credential:
    def __init__(self) -> None:
        self.token = f"tok-{uuid.uuid4().hex}"

    async def get_token(self, *_scopes: str, **_kwargs: Any) -> AccessToken:
        return AccessToken(self.token, int(time.time()) + 3600)

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> _Credential:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        return None


def _recorded(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _request(**over: object) -> JudgeRequest:
    base: dict[str, object] = {
        "judge_config_id": "jc-1",
        "judge_config_version": "1",
        "rubric_id": "rb-1",
        "rubric_version": "1",
        "dimension": "groundedness",
        "item_id": "it-1",
        "classification": "public",
        "payload": {"answer": "see ssn " + _SSN, "ctx": ["x"]},
    }
    return JudgeRequest.model_validate({**base, **over})


def _judge(
    handler: Any,
    *,
    cloud: Cloud = "commercial",
    endpoint: str = COMMERCIAL,
    credential: _Credential | None = None,
) -> tuple[EndpointJudge, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    config = AdapterConfig(kind="approved_endpoint", endpoint=endpoint, deployment="judge-1")
    judge = EndpointJudge(
        config,
        cloud=cloud,
        credential=credential or _Credential(),
        transport=httpx.MockTransport(wrapped),
    )
    return judge, seen


def _replay(name: str) -> Any:
    return lambda _request: httpx.Response(200, json=_recorded(name))


async def test_pass_verdict_and_protocol() -> None:
    judge, seen = _judge(_replay("pass"))
    assert isinstance(judge, Judge)
    response = await judge.score(_request())
    assert (response.value, response.abstained) == (1.0, False)
    assert len(seen) == 1
    body = json.loads(seen[0].content)
    assert body["stream"] is False
    assert body["response_format"] == {"type": "json_object"}
    assert seen[0].url.path == "/openai/deployments/judge-1/chat/completions"


async def test_fail_verdict() -> None:
    judge, _ = _judge(_replay("fail"))
    response = await judge.score(_request())
    assert (response.value, response.abstained) == (0.0, False)


async def test_abstention_with_reason() -> None:
    judge, _ = _judge(_replay("abstain"))
    response = await judge.score(_request())
    assert response.value is None
    assert response.abstained is True
    assert judge.abstention_reasons == ["insufficient context"]


@pytest.mark.parametrize("name", ["malformed", "schema_invalid"])
async def test_unparseable_verdict_is_abstention_never_a_score(name: str) -> None:
    judge, _ = _judge(_replay(name))
    response = await judge.score(_request())
    assert response.value is None
    assert response.abstained is True
    assert len(judge.abstention_reasons) == 1
    assert judge.abstention_reasons[0]
    assert response.input_tokens > 0


async def test_non_json_body_is_abstention() -> None:
    judge, _ = _judge(lambda _r: httpx.Response(200, content=b"<html>oops</html>"))
    response = await judge.score(_request())
    assert response.abstained is True
    assert judge.abstention_reasons == ["response body is not JSON"]


async def test_usage_is_parsed() -> None:
    judge, _ = _judge(_replay("pass"))
    response = await judge.score(_request())
    assert (response.input_tokens, response.output_tokens) == (123, 17)


async def test_429_maps_to_rate_limited() -> None:
    judge, _ = _judge(lambda _r: httpx.Response(429, headers={"retry-after": "7"}))
    with pytest.raises(RateLimitedError):
        await judge.score(_request())


@pytest.mark.parametrize("status", [500, 503])
async def test_5xx_maps_to_transient(status: int) -> None:
    judge, _ = _judge(lambda _r: httpx.Response(status))
    with pytest.raises(DependencyTransientError):
        await judge.score(_request())


@pytest.mark.parametrize(("status", "error"), [(401, UnauthorizedError), (403, ForbiddenError)])
async def test_auth_failures_map_through_taxonomy(status: int, error: type[Exception]) -> None:
    judge, _ = _judge(lambda _r: httpx.Response(status))
    with pytest.raises(error):
        await judge.score(_request())


@pytest.mark.parametrize(
    ("cloud", "endpoint"), [("government", COMMERCIAL), ("commercial", GOVERNMENT)]
)
def test_wrong_cloud_endpoint_refused_before_any_request(cloud: Cloud, endpoint: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_recorded("pass"))

    config = AdapterConfig(kind="approved_endpoint", endpoint=endpoint, deployment="judge-1")
    with pytest.raises(CapabilityUnavailableError):
        EndpointJudge(
            config,
            cloud=cloud,
            credential=_Credential(),
            transport=httpx.MockTransport(handler),
        )
    assert seen == []


async def test_payload_is_redacted_and_bearer_sent() -> None:
    credential = _Credential()
    judge, seen = _judge(_replay("pass"), credential=credential)
    await judge.score(_request())
    sent = seen[0].content.decode("utf-8")
    assert _SSN not in sent
    assert "[ssn]" in sent
    assert seen[0].headers["Authorization"] == "Bearer " + credential.token


def _run_gate(env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "NS_LIVE_APPROVED"}
    env.update(env_extra)
    return subprocess.run(  # noqa: S603
        [sys.executable, str(REPO_ROOT / "scripts" / "gates" / "g16_judge_live.py")],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
    )


def test_g16_script_refuses_without_approval() -> None:
    result = _run_gate({})
    assert result.returncode == 2
    assert "REFUSED" in result.stderr

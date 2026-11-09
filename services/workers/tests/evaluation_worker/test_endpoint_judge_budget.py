"""A billed endpoint call with unreadable usage is charged the full reservation, never zero."""

from __future__ import annotations

import time
from typing import Any

import httpx
from azure.core.credentials import AccessToken
from neurosphere_core.copilot.models.endpoints import AdapterConfig
from neurosphere_core.evaluation.endpoint_judge import EndpointJudge
from neurosphere_workers.evaluation.source import InMemoryRecordSource

from .support import ledger, llm_config, make_service, online_config, record

GOVERNMENT = "https://acct-eval.openai.azure.us"


class _Credential:
    async def get_token(self, *_scopes: str, **_kwargs: Any) -> AccessToken:
        return AccessToken("tok", int(time.time()) + 3600)

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> _Credential:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _no_usage(_request: httpx.Request) -> httpx.Response:
    body = {
        "choices": [
            {"message": {"role": "assistant", "content": '{"abstain": false, "score": 1.0}'}}
        ]
    }
    return httpx.Response(200, json=body)


async def test_missing_usage_settles_full_reservation_and_is_judge_error() -> None:
    config = AdapterConfig(kind="approved_endpoint", endpoint=GOVERNMENT, deployment="judge-1")
    judge = EndpointJudge(
        config,
        cloud="government",
        credential=_Credential(),  # type: ignore[arg-type]
        transport=httpx.MockTransport(_no_usage),
    )
    led = ledger()
    cfg = llm_config()
    service = make_service(judge, [cfg], budget=led)
    report = await service.run_online(
        InMemoryRecordSource([record(1, classification="public")]), online_config(cfg)
    )

    assert report.evaluated_total == 0
    assert report.skip_counts.get("judge_error", 0) >= 1
    assert all(o.status == "skipped" for o in report.outcomes)
    tokens, cost = led.run_consumed
    assert tokens > 0
    assert cost > 0
    assert tokens >= len(report.outcomes) * cfg.max_output_tokens
    assert led.open_reservations == 0

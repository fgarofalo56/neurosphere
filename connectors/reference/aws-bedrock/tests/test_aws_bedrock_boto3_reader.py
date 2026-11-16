"""PRP-62 item 4: the boto3 reader against botocore stubs and fake clients (no network)."""
# ruff: noqa: S105, S106

from __future__ import annotations

import itertools
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import pytest
from boto3.session import Session
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.stub import Stubber
from neurosphere_connector_aws_bedrock import boto3_reader
from neurosphere_connector_aws_bedrock.aws_auth import AwsCredentials
from neurosphere_connector_aws_bedrock.boto3_reader import Boto3BedrockReader
from neurosphere_connector_aws_bedrock.models import CostWindow, UsageWindow
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    RateLimitedError,
    UnauthorizedError,
)

_T0 = datetime(2026, 11, 1, tzinfo=UTC)


class _Provider:
    auth_mode: Literal["vault_reference"] = "vault_reference"

    def __init__(self) -> None:
        self.n = 0

    async def get(self) -> AwsCredentials:
        self.n += 1
        return AwsCredentials(access_key_id=f"AKIA-test-{self.n}", secret_access_key="s")


def _stubbed(*services: str) -> tuple[dict[str, Any], dict[str, Stubber]]:
    clients: dict[str, Any] = {}
    stubs: dict[str, Stubber] = {}
    for service in services:
        dummy = {"aws_access_key_id": "x", "aws_secret_access_key": "y"}
        client = Session(region_name="us-east-1", **dummy).client(
            service, config=Config(retries={"max_attempts": 1})
        )
        clients[service] = client
        stubs[service] = Stubber(client)
    return clients, stubs


def _reader(clients: dict[str, Any], **kw: Any) -> Boto3BedrockReader:
    async def no_sleep(_s: float) -> None:
        return None

    kw.setdefault("sleep", no_sleep)
    return Boto3BedrockReader(
        provider=_Provider(), region="us-east-1", client_factory=lambda s, _c, _r: clients[s], **kw
    )


# ------------------------------------------------------------------ stubbed, model-validated


async def test_inventory_calls_validate_against_the_service_models_and_drop_free_text() -> None:
    clients, stubs = _stubbed("bedrock", "bedrock-agent")
    created = _T0
    stubs["bedrock"].add_response(
        "list_foundation_models",
        {
            "modelSummaries": [
                {
                    "modelArn": "arn:aws:bedrock:us-east-1::foundation-model/acme.m1",
                    "modelId": "acme.m1",
                    "modelName": "M1",
                    "providerName": "Acme",
                    "inputModalities": ["TEXT"],
                    "outputModalities": ["TEXT"],
                    "modelLifecycle": {"status": "ACTIVE"},
                }
            ]
        },
    )
    stubs["bedrock"].add_response(
        "list_custom_models",
        {
            "modelSummaries": [
                {
                    "modelArn": "arn:aws:bedrock:us-east-1:111122223333:custom-model/c1",
                    "modelName": "c1",
                    "baseModelArn": "arn:aws:bedrock:us-east-1::foundation-model/acme.m1",
                    "baseModelName": "M1",
                    "creationTime": created,
                    "modelStatus": "Active",
                }
            ]
        },
    )
    stubs["bedrock"].add_response(
        "list_provisioned_model_throughputs",
        {
            "provisionedModelSummaries": [
                {
                    "provisionedModelName": "pt1",
                    "provisionedModelArn": "arn:aws:bedrock:us-east-1:111122223333:pt/1",
                    "modelArn": "arn:aws:bedrock:us-east-1::foundation-model/acme.m1",
                    "desiredModelArn": "arn:aws:bedrock:us-east-1::foundation-model/acme.m1",
                    "foundationModelArn": "arn:aws:bedrock:us-east-1::foundation-model/acme.m1",
                    "modelUnits": 1,
                    "desiredModelUnits": 1,
                    "status": "InService",
                    "creationTime": created,
                    "lastModifiedTime": created,
                }
            ]
        },
    )
    stubs["bedrock"].add_response(
        "list_guardrails",
        {
            "guardrails": [
                {
                    "id": "g1",
                    "arn": "arn:aws:bedrock:us-east-1:111122223333:guardrail/g1",
                    "status": "READY",
                    "name": "guard",
                    "description": "block the secret project name Falcon",
                    "version": "DRAFT",
                    "createdAt": created,
                    "updatedAt": created,
                }
            ]
        },
    )
    stubs["bedrock-agent"].add_response(
        "list_agents",
        {
            "agentSummaries": [
                {
                    "agentId": "a1",
                    "agentName": "helper",
                    "agentStatus": "PREPARED",
                    "description": "internal HR agent for salaries",
                    "updatedAt": created,
                }
            ]
        },
    )
    for stub in stubs.values():
        stub.activate()
    reader = _reader(clients)
    fm = await reader.list_foundation_models(limit=10)
    cm = await reader.list_custom_models(limit=10)
    pt = await reader.list_provisioned_throughput(limit=10)
    gr = await reader.list_guardrails(limit=10)
    ag = await reader.list_agents(limit=10)
    assert fm.items[0] == {
        "id": "acme.m1",
        "name": "M1",
        "status": "ACTIVE",
        "provider": "Acme",
        "input_modalities": ["TEXT"],
        "output_modalities": ["TEXT"],
    }
    assert cm.items[0]["created_at"] == created
    assert pt.items[0]["status"] == "InService"
    assert gr.items[0]["id"] == "g1"
    assert ag.items[0]["id"] == "a1"
    blob = repr([fm, cm, pt, gr, ag])
    assert "Falcon" not in blob
    assert "salaries" not in blob
    for stub in stubs.values():
        stub.assert_no_pending_responses()


async def test_usage_request_is_model_valid_and_missing_hours_stay_absent() -> None:
    clients, stubs = _stubbed("cloudwatch")
    stubs["cloudwatch"].add_response(
        "get_metric_data",
        {
            "MetricDataResults": [
                {
                    "Id": "q0",
                    "Label": "Invocations",
                    "Timestamps": [_T0],
                    "Values": [4.0],
                    "StatusCode": "Complete",
                },
                {"Id": "q1", "Label": "InputTokenCount", "Timestamps": [], "Values": []},
            ]
        },
    )
    stubs["cloudwatch"].activate()
    window = UsageWindow(start=_T0, end=_T0 + timedelta(hours=2))
    page = await _reader(clients).get_usage(model_ids=["acme.m1"], window=window, limit=100)
    assert page.truncated is False
    assert page.items == (
        {"model_id": "acme.m1", "metric": "Invocations", "hour": _T0, "value": 4.0},
    )
    stubs["cloudwatch"].assert_no_pending_responses()


async def test_cost_request_is_model_valid_and_parses_estimated_and_currency() -> None:
    clients, stubs = _stubbed("ce")
    stubs["ce"].add_response(
        "get_cost_and_usage",
        {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": "2026-11-01", "End": "2026-11-02"},
                    "Total": {},
                    "Groups": [
                        {
                            "Keys": ["Amazon Bedrock"],
                            "Metrics": {"UnblendedCost": {"Amount": "1.25", "Unit": "USD"}},
                        }
                    ],
                    "Estimated": True,
                }
            ]
        },
    )
    stubs["ce"].activate()
    window = CostWindow(start=date(2026, 11, 1), end=date(2026, 11, 2))
    page = await _reader(clients).get_cost(window=window, services=["Amazon Bedrock"], limit=10)
    assert page.items == (
        {
            "day": date(2026, 11, 1),
            "service": "Amazon Bedrock",
            "amount": "1.25",
            "currency": "USD",
            "estimated": True,
        },
    )


async def test_logging_setting_keeps_destination_types_not_names() -> None:
    clients, stubs = _stubbed("bedrock")
    stubs["bedrock"].add_response(
        "get_model_invocation_logging_configuration",
        {
            "loggingConfig": {
                "cloudWatchConfig": {
                    "logGroupName": "/aws/bedrock/prod-prompts",
                    "roleArn": "arn:aws:iam::111122223333:role/r",
                },
                "textDataDeliveryEnabled": True,
            }
        },
    )
    stubs["bedrock"].activate()
    state = await _reader(clients).get_invocation_logging()
    assert state == {"cloudwatch": True, "s3": False}


async def test_logging_not_configured_is_all_false() -> None:
    clients, stubs = _stubbed("bedrock")
    stubs["bedrock"].add_response("get_model_invocation_logging_configuration", {})
    stubs["bedrock"].activate()
    assert await _reader(clients).get_invocation_logging() == {"cloudwatch": False, "s3": False}


# ------------------------------------------------------------------ paging, caps, budgets


class _ScriptedClient:
    def __init__(self, script: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.script = script
        self.calls: list[dict[str, Any]] = []

    def list_custom_models(self, **params: Any) -> dict[str, Any]:
        self.calls.append(params)
        return self.script(params)

    list_agents = list_custom_models


_counter = itertools.count()


def _next_page(n: int) -> dict[str, Any]:
    """A page that always advertises another page, with a fresh cursor each time."""
    return {"modelSummaries": _custom_rows(n), "nextToken": f"t{next(_counter)}"}


def _custom_rows(n: int, start: int = 0) -> list[dict[str, Any]]:
    return [
        {"modelArn": f"arn:{i}", "modelName": f"n{i}", "modelStatus": "Active"}
        for i in range(start, start + n)
    ]


async def test_page_budget_stops_the_loop_and_marks_truncated() -> None:
    client = _ScriptedClient(lambda _p: _next_page(2))
    reader = _reader({"bedrock": client}, max_pages=3)
    page = await reader.list_custom_models(limit=1000)
    assert len(client.calls) == 3
    assert page.truncated is True


async def test_repeated_cursor_stops_early() -> None:
    client = _ScriptedClient(lambda _p: {"modelSummaries": [], "nextToken": "same"})
    page = await _reader({"bedrock": client}, max_pages=50).list_custom_models(limit=10)
    assert len(client.calls) == 2
    assert page.truncated is True


async def test_item_cap_truncates_and_stops() -> None:
    client = _ScriptedClient(lambda _p: _next_page(5))
    page = await _reader({"bedrock": client}, max_pages=9).list_custom_models(limit=7)
    assert len(page.items) == 7
    assert page.truncated is True
    assert len(client.calls) == 2


async def test_complete_listing_is_not_truncated() -> None:
    pages = iter(
        [
            {"modelSummaries": _custom_rows(2), "nextToken": "t"},
            {"modelSummaries": _custom_rows(1, 2)},
        ]
    )
    client = _ScriptedClient(lambda _p: next(pages))
    page = await _reader({"bedrock": client}).list_custom_models(limit=10)
    assert len(page.items) == 3
    assert page.truncated is False
    assert client.calls[1]["nextToken"] == "t"


# ------------------------------------------------------------------ errors and backoff


def _client_error(code: str, status: int, message: str = "boom") -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        "ListCustomModels",
    )


@pytest.mark.parametrize(
    ("error", "expected", "reason"),
    [
        (_client_error("ThrottlingException", 429), RateLimitedError, "aws_throttled"),
        (_client_error("LimitExceededException", 400), RateLimitedError, "aws_throttled"),
        (
            _client_error("InternalServerException", 500),
            DependencyTransientError,
            "aws_unavailable",
        ),
        (_client_error("ServiceUnavailable", 503), DependencyTransientError, "aws_unavailable"),
        (_client_error("AccessDeniedException", 403), ForbiddenError, "aws_access_denied"),
        (
            _client_error("UnrecognizedClientException", 401),
            UnauthorizedError,
            "aws_credentials_rejected",
        ),
        (
            EndpointConnectionError(endpoint_url="https://bedrock.us-east-1.amazonaws.com"),
            DependencyTransientError,
            "aws_unreachable",
        ),
    ],
)
async def test_aws_errors_map_to_typed_errors_with_capped_attempts(
    error: Exception, expected: type[Exception], reason: str
) -> None:
    client = _ScriptedClient(lambda _p: (_ for _ in ()).throw(error))
    sleeps: list[float] = []

    async def record(seconds: float) -> None:
        sleeps.append(seconds)

    reader = _reader(
        {"bedrock": client}, sleep=record, max_attempts=3, backoff_base=1, backoff_cap=1.5
    )
    with pytest.raises(expected) as err:
        await reader.list_custom_models(limit=5)
    assert getattr(err.value, "reason", None) == reason
    retried = expected in (RateLimitedError, DependencyTransientError)
    assert len(client.calls) == (3 if retried else 1)
    assert sleeps == ([1, 1.5] if retried else [])  # capped exponential backoff


async def test_aws_message_never_reaches_the_exception() -> None:
    secret = "AKIAIOSFODNN7EXAMPLE leaked in message"
    client = _ScriptedClient(
        lambda _p: (_ for _ in ()).throw(_client_error("Whatever", 400, secret))
    )
    with pytest.raises(DependencyTransientError) as err:
        await _reader({"bedrock": client}).list_custom_models(limit=5)
    assert secret not in str(err.value)
    assert secret not in repr(err.value)
    assert err.value.__cause__ is None
    assert err.value.__suppress_context__ is True


async def test_throttle_then_success_recovers() -> None:
    outcomes: list[Any] = [
        _client_error("ThrottlingException", 429),
        {"modelSummaries": _custom_rows(1)},
    ]

    def script(_p: dict[str, Any]) -> dict[str, Any]:
        out = outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    page = await _reader({"bedrock": _ScriptedClient(script)}).list_custom_models(limit=5)
    assert len(page.items) == 1


# ------------------------------------------------------------------ credentials per call


async def test_credentials_are_resolved_per_request_so_rotation_takes_effect() -> None:
    seen: list[str] = []

    def factory(_service: str, creds: AwsCredentials, _region: str) -> Any:
        seen.append(creds.access_key_id)
        return _ScriptedClient(lambda _p: {"modelSummaries": []})

    reader = Boto3BedrockReader(provider=_Provider(), region="us-east-1", client_factory=factory)
    await reader.list_custom_models(limit=1)
    await reader.list_custom_models(limit=1)
    assert seen == ["AKIA-test-1", "AKIA-test-2"]


def test_default_factory_uses_explicit_credentials_and_region_only() -> None:
    client = boto3_reader.default_client_factory(
        "bedrock", AwsCredentials(access_key_id="AKIAEXPLICIT", secret_access_key="s"), "eu-west-1"
    )
    assert client.meta.region_name == "eu-west-1"
    assert client.meta.config.retries["total_max_attempts"] == 1


def test_module_imports_and_reader_constructs_without_boto3() -> None:
    code = "\n".join(
        [
            "import sys",
            "sys.modules['boto3'] = None",
            "sys.modules['botocore'] = None",
            "from neurosphere_connector_aws_bedrock import aws_auth, boto3_reader, connector",
            "class P:",
            "    auth_mode = 'vault_reference'",
            "r = boto3_reader.Boto3BedrockReader(provider=P(), region='us-east-1')",
            "print(repr(r))",
        ]
    )
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert "us-east-1" in proc.stdout

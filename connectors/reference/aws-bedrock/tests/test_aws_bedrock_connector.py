"""PRP-62 item 3: the connector against a scripted fake reader (no AWS SDK, no network)."""

from __future__ import annotations

import logging
import socket
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from neurosphere_connector.health import HealthState
from neurosphere_connector_aws_bedrock.connector import GOVERNMENT_REASON, AwsBedrockConnector
from neurosphere_connector_aws_bedrock.models import CostWindow, UsageWindow
from neurosphere_connector_aws_bedrock.reader import ReaderPage
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    RateLimitedError,
)

_T0 = datetime(2026, 11, 1, tzinfo=UTC)
_SECRETS = (
    "AKIAIOSFODNN7EXAMPLE",
    "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "Summarise the quarterly numbers for Jane",
    "/aws/bedrock/modelinvocations-prod",
    "acme-bedrock-invocation-logs",
)


class FakeReader:
    """Scripted reader. Every call is recorded; a value that is an exception is raised."""

    def __init__(self, **script: Any) -> None:
        self.script = script
        self.calls: list[str] = []
        self.limits: dict[str, int] = {}

    def _take(self, name: str) -> Any:
        self.calls.append(name)
        value = self.script.get(name, ReaderPage(items=()))
        if isinstance(value, BaseException):
            raise value
        return value

    async def list_foundation_models(self, *, limit: int) -> ReaderPage:
        self.limits["foundation_models"] = limit
        return self._take("foundation_models")

    async def list_custom_models(self, *, limit: int) -> ReaderPage:
        return self._take("custom_models")

    async def list_provisioned_throughput(self, *, limit: int) -> ReaderPage:
        return self._take("provisioned_throughput")

    async def list_guardrails(self, *, limit: int) -> ReaderPage:
        return self._take("guardrails")

    async def list_agents(self, *, limit: int) -> ReaderPage:
        return self._take("agents")

    async def get_usage(
        self, *, model_ids: Sequence[str], window: UsageWindow, limit: int
    ) -> ReaderPage:
        return self._take("usage")

    async def get_cost(
        self, *, window: CostWindow, services: Sequence[str], limit: int
    ) -> ReaderPage:
        return self._take("cost")

    async def get_invocation_logging(self) -> Mapping[str, Any]:
        return self._take("logging")

    async def close(self) -> None:
        self.calls.append("close")


def _connector(reader: FakeReader, **kw: Any) -> AwsBedrockConnector:
    return AwsBedrockConnector(reader=reader, cloud=CloudName.COMMERCIAL, region="us-east-1", **kw)


# ------------------------------------------------------------------ government


@pytest.mark.parametrize(
    ("cloud", "region"),
    [
        (CloudName.GOVERNMENT, "us-east-1"),
        (CloudName.COMMERCIAL, "us-gov-west-1"),
        (CloudName.COMMERCIAL, "cn-north-1"),
        (CloudName.COMMERCIAL, "not a region"),
    ],
)
def test_government_and_govcloud_are_refused_without_any_request(
    monkeypatch: pytest.MonkeyPatch, cloud: CloudName, region: str
) -> None:
    def no_socket(*_a: Any, **_k: Any) -> None:
        raise AssertionError("no request may be made")

    monkeypatch.setattr(socket.socket, "connect", no_socket)
    monkeypatch.setattr(socket.socket, "connect_ex", no_socket)
    reader = FakeReader()
    with pytest.raises(CapabilityUnavailableError) as err:
        AwsBedrockConnector(reader=reader, cloud=cloud, region=region)
    assert err.value.code == "capability_unavailable"
    assert err.value.reason == GOVERNMENT_REASON
    assert reader.calls == []


# ------------------------------------------------------------------ inventory


def _models(n: int) -> ReaderPage:
    return ReaderPage(
        items=tuple(
            {
                "id": f"model-{i}",
                "name": f"Model {i}",
                "status": "ACTIVE",
                "provider": "Acme",
                "input_modalities": ["TEXT"],
                "output_modalities": ["TEXT"],
            }
            for i in range(n)
        )
    )


async def test_inventory_returns_typed_bounded_metadata() -> None:
    created = datetime(2026, 10, 1, tzinfo=UTC)
    reader = FakeReader(
        foundation_models=_models(2),
        custom_models=ReaderPage(items=({"id": "cm-1", "name": "tuned", "created_at": created},)),
        provisioned_throughput=ReaderPage(items=()),
        guardrails=ReaderPage(items=({"id": "gr-1", "name": "g", "status": "READY"},)),
        agents=ReaderPage(items=({"id": "ag-1", "name": "helper", "status": "PREPARED"},)),
    )
    inv = await _connector(reader).inventory()
    assert inv.region == "us-east-1"
    assert inv.advisory is True
    assert inv.foundation_models is not None
    assert [m.id for m in inv.foundation_models] == ["model-0", "model-1"]
    assert inv.foundation_models[0].input_modalities == ["TEXT"]
    assert inv.custom_models is not None
    assert inv.custom_models[0].created_at == created
    assert inv.provisioned_throughput == []  # answered and empty is [], distinct from None
    assert inv.failed_sources == {}
    assert inv.truncated == []


async def test_inventory_cap_sets_truncated_and_partial_coverage() -> None:
    reader = FakeReader(foundation_models=_models(10), custom_models=_models(2))
    connector = _connector(reader, max_items=3)
    inv = await connector.inventory()
    assert inv.foundation_models is not None
    assert len(inv.foundation_models) == 3
    assert inv.truncated == ["foundation_models"]
    assert reader.limits["foundation_models"] == 3
    cov = await connector.coverage()
    assert cov.partial is True


async def test_reader_reported_truncation_is_carried() -> None:
    page = ReaderPage(items=_models(2).items, truncated=True)
    inv = await _connector(FakeReader(agents=page)).inventory()
    assert inv.truncated == ["agents"]


async def test_failed_source_is_none_never_empty() -> None:
    reader = FakeReader(
        foundation_models=_models(1),
        guardrails=DependencyTransientError(reason="aws_unavailable"),
    )
    connector = _connector(reader)
    inv = await connector.inventory()
    assert inv.guardrails is None
    assert inv.failed_sources == {"guardrails": "dependency_transient"}
    cov = await connector.coverage()
    assert (cov.expected_sources, cov.answered_sources, cov.partial) == (5, 4, True)


async def test_all_sources_failing_raises_and_health_records_the_class() -> None:
    boom = RateLimitedError(30, reason="aws_throttled")
    reader = FakeReader(
        foundation_models=boom,
        custom_models=boom,
        provisioned_throughput=boom,
        guardrails=boom,
        agents=boom,
    )
    connector = _connector(reader)
    with pytest.raises(RateLimitedError):
        await connector.inventory()
    health = await connector.health()
    assert health.state is HealthState.RATE_LIMITED
    assert health.last_error_code == "rate_limited"


async def test_transient_failure_degrades_health_with_class_only() -> None:
    reader = FakeReader(
        **dict.fromkeys(
            (
                "foundation_models",
                "custom_models",
                "provisioned_throughput",
                "guardrails",
                "agents",
            ),
            DependencyTransientError(reason="aws_unavailable"),
        )
    )
    connector = _connector(reader)
    with pytest.raises(DependencyTransientError):
        await connector.inventory()
    health = await connector.health()
    assert health.state is HealthState.DEGRADED
    assert health.last_error_code == "dependency_transient"


# ------------------------------------------------------------------ usage and cost


async def test_usage_missing_datapoints_are_none_not_zero() -> None:
    window = UsageWindow(start=_T0, end=_T0 + timedelta(hours=3))
    reader = FakeReader(
        usage=ReaderPage(
            items=(
                {"model_id": "m1", "metric": "Invocations", "hour": _T0, "value": 7.0},
                {
                    "model_id": "m1",
                    "metric": "InputTokenCount",
                    "hour": _T0 + timedelta(hours=2),
                    "value": 0.0,
                },
            )
        )
    )
    res = await _connector(reader).usage(window, ["m1"])
    assert len(res.points) == 1 * 3 * 3
    by_key = {(p.metric, p.hour): p.value for p in res.points}
    assert by_key[("Invocations", _T0)] == 7.0
    assert by_key[("Invocations", _T0 + timedelta(hours=1))] is None
    assert by_key[("InputTokenCount", _T0 + timedelta(hours=2))] == 0.0  # a reported zero stays 0
    assert by_key[("OutputTokenCount", _T0)] is None
    assert res.truncated is False


async def test_usage_is_capped_and_marks_truncation() -> None:
    window = UsageWindow(start=_T0, end=_T0 + timedelta(hours=24))
    res = await _connector(FakeReader(), max_points=10).usage(window, ["m1", "m2"])
    assert len(res.points) == 10
    assert res.truncated is True


async def test_usage_rejects_empty_and_oversized_model_lists() -> None:
    window = UsageWindow(start=_T0, end=_T0 + timedelta(hours=1))
    connector = _connector(FakeReader())
    with pytest.raises(ValueError, match="must not be empty"):
        await connector.usage(window, [])
    with pytest.raises(ValueError, match="at most"):
        await connector.usage(window, [f"m{i}" for i in range(51)])


async def test_cost_carries_estimated_versus_invoiced_currency_and_none_for_missing_days() -> None:
    window = CostWindow(start=date(2026, 11, 1), end=date(2026, 11, 4))
    reader = FakeReader(
        cost=ReaderPage(
            items=(
                {
                    "day": date(2026, 11, 1),
                    "service": "Amazon Bedrock",
                    "amount": "12.5000",
                    "currency": "USD",
                    "estimated": False,
                },
                {
                    "day": date(2026, 11, 3),
                    "service": "Amazon Bedrock",
                    "amount": "3.1",
                    "currency": "USD",
                    "estimated": True,
                },
            )
        )
    )
    res = await _connector(reader).cost(window)
    assert [p.day for p in res.points] == window.days()
    first, gap, last = res.points
    assert (first.amount, first.amount_kind, first.currency) == (Decimal("12.5"), "invoiced", "USD")
    assert (gap.amount, gap.amount_kind, gap.currency) == (None, None, None)
    assert (last.amount, last.amount_kind) == (Decimal("3.1"), "estimated")


async def test_cost_bad_amount_is_none_not_zero() -> None:
    window = CostWindow(start=date(2026, 11, 1), end=date(2026, 11, 2))
    reader = FakeReader(
        cost=ReaderPage(
            items=({"day": date(2026, 11, 1), "service": "Amazon Bedrock", "amount": "NaN"},)
        )
    )
    res = await _connector(reader).cost(window)
    assert res.points[0].amount is None


async def test_cost_failure_propagates_and_is_recorded() -> None:
    window = CostWindow(start=date(2026, 11, 1), end=date(2026, 11, 2))
    connector = _connector(FakeReader(cost=RateLimitedError(5, reason="aws_throttled")))
    with pytest.raises(RateLimitedError):
        await connector.cost(window)
    assert (await connector.health()).state is HealthState.RATE_LIMITED


# ------------------------------------------------------------------ logging setting


async def test_logging_state_is_booleans_only() -> None:
    reader = FakeReader(logging={"cloudwatch": True, "s3": False})
    state = await _connector(reader).logging_state()
    assert (state.configured, state.cloudwatch, state.s3) == (True, True, False)
    off = await _connector(FakeReader(logging={"cloudwatch": False, "s3": False})).logging_state()
    assert off.configured is False


# ------------------------------------------------------------------ metadata only


async def test_prompt_like_text_keys_and_log_names_never_reach_outputs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    window = UsageWindow(start=_T0, end=_T0 + timedelta(hours=1))
    cwindow = CostWindow(start=date(2026, 11, 1), end=date(2026, 11, 2))
    extras = {
        "prompt": _SECRETS[2],
        "access_key_id": _SECRETS[0],
        "secret_access_key": _SECRETS[1],
        "log_group": _SECRETS[3],
        "bucket": _SECRETS[4],
    }
    reader = FakeReader(
        foundation_models=ReaderPage(items=({"id": "m1", "name": "n", **extras},)),
        agents=ReaderPage(items=({"id": "a1", "instruction": _SECRETS[2], **extras},)),
        usage=ReaderPage(
            items=({"model_id": "m1", "metric": "Invocations", "hour": _T0, "value": 1, **extras},)
        ),
        cost=ReaderPage(
            items=(
                {"day": date(2026, 11, 1), "service": "Amazon Bedrock", "amount": "1", **extras},
            )
        ),
        logging={"cloudwatch": True, "s3": True, **extras},
    )
    connector = _connector(reader)
    with caplog.at_level(logging.DEBUG):
        inv = await connector.inventory()
        usage = await connector.usage(window, ["m1"])
        cost = await connector.cost(cwindow)
        state = await connector.logging_state()
    health = await connector.health()
    blob = " ".join(
        [
            inv.model_dump_json(),
            repr(inv),
            usage.model_dump_json(),
            cost.model_dump_json(),
            state.model_dump_json(),
            repr(state),
            health.model_dump_json(),
            repr(connector),
            connector.manifest.model_dump_json(),
            caplog.text,
        ]
    )
    for secret in _SECRETS:
        assert secret not in blob


# ------------------------------------------------------------------ lifecycle


async def test_close_closes_the_reader() -> None:
    reader = FakeReader()
    connector = _connector(reader)
    await connector.close()
    assert reader.calls == ["close"]
    assert connector.closed is True

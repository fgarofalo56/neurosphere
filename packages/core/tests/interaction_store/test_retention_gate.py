"""PRP-102 item 4: no content is written unless the customer retention policy opts in."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from neurosphere_core.interactions import (
    InMemoryInteractionStore,
    InteractionStoreError,
    content_writes_enabled,
)
from neurosphere_core.interactions.store import METRIC_INTERACTION_REFUSALS
from neurosphere_core.lifecycle.policy import UNSET, PolicyState, load_policy
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from ._support import KEK_URI, canary, make_content, make_record, new_id, policy

_GATE_CASES: dict[str, PolicyState] = {
    "no_policy": UNSET,
    "invalid_policy": load_policy({"policy_version": "v1", "rules": []}),
    "opt_in_false": policy(opt_in=False),
    "no_interaction_content_rule": policy(rule=False),
}


def test_gate_open_only_with_opt_in_and_rule() -> None:
    assert content_writes_enabled(policy()) is True
    for state in _GATE_CASES.values():
        assert content_writes_enabled(state) is False
    assert content_writes_enabled(None) is False  # type: ignore[arg-type]


def _refusal_points(reader: InMemoryMetricReader) -> dict[str, int]:
    data = reader.get_metrics_data()
    counts: dict[str, int] = {}
    if data is None:
        return counts
    for resource in data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name != METRIC_INTERACTION_REFUSALS:
                    continue
                for point in metric.data.data_points:
                    reason = str(point.attributes.get("ns.reason"))  # type: ignore[union-attr]
                    counts[reason] = counts.get(reason, 0) + int(point.value)  # type: ignore[attr-defined]
    return counts


@pytest.mark.parametrize("case", sorted(_GATE_CASES))
async def test_closed_gate_refuses_before_any_io_and_counts(
    local_wrapper: Any, case: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    reader = InMemoryMetricReader()
    meter = MeterProvider(metric_readers=[reader]).get_meter("test")
    store = InMemoryInteractionStore(
        local_wrapper, kek_uri=KEK_URI, policy=_GATE_CASES[case], meter=meter
    )
    secret = canary()
    iid = new_id()
    with pytest.raises(InteractionStoreError) as caught:
        await store.put(make_record(iid), make_content(iid, secret), capture_retention_days=30)
    assert str(caught.value) == "content_retention_not_enabled"
    assert store.index_backend.documents == {}
    assert store.content_backend.blobs == {}
    assert store.refusals == {"content_retention_not_enabled": 1}
    assert _refusal_points(reader) == {"content_retention_not_enabled": 1}
    assert secret not in caplog.text


async def test_gate_runs_before_content_validation(local_wrapper: Any) -> None:
    store = InMemoryInteractionStore(local_wrapper, kek_uri=KEK_URI, policy=UNSET)
    with pytest.raises(InteractionStoreError) as caught:
        await store.put(make_record(new_id()), "not content", capture_retention_days=30)  # type: ignore[arg-type]
    assert caught.value.reason == "content_retention_not_enabled"


async def test_turning_the_opt_in_off_stops_writes_immediately(local_wrapper: Any) -> None:
    current = {"state": policy()}
    store = InMemoryInteractionStore(
        local_wrapper, kek_uri=KEK_URI, policy=lambda: current["state"]
    )
    first = new_id()
    await store.put(make_record(first), make_content(first), capture_retention_days=30)
    current["state"] = policy(opt_in=False)
    second = new_id()
    with pytest.raises(InteractionStoreError):
        await store.put(make_record(second), make_content(second), capture_retention_days=30)
    assert len(store.content_backend.blobs) == 1


@pytest.mark.parametrize(
    ("capture_days", "rule_days", "expected"),
    [
        (30, 90, "2026-12-20T10:15:01.000000Z"),
        (90, 10, "2026-11-30T10:15:01.000000Z"),
        (90, 90, "2027-02-18T10:15:01.000000Z"),
        (1, 365, "2026-11-21T10:15:01.000000Z"),
    ],
)
async def test_expires_at_is_the_earlier_of_capture_and_rule(
    local_wrapper: Any, capture_days: int, rule_days: int, expected: str
) -> None:
    store = InMemoryInteractionStore(
        local_wrapper, kek_uri=KEK_URI, policy=policy(max_days=rule_days)
    )
    iid = new_id()
    stored = await store.put(
        make_record(iid), make_content(iid), capture_retention_days=capture_days
    )
    assert stored.expires_at.root == expected
    assert stored.captured_at.root == "2026-11-20T10:15:01.000000Z"


@pytest.mark.parametrize("days", [0, 366, -1, True, 1.5])
async def test_capture_retention_days_is_bounded(local_wrapper: Any, days: Any) -> None:
    store = InMemoryInteractionStore(local_wrapper, kek_uri=KEK_URI, policy=policy())
    iid = new_id()
    with pytest.raises(ValueError):
        await store.put(make_record(iid), make_content(iid), capture_retention_days=days)
    assert store.content_backend.blobs == {}

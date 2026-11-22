"""PRP-139 item 3: ``summarize`` for the four sources."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from neurosphere_core.sources_status import (
    ConfiguredConnector,
    ConnectorRunStatus,
    GatewayHealth,
    summarize,
)

NOW = datetime(2026, 11, 21, 10, 0, tzinfo=UTC)


def run(kind: str, state: str, reason: str | None = None, **counts: int) -> ConnectorRunStatus:
    body: dict[str, Any] = {
        "kind": kind,
        "state": state,
        "reason": reason,
        "last_attempt_at": NOW,
        "last_success_at": NOW if state in ("ok", "partial") else None,
        "counts": counts,
    }
    return ConnectorRunStatus.model_validate(body)


def cfg(kind: str, enabled: bool = True) -> ConfiguredConnector:
    return ConfiguredConnector(kind=kind, enabled=enabled)


def test_nothing_configured_is_four_sources_in_order_not_connected() -> None:
    summary = summarize([], [])
    assert [i.source for i in summary.sources] == [
        "foundry",
        "apim_gateway",
        "billing",
        "azure_monitor_telemetry",
    ]
    assert {i.state for i in summary.sources} == {"not_connected"}
    assert [i.available for i in summary.sources] == [True, True, True, True]
    assert [c.kind for c in summary.connectors] == [
        "foundry_discovery",
        "gateway_poll",
        "billing_export",
        "azure_monitor_ai",
    ]


def test_application_insights_ignores_the_other_connectors_runs() -> None:
    everything = [
        run(k, "ok", records=5, gateways_polled=1, events_posted=0)
        for k in ("foundry_discovery", "gateway_poll", "billing_export")
    ]
    item = summarize(everything, [cfg("foundry_discovery")]).sources[3]
    assert (item.source, item.state, item.available) == (
        "azure_monitor_telemetry",
        "not_connected",
        True,
    )
    assert item.reason is None
    assert item.last_success_at is None


@pytest.mark.parametrize(
    ("status", "enabled", "state"),
    [
        (run("foundry_discovery", "failed", "source_access_denied"), True, "failing"),
        (run("foundry_discovery", "ok", records=4), True, "connected"),
        (run("foundry_discovery", "ok", records=0), True, "connected_no_data"),
        (run("foundry_discovery", "partial", "partial_results", records=2), True, "connected"),
        (run("foundry_discovery", "idle", "disabled"), True, "connected_no_data"),
        (run("foundry_discovery", "idle", "disabled"), False, "not_connected"),
        (run("foundry_discovery", "not_configured"), False, "not_connected"),
        (run("foundry_discovery", "not_configured"), True, "not_connected"),
        (run("billing_export", "ok", "unchanged", records=0), True, "connected"),
        (run("billing_export", "ok", records=0), True, "connected_no_data"),
        (None, True, "not_connected"),
        (None, False, "not_connected"),
    ],
)
def test_state_per_run(status: ConnectorRunStatus | None, enabled: bool, state: str) -> None:
    kind = (
        "billing_export"
        if status is not None and status.kind == "billing_export"
        else ("foundry_discovery")
    )
    summary = summarize([] if status is None else [status], [cfg(kind, enabled)])
    index = 2 if kind == "billing_export" else 0
    assert summary.sources[index].state == state


def test_last_success_time_is_reported_even_while_failing() -> None:
    failing = ConnectorRunStatus(
        kind="billing_export",
        state="failed",
        reason="source_access_denied",
        last_attempt_at=NOW,
        last_success_at=NOW,
    )
    item = summarize([failing], [cfg("billing_export")]).sources[2]
    assert item.state == "failing"
    assert item.last_success_at == NOW
    assert item.reason == "source_access_denied"


def test_one_failing_source_leaves_the_others_alone() -> None:
    summary = summarize(
        [
            run("foundry_discovery", "failed", "source_access_denied"),
            run("gateway_poll", "ok", gateways_polled=2),
        ],
        [cfg("foundry_discovery"), cfg("gateway_poll")],
    )
    assert [i.state for i in summary.sources[:3]] == ["failing", "connected", "not_connected"]


def test_an_enabled_configuration_with_no_run_is_awaiting_the_first_run() -> None:
    summary = summarize([], [cfg("gateway_poll")])
    assert summary.sources[1].reason == "awaiting_first_run"
    assert summary.connectors[1].state == "not_configured"
    assert summary.connectors[1].reason == "awaiting_first_run"


def test_gateway_registrations_stand_in_when_no_worker_status_exists() -> None:
    polled = summarize([], [], [GatewayHealth("ok", has_watermark=True)])
    assert polled.sources[1].state == "connected"
    failing = summarize([], [], [GatewayHealth("poll_failed:forbidden")])
    assert failing.sources[1].state == "failing"
    assert summarize([], [], []).sources[1].state == "not_connected"


def test_gateway_run_with_no_gateways_is_connected_no_data() -> None:
    summary = summarize([run("gateway_poll", "idle", "no_gateways")], [cfg("gateway_poll")])
    assert summary.sources[1].state == "connected_no_data"

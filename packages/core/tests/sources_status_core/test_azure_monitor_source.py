"""PRP-141 item 4: the Application Insights source is computed from ``azure_monitor_ai``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from neurosphere_core.sources_status import (
    CONNECTOR_KINDS,
    ConfiguredConnector,
    ConnectorRunStatus,
    summarize,
)

NOW = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)
KIND = "azure_monitor_ai"


def run(state: str, reason: str | None = None, **counts: int) -> ConnectorRunStatus:
    body: dict[str, Any] = {
        "kind": KIND,
        "state": state,
        "reason": reason,
        "last_attempt_at": NOW,
        "last_success_at": NOW if state in ("ok", "partial") else None,
        "counts": counts,
    }
    return ConnectorRunStatus.model_validate(body)


def cfg(enabled: bool = True) -> ConfiguredConnector:
    return ConfiguredConnector(kind=KIND, enabled=enabled)


def test_kind_is_registered() -> None:
    assert CONNECTOR_KINDS[-1] == KIND


@pytest.mark.parametrize(
    ("status", "configs", "state", "reason"),
    [
        (None, [], "not_connected", None),
        (None, [cfg()], "not_connected", "awaiting_first_run"),
        (run("not_configured"), [], "not_connected", None),
        (run("not_configured"), [cfg()], "not_connected", "awaiting_first_run"),
        (
            run("ok", queries=2, rows=9, events_posted=7, rows_skipped=2),
            [cfg()],
            "connected",
            None,
        ),
        (
            run("partial", "rate_limited", queries=2, rows=9, events_posted=3, rows_skipped=0),
            [cfg()],
            "connected",
            "rate_limited",
        ),
        (
            run("ok", queries=2, rows=0, events_posted=0, rows_skipped=0),
            [cfg()],
            "connected_no_data",
            None,
        ),
        (run("idle", "disabled"), [cfg()], "connected_no_data", "disabled"),
        (run("failed", "source_access_denied"), [cfg()], "failing", "source_access_denied"),
    ],
)
def test_four_states_are_reachable(
    status: ConnectorRunStatus | None,
    configs: list[ConfiguredConnector],
    state: str,
    reason: str | None,
) -> None:
    item = summarize([] if status is None else [status], configs).sources[3]
    assert item.source == "azure_monitor_telemetry"
    assert item.available is True
    assert (item.state, item.reason) == (state, reason)


def test_admin_connectors_view_carries_the_counts() -> None:
    counts = {"queries": 2, "rows": 9, "events_posted": 7, "rows_skipped": 2}
    summary = summarize([run("ok", queries=2, rows=9, events_posted=7, rows_skipped=2)], [cfg()])
    connector = summary.connectors[3]
    assert connector.kind == KIND
    assert dict(connector.counts) == counts
    assert connector.last_success_at == NOW


def test_summary_items_hold_no_ids_hosts_or_tokens() -> None:
    summary = summarize([run("ok", queries=1, rows=1, events_posted=1)], [cfg()])
    item = summary.sources[3]
    assert set(item.__slots__) == {"source", "state", "last_success_at", "available", "reason"}

"""Fakes for the azure_monitor_ai tests: scripted connector, recording ingest API, clock, rig."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
from neurosphere_connector import CoverageReport, FreshnessReport
from neurosphere_connector_azure_monitor import MonitorSource, PollBounds, PollResult, SourceKind
from neurosphere_workers.ingestion.azure_monitor_ai import (
    AzureMonitorAiPoller,
    AzureMonitorAiSettings,
)
from neurosphere_workers.ingestion.gateway_poll import IngestClient, MonitorPort
from neurosphere_workers.runtime.checkpoint import InMemoryCheckpointStore

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURES = REPO_ROOT / "connectors" / "reference" / "azure-monitor" / "tests" / "fixtures"

NOW = datetime(2026, 11, 22, 10, 30, tzinfo=UTC)
CUSTOMER = "synthco"
DOMAIN = "dom-1"
WS1 = "11111111-1111-1111-1111-111111111111"
WS2 = "22222222-2222-2222-2222-222222222222"
FAKE_SECRET = "local-only-fake-azure-monitor-ai-secret"  # noqa: S105 - fake test value
DEPS = SourceKind.APP_GENAI_DEPENDENCIES
REQS = SourceKind.APP_GENAI_REQUESTS
GUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")


def fixture_rows(name: str, kind: SourceKind, workspace: str = WS1) -> list[dict[str, Any]]:
    """Rows as the connector returns them (``source_kind``/``source_id`` plus the columns)."""
    doc = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    table = doc["tables"][0]
    names = [c["name"] for c in table["columns"]]
    return [
        {"source_kind": kind.value, "source_id": workspace, **dict(zip(names, row, strict=True))}
        for row in table["rows"]
    ]


def dep_rows(workspace: str = WS1) -> list[dict[str, Any]]:
    """Six rows: five map, one has bad ids and is skipped."""
    return fixture_rows("genai_dependencies_response.json", DEPS, workspace)


def req_rows(workspace: str = WS1) -> list[dict[str, Any]]:
    """One row that maps."""
    return fixture_rows("genai_requests_response.json", REQS, workspace)


def result(
    records: list[dict[str, Any]],
    *,
    next_watermark: datetime,
    requests_made: int = 1,
    partial: bool = False,
    rate_limited: bool = False,
    truncated_pages: int = 0,
    stalled_slice_start: datetime | None = None,
    failed: bool = False,
) -> PollResult:
    return PollResult(
        records=records,
        next_watermark=next_watermark,
        partial=partial,
        pages_used=1,
        page_budget=4,
        requests_made=requests_made,
        coverage=CoverageReport(expected_sources=1, answered_sources=0 if failed else 1),
        freshness=FreshnessReport(),
        failed_sources={"x": "dependency_transient"} if failed else {},
        truncated_pages=truncated_pages,
        rate_limited=rate_limited,
        stalled_slice_start=stalled_slice_start,
    )


Script = Mapping[tuple[SourceKind, str], Sequence[PollResult | Exception]]


class FakeConnector:
    """Scripted per (kind, workspace); an unscripted poll returns no rows and no progress."""

    def __init__(self, script: Script | None = None) -> None:
        self._script = {key: list(items) for key, items in (script or {}).items()}
        self.calls: list[tuple[SourceKind, str, datetime | None]] = []
        self.closed = 0

    async def poll(
        self, sources: Sequence[MonitorSource], *, watermark: datetime | None = None
    ) -> PollResult:
        assert len(sources) == 1  # one MonitorSource per workspace and kind
        source = sources[0]
        self.calls.append((source.kind, source.source_id, watermark))
        queue = self._script.get((source.kind, source.source_id), [])
        if not queue:
            return result([], next_watermark=watermark or NOW)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed += 1


class FakeIngestApi:
    def __init__(self) -> None:
        self.batches: list[list[dict[str, Any]]] = []
        self.urls: list[str] = []
        self.status = 202
        self.fail_after: int | None = None  # accept this many batches, then answer 500

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        failing = self.fail_after is not None and len(self.batches) >= self.fail_after
        if self.status != 202 or failing:
            return httpx.Response(self.status if self.status != 202 else 500, json={})
        batch = json.loads(request.content)
        self.batches.append(batch)
        return httpx.Response(202, json={"accepted": len(batch), "rejected": []})

    @property
    def events(self) -> list[dict[str, Any]]:
        return [event for batch in self.batches for event in batch]


class Rig:
    def __init__(
        self,
        connector: FakeConnector | None = None,
        *,
        cloud: Literal["commercial", "government"] = "commercial",
        checkpoints: InMemoryCheckpointStore | None = None,
        **overrides: Any,
    ) -> None:
        self.connector = connector or FakeConnector()
        self.api = FakeIngestApi()
        self.checkpoints = checkpoints or InMemoryCheckpointStore()
        values: dict[str, Any] = {"workspace_ids": WS1, "domain_id": DOMAIN}
        values.update(overrides)
        self.settings = AzureMonitorAiSettings(**values)
        self.factory_calls: list[tuple[str, PollBounds]] = []
        self.now = NOW
        http = httpx.AsyncClient(transport=httpx.MockTransport(self.api.handler))
        self.poller = AzureMonitorAiPoller(
            ingest=IngestClient(
                http,
                base_url="http://127.0.0.1:8000",
                producer_id=self.settings.producer_id,
                secret=FAKE_SECRET,
            ),
            checkpoints=self.checkpoints,
            settings=self.settings,
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
            cloud=cloud,
            connector_factory=self._factory,
            clock=lambda: self.now,
        )

    def _factory(self, cloud: str, bounds: PollBounds) -> MonitorPort:
        self.factory_calls.append((cloud, bounds))
        return self.connector


def at(minutes_ago: int) -> datetime:
    return NOW - timedelta(minutes=minutes_ago)

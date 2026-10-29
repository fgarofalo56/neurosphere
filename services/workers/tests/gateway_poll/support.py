"""Fakes for the gateway_poll tests: scripted connector, recording ingest API, registrations."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
from neurosphere_connector import CoverageReport, FreshnessReport
from neurosphere_connector_azure_monitor import MonitorSource, PollBounds, PollResult
from neurosphere_core.gateway import GatewayRegistration, InMemoryGatewayStore, gateway_id_for
from neurosphere_workers.ingestion.gateway_poll import (
    GatewayPoller,
    GatewayPollSettings,
    IngestClient,
    MonitorPort,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURES = REPO_ROOT / "connectors" / "reference" / "azure-monitor" / "tests" / "fixtures"

NOW = datetime(2026, 10, 29, 10, 30, tzinfo=UTC)
CUSTOMER = "synthco"
DOMAIN = "dom-1"
WORKSPACE = "11111111-1111-1111-1111-111111111111"
# A clearly fake, local-only secret. Its sha256 is what producers.example.json carries.
FAKE_SECRET = "local-only-fake-gateway-poll-secret"  # noqa: S105 - fake test value
ARM_ID = (
    "/subscriptions/22222222-2222-2222-2222-222222222222/resourceGroups/rg-demo"
    "/providers/Microsoft.ApiManagement/service/apim-demo"
)


def fixture_rows(name: str, kind: str) -> list[dict[str, Any]]:
    doc = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    table = doc["tables"][0]
    names = [c["name"] for c in table["columns"]]
    return [
        {"source_kind": kind, "source_id": WORKSPACE, **dict(zip(names, row, strict=True))}
        for row in table["rows"]
    ]


def all_rows() -> list[dict[str, Any]]:
    return [
        *fixture_rows("apim_gateway_response.json", "apim_gateway"),
        *fixture_rows("apim_mcp_response.json", "apim_mcp"),
    ]


def result(
    records: list[dict[str, Any]],
    *,
    next_watermark: datetime,
    answered: int = 2,
    partial: bool = False,
    lag_ms: int | None = 60_000,
) -> PollResult:
    return PollResult(
        records=records,
        next_watermark=next_watermark,
        partial=partial,
        pages_used=1,
        page_budget=4,
        requests_made=2,
        coverage=CoverageReport(expected_sources=2, answered_sources=answered, partial=partial),
        freshness=FreshnessReport(lag_ms=lag_ms) if lag_ms is not None else FreshnessReport(),
        failed_sources={} if answered == 2 else {WORKSPACE: "dependency_transient"},
    )


class FakeConnector:
    """Returns scripted results in order (the last one repeats) and records every call."""

    def __init__(self, results: Sequence[PollResult | Exception]) -> None:
        self._results = list(results)
        self.calls: list[tuple[list[MonitorSource], datetime | None]] = []
        self.closed = 0

    async def poll(
        self, sources: Sequence[MonitorSource], *, watermark: datetime | None = None
    ) -> PollResult:
        self.calls.append((list(sources), watermark))
        item = self._results[min(len(self.calls) - 1, len(self._results) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed += 1


class FakeIngestApi:
    """Records posted batches; answers like the ingest edge (202 + counts) or a scripted error."""

    def __init__(self) -> None:
        self.batches: list[list[dict[str, Any]]] = []
        self.headers: list[httpx.Headers] = []
        self.status = 202

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.headers.append(request.headers)
        if self.status != 202:
            return httpx.Response(self.status, json={"error": "scripted"})
        batch = json.loads(request.content)
        self.batches.append(batch)
        return httpx.Response(202, json={"accepted": len(batch), "rejected": []})

    @property
    def events(self) -> list[dict[str, Any]]:
        return [event for batch in self.batches for event in batch]


def registration(
    *,
    cloud: Literal["commercial", "government"] = "commercial",
    workspace_id: str | None = WORKSPACE,
    poll_watermark: datetime | None = None,
    arm_id: str = ARM_ID,
) -> GatewayRegistration:
    return GatewayRegistration(
        id=gateway_id_for(CUSTOMER, DOMAIN, arm_id),
        customer_id=CUSTOMER,
        domain_id=DOMAIN,
        cloud=cloud,
        arm_resource_id=arm_id,
        name="apim-demo",
        tier="standard_v2",
        workspace_id=workspace_id,
        poll_watermark=poll_watermark,
        created_at=NOW - timedelta(days=2),
        updated_at=NOW - timedelta(days=2),
        registered_by="operator-1",
    )


class Rig:
    """A poller wired to fakes. ``connector`` is shared across ticks so calls accumulate."""

    def __init__(
        self,
        connector: FakeConnector,
        *,
        cloud: Literal["commercial", "government"] = "commercial",
        settings: GatewayPollSettings | None = None,
        store: InMemoryGatewayStore | None = None,
    ) -> None:
        self.connector = connector
        self.api = FakeIngestApi()
        self.store = store or InMemoryGatewayStore()
        self.settings = settings or GatewayPollSettings(domain_ids=DOMAIN)
        self.factory_calls: list[tuple[str, PollBounds]] = []
        self.clock_now = NOW
        http = httpx.AsyncClient(transport=httpx.MockTransport(self.api.handler))
        self.poller = GatewayPoller(
            store=self.store,
            ingest=IngestClient(
                http,
                base_url="http://127.0.0.1:8000",
                producer_id=self.settings.producer_id,
                secret=FAKE_SECRET,
            ),
            settings=self.settings,
            customer_id=CUSTOMER,
            domain_ids=[DOMAIN],
            cloud=cloud,
            connector_factory=self._factory,
            clock=lambda: self.clock_now,
        )

    def _factory(self, cloud: str, bounds: PollBounds) -> MonitorPort:
        self.factory_calls.append((cloud, bounds))
        return self.connector

    async def current(self, reg: GatewayRegistration) -> GatewayRegistration:
        found = await self.store.get(reg.customer_id, reg.domain_id, reg.id)
        assert found is not None
        return found

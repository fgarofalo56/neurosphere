"""APIM gateway fixtures for the executor tests (PRP-34 item 3): a registered gateway with an
in-memory APIM, the worker-composed connector, swap drafts and a scripted log source."""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from neurosphere_connector import CoverageReport, FreshnessReport
from neurosphere_connector.write import WriteConnector, WriteRequest
from neurosphere_connector_apim_gateway import ApplyRecord, InMemoryApim
from neurosphere_connector_apim_gateway.swap import (
    BackendSwapTranslator,
    backend_swap_diff,
    backend_target,
)
from neurosphere_connector_azure_monitor import MonitorSource, PollResult
from neurosphere_core.actions import DraftRequest
from neurosphere_core.gateway import (
    DiagnosticsState,
    GatewayRegistration,
    InMemoryGatewayRecordStore,
    InMemoryGatewayStore,
)
from neurosphere_core.gateway.mode import evaluate_permissions
from neurosphere_workers.actions.apim import build_apim_gateway_connector

from .executor_support import CUSTOMER, DOMAIN, START

GW = "gw-" + "d" * 32
ARM_ID = (
    "/subscriptions/33333333-4444-4555-8666-777777777777/resourceGroups/rg-ai"
    "/providers/Microsoft.ApiManagement/service/apim-demo"
)
WORKSPACE = "11111111-2222-4333-8444-555555555555"
OLD_URL = "https://foundry-old.openai.azure.com/openai"
NEW_URL = "https://foundry-new.openai.azure.com/openai"
SINGLE: dict[str, Any] = {"type": "Single", "url": OLD_URL, "protocol": "http"}
POOL: dict[str, Any] = {
    "type": "Pool",
    "pool": {
        "services": [
            {"id": "/backends/gpt4o-east", "weight": 100, "priority": 1},
            {"id": "/backends/gpt41-east", "weight": 0, "priority": 1},
        ]
    },
}
CANARY_WEIGHTS = {"gpt4o-east": 90, "gpt41-east": 10}


def registration(
    *,
    mode: Literal["observe", "manage"] = "manage",
    domain: str = DOMAIN,
    cloud: Literal["commercial", "government"] = "commercial",
    gateway_logs: bool = False,
    workspace: str | None = WORKSPACE,
) -> GatewayRegistration:
    data: dict[str, Any] = {
        "id": GW,
        "customer_id": CUSTOMER,
        "domain_id": domain,
        "cloud": cloud,
        "arm_resource_id": ARM_ID,
        "name": "apim-demo",
        "tier": "standard_v2",
        "workspace_id": workspace,
        "diagnostics": DiagnosticsState(gateway_logs=gateway_logs),
        "created_at": START,
        "updated_at": START,
        "registered_by": "pn-admin",
    }
    if mode == "manage":
        data.update(
            mode="manage",
            mode_changed_by="pn-switch",
            mode_changed_at=START,
            mode_revision=1,
            preflight=evaluate_permissions(
                [{"actions": ["Microsoft.ApiManagement/service/*"]}], now=START
            ),
        )
    return GatewayRegistration.model_validate(data)


@dataclass
class ApimWorld:
    apim: InMemoryApim
    store: InMemoryGatewayStore
    records: InMemoryGatewayRecordStore[ApplyRecord]
    registration: GatewayRegistration
    connector: WriteConnector

    def statuses(self) -> list[list[str]]:
        """Status history per apply record (sync view over the in-memory store)."""
        return [
            [str(v.get("status")) for v in versions]
            for versions in self.records._versions.values()  # pyright: ignore[reportPrivateUsage]
        ]


async def apim_world(
    registered: GatewayRegistration | None = None,
    *,
    apim: InMemoryApim | None = None,
    backends: dict[str, dict[str, Any]] | None = None,
) -> ApimWorld:
    reg = registered or registration()
    apim = apim or InMemoryApim()
    for name, doc in (backends if backends is not None else {"chat-pool": POOL}).items():
        apim.seed(f"backends/{name}", copy.deepcopy(doc))
    store = InMemoryGatewayStore()
    saved = await store.create(reg)
    records: InMemoryGatewayRecordStore[ApplyRecord] = InMemoryGatewayRecordStore(ApplyRecord)
    connector = build_apim_gateway_connector(
        saved,
        apim,
        store=store,
        records=records,
        translators=[BackendSwapTranslator()],
        clock=lambda: START,
    )
    assert isinstance(connector, WriteConnector)
    return ApimWorld(apim, store, records, saved, connector)


def swap_request(
    world: ApimWorld,
    backend: str = "chat-pool",
    *,
    url: str | None = None,
    weights: dict[str, int] | None = None,
) -> WriteRequest:
    """A swap of ``backend``: a URL swap when ``url`` is given, else a weight shift."""
    base = world.apim.snapshot()[f"backends/{backend}"]
    diff = (
        backend_swap_diff(base, url=url)
        if url is not None
        else backend_swap_diff(base, weights=weights or CANARY_WEIGHTS)
    )
    return WriteRequest(
        target=backend_target("commercial", CUSTOMER, backend),
        target_version=world.apim.etag_of(f"backends/{backend}") or "",
        proposed_diff=diff,
    )


async def reviewed_draft(
    world: ApimWorld, request: WriteRequest, *, key: str = "idem-apim-swap-000001"
) -> DraftRequest:
    """The draft a maker submits after the plan preview: the diff carries the plan digest."""
    planned = await world.connector.dry_run(request)
    world.apim.calls.clear()
    return DraftRequest.model_validate(
        {
            "action_kind": "model_deployment_swap",
            "target": request.target.model_dump(mode="json"),
            "target_version": request.target_version,
            "proposed_diff": planned.planned_diff.model_dump(mode="json", by_alias=True),
            "evidence": [],
            "idempotency_key": key,
            "channel": "rest",
            "dry_run": False,
        }
    )


def poll_result(records: list[dict[str, Any]]) -> PollResult:
    return PollResult(
        records=records,
        next_watermark=START,
        partial=False,
        pages_used=1,
        page_budget=4,
        requests_made=1,
        coverage=CoverageReport(expected_sources=1, answered_sources=1, partial=False),
        freshness=FreshnessReport(),
    )


class FakeLogs:
    """Scripted gateway log source: results in order (the last repeats); records each call."""

    def __init__(self, results: Sequence[PollResult | Exception]) -> None:
        self._results = list(results)
        self.calls: list[tuple[list[MonitorSource], datetime | None]] = []

    async def poll(
        self, sources: Sequence[MonitorSource], *, watermark: datetime | None = None
    ) -> PollResult:
        self.calls.append((list(sources), watermark))
        item = self._results[min(len(self.calls) - 1, len(self._results) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


def gateway_row(backend_id: str) -> dict[str, Any]:
    return {
        "TimeGenerated": START.astimezone(UTC).isoformat(),
        "CorrelationId": "corr-1",
        "BackendId": backend_id,
        "ResponseCode": 200,
    }

"""Shared fakes for the billing_export role tests (synthetic data, no network)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from neurosphere_connector_azure_billing import (
    AzureBillingConnector,
    ExportBlobNotFoundError,
)
from neurosphere_workers.ingestion.billing_export import BillingExportPoller
from neurosphere_workers.ingestion.gateway_poll import IngestPostError

CUSTOMER = "cust-1"
SOURCE = "azure-billing-export"
DOMAIN = "commercial:cust-1:neurosphere:domain:finance"
MANIFEST_BLOB = "exports/run/manifest.json"
PART0 = "exports/run/part0.csv"
PART1 = "exports/run/part1.csv"
HEADER = "Date,CostInBillingCurrency,BillingCurrencyCode,ResourceId,MeterId\n"
R1 = "/subscriptions/s1/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/aoai"
R2 = "/subscriptions/s1/resourceGroups/rg/providers/Microsoft.Search/searchServices/search"
NOW = datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)

CSV0 = (
    HEADER
    + f"2026-10-10,1.25,USD,{R1},m-in\n"
    + f"2026-10-10,0.75,USD,{R1},m-in\n"  # same day/resource/meter: rolled to 2.00
    + f"2026-10-10,3.10,USD,{R2},m-sku\n"
    + f"2026-10-11,4.00,USD,{R1},m-in\n"
)
CSV1 = HEADER + f"2026-10-11,,USD,{R2},m-sku\n"  # blank cost: unknown, never posted as 0


def manifest(blobs: Sequence[str] = (PART0, PART1), *, rows: int | None = 5, **extra: Any) -> bytes:
    doc: dict[str, Any] = {
        "blobCount": len(blobs),
        "deliveryConfig": {"fileFormat": "Csv", "compressionMode": "None"},
        "blobs": [{"blobName": b} for b in blobs],
        **extra,
    }
    if rows is not None:
        doc["dataRowCount"] = rows
    return json.dumps(doc).encode()


class FakeBlobSource:
    def __init__(self, manifest_bytes: bytes, blobs: Mapping[str, bytes]) -> None:
        self.manifest = manifest_bytes
        self.blobs = dict(blobs)
        self.error: Exception | None = None

    async def read_manifest(self) -> bytes:
        if self.error is not None:
            raise self.error
        return self.manifest

    async def read_blob(self, name: str) -> bytes:
        if name not in self.blobs:
            raise ExportBlobNotFoundError(name)
        return self.blobs[name]


def default_source() -> FakeBlobSource:
    return FakeBlobSource(manifest(), {PART0: CSV0.encode(), PART1: CSV1.encode()})


class FakeIngest:
    """Stands in for the ingest edge: records posted CloudEvents; failures are injectable."""

    def __init__(self) -> None:
        self.batches: list[list[dict[str, Any]]] = []
        self.fail_status: int | None = None
        self.accept_limit: int | None = None

    @property
    def events(self) -> list[dict[str, Any]]:
        return [e for batch in self.batches for e in batch]

    async def post(self, events: Sequence[Mapping[str, Any]]) -> int:
        if self.fail_status is not None:
            raise IngestPostError(self.fail_status)
        self.batches.append([dict(e) for e in events])
        if self.accept_limit is not None:
            return min(len(events), self.accept_limit)
        return len(events)


def make_poller(
    source: FakeBlobSource, ingest: Any, *, batch_size: int = 100
) -> BillingExportPoller:
    return BillingExportPoller(
        reader=AzureBillingConnector(source=source, basis="actual", amount_kind="invoiced"),
        ingest=ingest,
        customer_id=CUSTOMER,
        cloud="commercial",
        source_id=SOURCE,
        domain_id=DOMAIN,
        batch_size=batch_size,
        clock=lambda: NOW,
    )

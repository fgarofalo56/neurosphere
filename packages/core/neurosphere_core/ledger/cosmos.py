"""Cosmos NoSQL ledger store (partition key ``/customer_id``).

The container client is INJECTED (created in wiring through ``neurosphere_core.clients``). One
container holds entries (``doc_type="entry"``) and allocation records (``"allocation"``), both
with deterministic ids. Entry read-modify-write uses the ETag; a precondition failure returns
False and ``CostLedger`` retries a bounded number of times. Timestamps are stored as fixed-width
UTC strings so SQL range comparisons are lexicographically correct. SDK failures are mapped to
the error taxonomy by ``translating()``. Emulator-backed tests are PRP-07 item 6.
"""

from __future__ import annotations

from typing import Any

from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)

from neurosphere_core.clients import translating
from neurosphere_core.ledger.models import AllocationRecord, LedgerEntry, format_time
from neurosphere_core.ledger.store import VersionedEntry
from neurosphere_core.ledger.totals import TimeWindow


def _strip_system(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if not k.startswith("_")}


class CosmosLedgerStore:
    def __init__(self, container: Any) -> None:
        self._container = container

    async def read_entry(self, customer_id: str, entry_id: str) -> VersionedEntry | None:
        with translating():
            try:
                doc = await self._container.read_item(item=entry_id, partition_key=customer_id)
            except CosmosResourceNotFoundError:
                return None
        if doc.get("doc_type") != "entry":
            return None
        return VersionedEntry(LedgerEntry.model_validate(_strip_system(doc)), doc["_etag"])

    async def write_entry(self, entry: LedgerEntry, expected_version: str | None) -> bool:
        body = entry.model_dump(mode="json")
        with translating():
            if expected_version is None:
                try:
                    await self._container.create_item(body=body)
                except CosmosResourceExistsError:
                    return False
                return True
            try:
                await self._container.replace_item(
                    item=entry.id,
                    body=body,
                    etag=expected_version,
                    match_condition=MatchConditions.IfNotModified,
                )
            except (CosmosAccessConditionFailedError, CosmosResourceNotFoundError):
                return False
        return True

    async def list_entries(self, customer_id: str, window: TimeWindow) -> list[LedgerEntry]:
        query = (
            "SELECT * FROM c WHERE c.customer_id = @customer AND c.doc_type = 'entry' "
            "AND c.occurred_at >= @start AND c.occurred_at < @end"
        )
        parameters = [
            {"name": "@customer", "value": customer_id},
            {"name": "@start", "value": format_time(window.start)},
            {"name": "@end", "value": format_time(window.end)},
        ]
        entries: list[LedgerEntry] = []
        with translating():
            async for doc in self._container.query_items(
                query=query, parameters=parameters, partition_key=customer_id
            ):
                entries.append(LedgerEntry.model_validate(_strip_system(doc)))
        return entries

    async def put_allocation(self, record: AllocationRecord) -> None:
        with translating():
            try:
                await self._container.create_item(body=record.model_dump(mode="json"))
            except CosmosResourceExistsError:
                return  # same observation, same id: already stored

    async def list_allocations(self, customer_id: str) -> list[AllocationRecord]:
        query = "SELECT * FROM c WHERE c.customer_id = @customer AND c.doc_type = 'allocation'"
        parameters = [{"name": "@customer", "value": customer_id}]
        records: list[AllocationRecord] = []
        with translating():
            async for doc in self._container.query_items(
                query=query, parameters=parameters, partition_key=customer_id
            ):
                records.append(AllocationRecord.model_validate(_strip_system(doc)))
        return records

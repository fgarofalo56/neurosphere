"""Cosmos (``azure.cosmos.aio``) implementation of ``AggregateStore``.

One container, partition key ``/customer_id`` (every read and write is single-partition). Three
document types share it, told apart by ``doc_type``: ``aggregate``, ``contribution`` and
``status``. Build the client with ``neurosphere_core.clients.create_cosmos_client`` and pass the
container in; no credentials are handled here. Government and Commercial use separate accounts
(separate endpoints), so nothing here ever bridges clouds.

Emulator notes (PRP-14 clarification 9): the vNext emulator has no RU accounting and no
range/composite indexes, so queries use equality filters plus single-field string range filters
and sort client-side; none of this proves production index or RU behavior (gate G12 stays open).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Final

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from neurosphere_core.aggregates.models import (
    AGGREGATE_ADAPTER,
    AggregateDoc,
    AggregateStatus,
    AggregateWindow,
    Contribution,
    Grain,
    Metric,
    QueryResult,
    format_bucket,
)
from neurosphere_core.aggregates.store import (
    bounded_keys,
    pick_latest,
    pick_newest,
    select_series,
    validate_query,
    validate_subject_window,
)
from neurosphere_core.aggregates.subject import KEYS_PER_QUERY, SubjectKind, SubjectLookup
from neurosphere_core.clients import translating

if TYPE_CHECKING:
    from azure.cosmos.aio import ContainerProxy

__all__ = ["PARTITION_KEY_PATH", "CosmosAggregateStore"]

PARTITION_KEY_PATH: Final = "/customer_id"
_STATUS_ID: Final = "status"
_SYSTEM_PROPERTIES = ("_rid", "_self", "_etag", "_attachments", "_ts")


def _clean(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if k not in _SYSTEM_PROPERTIES}


class CosmosAggregateStore:
    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    async def _query(
        self, query: str, parameters: list[dict[str, Any]], customer_id: str
    ) -> list[dict[str, Any]]:
        with translating():
            return [
                _clean(dict(row))
                async for row in self._container.query_items(
                    query=query, parameters=parameters, partition_key=customer_id
                )
            ]

    # ---- read side

    async def query(
        self,
        customer_id: str,
        domain_id: str,
        metric: Metric,
        grain: Grain,
        window: AggregateWindow,
        *,
        max_series: int,
        max_points: int,
    ) -> QueryResult:
        validate_query(grain, window, max_series, max_points)
        rows = await self._query(
            "SELECT * FROM c WHERE c.customer_id = @customer AND c.doc_type = 'aggregate' "
            "AND c.domain_id = @domain AND c.metric = @metric AND c.grain = @grain "
            "AND c.bucket_start >= @start AND c.bucket_start < @end",
            [
                {"name": "@customer", "value": customer_id},
                {"name": "@domain", "value": domain_id},
                {"name": "@metric", "value": metric},
                {"name": "@grain", "value": grain},
                {"name": "@start", "value": format_bucket(window.start)},
                {"name": "@end", "value": format_bucket(window.end)},
            ],
            customer_id,
        )
        docs: list[AggregateDoc] = [AGGREGATE_ADAPTER.validate_python(row) for row in rows]
        return select_series(docs, max_series, max_points)

    async def _subject_rows(
        self,
        customer_id: str,
        domain_id: str,
        window: AggregateWindow,
        extra: str,
        extra_params: list[dict[str, Any]],
    ) -> list[AggregateDoc]:
        rows = await self._query(
            "SELECT * FROM c WHERE c.customer_id = @customer AND c.doc_type = 'aggregate' "  # noqa: S608
            "AND c.domain_id = @domain AND c.metric = 'subject' AND c.grain = 'hour' "
            "AND c.bucket_start >= @start AND c.bucket_start < @end" + extra,  # extra: only @params
            [
                {"name": "@customer", "value": customer_id},
                {"name": "@domain", "value": domain_id},
                {"name": "@start", "value": format_bucket(window.start)},
                {"name": "@end", "value": format_bucket(window.end)},
                *extra_params,
            ],
            customer_id,
        )
        return [AGGREGATE_ADAPTER.validate_python(row) for row in rows]

    async def latest_subject_points(
        self,
        customer_id: str,
        domain_id: str,
        kind: SubjectKind,
        keys: Sequence[str],
        window: AggregateWindow,
    ) -> SubjectLookup:
        validate_subject_window(window)
        kept, truncated = bounded_keys(keys)
        docs: list[AggregateDoc] = []
        for offset in range(0, len(kept), KEYS_PER_QUERY):
            chunk = kept[offset : offset + KEYS_PER_QUERY]
            names = [f"@k{i}" for i in range(len(chunk))]
            docs.extend(
                await self._subject_rows(
                    customer_id,
                    domain_id,
                    window,
                    " AND c.subject_kind = @kind AND c.series_key IN (" + ", ".join(names) + ")",
                    [
                        {"name": "@kind", "value": kind},
                        *({"name": n, "value": k} for n, k in zip(names, chunk, strict=True)),
                    ],
                )
            )
        return pick_latest(docs, kept, truncated)

    async def newest_subject_points(
        self, customer_id: str, domain_id: str, window: AggregateWindow, limit: int
    ) -> SubjectLookup:
        validate_subject_window(window)
        # No composite index on the emulator: read the window's subject documents (bounded by
        # MAX_SUBJECT_SERIES_PER_BUCKET per bucket) and rank client-side.
        return pick_newest(await self._subject_rows(customer_id, domain_id, window, "", []), limit)

    async def status(self, customer_id: str) -> AggregateStatus | None:
        with translating():
            try:
                item = await self._container.read_item(item=_STATUS_ID, partition_key=customer_id)
            except CosmosResourceNotFoundError:
                return None
        return AggregateStatus.model_validate(_clean(dict(item)))

    # ---- write side

    async def get_contribution(self, customer_id: str, contribution_id: str) -> Contribution | None:
        with translating():
            try:
                item = await self._container.read_item(
                    item=contribution_id, partition_key=customer_id
                )
            except CosmosResourceNotFoundError:
                return None
        return Contribution.model_validate(_clean(dict(item)))

    async def put_contribution(self, contribution: Contribution) -> None:
        with translating():
            await self._container.upsert_item(body=contribution.model_dump(mode="json"))

    async def delete_contribution(self, customer_id: str, contribution_id: str) -> None:
        with translating():
            try:
                await self._container.delete_item(item=contribution_id, partition_key=customer_id)
            except CosmosResourceNotFoundError:
                return

    async def list_contributions(
        self, customer_id: str, domain_id: str, day: date
    ) -> list[Contribution]:
        start = f"{day.isoformat()}T00:00:00"
        end = f"{day.isoformat()}T23:59:59.999999Z"
        rows = await self._query(
            "SELECT * FROM c WHERE c.customer_id = @customer AND c.doc_type = 'contribution' "
            "AND c.domain_id = @domain AND c.occurred_at >= @start AND c.occurred_at <= @end",
            [
                {"name": "@customer", "value": customer_id},
                {"name": "@domain", "value": domain_id},
                {"name": "@start", "value": start},
                {"name": "@end", "value": end},
            ],
            customer_id,
        )
        found = [Contribution.model_validate(row) for row in rows]
        return sorted((c for c in found if c.occurred.date() == day), key=lambda c: c.id)

    async def replace_bucket(
        self,
        customer_id: str,
        domain_id: str,
        grain: Grain,
        start: str,
        docs: Sequence[AggregateDoc],
    ) -> None:
        existing = await self._query(
            "SELECT * FROM c WHERE c.customer_id = @customer AND c.doc_type = 'aggregate' "
            "AND c.domain_id = @domain AND c.grain = @grain AND c.bucket_start = @start",
            [
                {"name": "@customer", "value": customer_id},
                {"name": "@domain", "value": domain_id},
                {"name": "@grain", "value": grain},
                {"name": "@start", "value": start},
            ],
            customer_id,
        )
        keep = {doc.id for doc in docs}
        stored = {str(row["id"]): row for row in existing}
        with translating():
            for doc in docs:
                body = doc.model_dump(mode="json")
                if stored.get(doc.id) == body:
                    continue  # unchanged: a one-event rebuild writes only the changed documents
                await self._container.upsert_item(body=body)
            for row in existing:
                if row["id"] not in keep:
                    await self._delete(customer_id, str(row["id"]))

    async def _delete(self, customer_id: str, doc_id: str) -> None:
        try:
            await self._container.delete_item(item=doc_id, partition_key=customer_id)
        except CosmosResourceNotFoundError:
            return

    async def put_status(self, status: AggregateStatus) -> None:
        with translating():
            await self._container.upsert_item(body=status.model_dump(mode="json"))

    async def prune(self, customer_id: str, *, day_cutoff: date, hour_cutoff: datetime) -> int:
        rows = await self._query(
            "SELECT c.id, c.doc_type, c.grain, c.bucket_start, c.occurred_at FROM c "
            "WHERE c.customer_id = @customer AND c.doc_type != 'status'",
            [{"name": "@customer", "value": customer_id}],
            customer_id,
        )
        day_limit, hour_limit = day_cutoff.isoformat(), format_bucket(hour_cutoff)
        stale: list[str] = []
        for row in rows:
            if row["doc_type"] == "contribution":
                is_stale = str(row["occurred_at"])[:10] < day_limit
            elif row["grain"] == "day":
                is_stale = str(row["bucket_start"])[:10] < day_limit
            else:
                is_stale = str(row["bucket_start"]) < hour_limit
            if is_stale:
                stale.append(str(row["id"]))
        with translating():
            for doc_id in stale:
                await self._delete(customer_id, doc_id)
        return len(stale)

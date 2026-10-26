"""Cosmos-backed ``AcceptedMarkerStore`` and ``WatermarkStore`` (partition key ``/customer_id``).

Both take an async ``ContainerProxy`` created from ``neurosphere_core.clients.create_cosmos_client``
(the only place SDK clients are built). Unit tests use a fake container; the emulator tests are
PRP-07 item 6. SDK failures are translated to the error taxonomy so the pipeline's retry logic
sees ``DependencyTransientError``.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Final

from azure.core import MatchConditions
from azure.cosmos import PartitionKey
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_core.clients import translating
from neurosphere_core.errors import DependencyTransientError

from neurosphere_workers.ingestion.models import EventKey, format_timestamp, parse_timestamp

PARTITION_KEY_PATH: Final = "/customer_id"
_MAX_ADVANCE_ATTEMPTS: Final = 5


async def ensure_containers(database: Any, *container_names: str) -> None:
    """Create the containers if missing (local/emulator bootstrap; production uses Bicep).

    A 409 "already exists" is success: on a fresh emulator another role (the API's
    ``ensure_local_containers``) can create the container between the existence check and the
    create call inside ``create_container_if_not_exists``.
    """
    for name in container_names:
        try:
            await database.create_container_if_not_exists(
                id=name, partition_key=PartitionKey(path=PARTITION_KEY_PATH)
            )
        except CosmosResourceExistsError:
            continue


class CosmosAcceptedMarkerStore:
    """One marker document per event, id = deterministic ``EventKey.doc_id``."""

    def __init__(self, container: Any, *, clock: Any = None) -> None:
        self._container = container
        self._clock = clock or (lambda: datetime.now(UTC))

    async def is_accepted(self, key: EventKey) -> bool:
        with translating():
            try:
                await self._container.read_item(item=key.doc_id, partition_key=key.customer_id)
            except CosmosResourceNotFoundError:
                return False
        return True

    async def mark_accepted(self, key: EventKey) -> bool:
        body = {
            "id": key.doc_id,
            "customer_id": key.customer_id,
            "source_id": key.source_id,
            "event_id": key.event_id,
            "accepted_at": format_timestamp(self._clock()),
        }
        with translating():
            try:
                await self._container.create_item(body=body)
            except CosmosResourceExistsError:
                return False  # conflict means already accepted
        return True


def _watermark_id(source_id: str) -> str:
    # Document ids may not contain '/', '\\', '?' or '#': hash the source id.
    return "wm-" + hashlib.sha256(source_id.encode()).hexdigest()[:40]


class CosmosWatermarkStore:
    """One document per (customer, source) holding the newest event time; monotonic."""

    def __init__(self, container: Any) -> None:
        self._container = container

    async def get(self, customer_id: str, source_id: str) -> datetime | None:
        with translating():
            try:
                item = await self._container.read_item(
                    item=_watermark_id(source_id), partition_key=customer_id
                )
            except CosmosResourceNotFoundError:
                return None
        return parse_timestamp(item["max_event_time"])

    async def advance(self, customer_id: str, source_id: str, event_time: datetime) -> datetime:
        doc_id = _watermark_id(source_id)
        body = {
            "id": doc_id,
            "customer_id": customer_id,
            "source_id": source_id,
            "max_event_time": format_timestamp(event_time),
        }
        with translating():
            for _ in range(_MAX_ADVANCE_ATTEMPTS):
                try:
                    item = await self._container.read_item(item=doc_id, partition_key=customer_id)
                except CosmosResourceNotFoundError:
                    try:
                        await self._container.create_item(body=body)
                    except CosmosResourceExistsError:
                        continue  # raced with another writer: re-read
                    return event_time
                current = parse_timestamp(item["max_event_time"])
                if current >= event_time:
                    return current
                try:
                    await self._container.replace_item(
                        item=doc_id,
                        body=body,
                        etag=item["_etag"],
                        match_condition=MatchConditions.IfNotModified,
                    )
                except CosmosAccessConditionFailedError:
                    continue
                return event_time
        raise DependencyTransientError("watermark update contention", reason="watermark_contention")

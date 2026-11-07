"""Checkpoint abstraction (PRP-05 C9).

Rule: a checkpoint advances only after the batch it covers was durably accepted or
quarantined. The blob-backed implementation arrives with PRP-07; this module owns only the
protocol, an in-memory implementation for tests, and the Cosmos-backed store the supervised
roles use (the blob-backed one is the Event Hubs consumer's own).
"""

from __future__ import annotations

import hashlib
from typing import Any, Protocol, runtime_checkable

from azure.cosmos.exceptions import CosmosResourceNotFoundError
from neurosphere_core.clients import translating


@runtime_checkable
class CheckpointStore(Protocol):
    """Per-partition-key checkpoint persistence."""

    async def get(self, partition_key: str) -> str | None:
        """Return the last committed checkpoint, or ``None`` if none exists."""
        raise NotImplementedError

    async def commit(self, partition_key: str, checkpoint: str) -> None:
        """Durably record ``checkpoint``; must not return before it is durable."""
        raise NotImplementedError


def _runtime_checkpoint_id(partition_key: str) -> str:
    # "rt-" keeps these documents apart from the outbox sink checkpoints ("ckpt-...") that share
    # the container.
    return "rt-" + hashlib.sha256(partition_key.encode()).hexdigest()[:40]


class CosmosRuntimeCheckpointStore:
    """Durable :class:`CheckpointStore` for the supervised roles (one customer's partition).

    Reuses the existing ``outbox-checkpoints`` container (partition key ``/customer_id``), so no
    new container or Bicep change is needed. ``commit`` returns only after Cosmos accepted the
    upsert; a failed write raises and the runner's checkpoint stays at its prior value.
    """

    def __init__(self, container: Any, *, customer_id: str) -> None:
        self._container = container
        self._customer = customer_id

    async def get(self, partition_key: str) -> str | None:
        with translating():
            try:
                doc = await self._container.read_item(
                    item=_runtime_checkpoint_id(partition_key), partition_key=self._customer
                )
            except CosmosResourceNotFoundError:
                return None
        return str(doc["checkpoint"])

    async def commit(self, partition_key: str, checkpoint: str) -> None:
        body = {
            "id": _runtime_checkpoint_id(partition_key),
            "customer_id": self._customer,
            "kind": "runtime_checkpoint",
            "worker": partition_key,
            "checkpoint": checkpoint,
        }
        with translating():
            await self._container.upsert_item(body=body)


class InMemoryCheckpointStore:
    """Process-local store; instance state only (no module globals)."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self.commit_count = 0

    async def get(self, partition_key: str) -> str | None:
        return self._values.get(partition_key)

    async def commit(self, partition_key: str, checkpoint: str) -> None:
        self._values[partition_key] = checkpoint
        self.commit_count += 1

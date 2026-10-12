"""Checkpoint abstraction (PRP-05 C9).

Rule: a checkpoint advances only after the batch it covers was durably accepted or
quarantined. The blob-backed implementation arrives with PRP-07; this module owns only the
protocol and an in-memory implementation for tests and local idling.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CheckpointStore(Protocol):
    """Per-partition-key checkpoint persistence."""

    async def get(self, partition_key: str) -> str | None:
        """Return the last committed checkpoint, or ``None`` if none exists."""
        raise NotImplementedError

    async def commit(self, partition_key: str, checkpoint: str) -> None:
        """Durably record ``checkpoint``; must not return before it is durable."""
        raise NotImplementedError


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

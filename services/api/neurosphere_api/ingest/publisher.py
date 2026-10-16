"""Hub publishers. The edge publishes only through this protocol."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from azure.eventhub import EventData
from neurosphere_core.clients import translating
from neurosphere_core.payload import HubMessage


class Publisher(Protocol):
    async def publish(self, messages: Sequence[HubMessage]) -> None: ...


class EventHubsPublisher:
    """Sends messages through an async ``EventHubProducerClient``.

    Build the producer with ``neurosphere_core.clients.create_eventhub_producer`` (the only
    place SDK clients are constructed) and register it with the caller's ``ClientLifetime``.
    Messages are grouped by partition key so each source keeps its order; SDK failures are
    translated to ``DependencyTransientError`` (or other taxonomy errors).
    """

    def __init__(self, producer: Any) -> None:
        self._producer = producer

    async def publish(self, messages: Sequence[HubMessage]) -> None:
        by_key: dict[str, list[HubMessage]] = {}
        for msg in messages:
            by_key.setdefault(msg.partition_key(), []).append(msg)
        with translating():
            for key, group in by_key.items():
                batch = await self._producer.create_batch(partition_key=key)
                for msg in group:
                    event = EventData(msg.to_bytes())
                    try:
                        batch.add(event)
                    except ValueError:  # batch full: flush and start a new one
                        await self._producer.send_batch(batch)
                        batch = await self._producer.create_batch(partition_key=key)
                        batch.add(event)
                if len(batch) > 0:
                    await self._producer.send_batch(batch)


class InMemoryPublisher:
    """Test double that records what would have been published."""

    def __init__(self) -> None:
        self.messages: list[HubMessage] = []

    async def publish(self, messages: Sequence[HubMessage]) -> None:
        self.messages.extend(messages)

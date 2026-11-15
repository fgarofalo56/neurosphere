"""Event Hubs SIEM sink (PRP-40 item 1, ASSUMPTION A2).

One already-redacted event per audit append, sent as a single-event batch through an injected
async producer. The composition (``runtime/builders/data.py``) builds the producer with
``neurosphere_core.clients.create_eventhub_producer``: managed identity through
``DefaultAzureCredential`` outside ``NS_ENV=local``, never a key or connection string there.
Microsoft Sentinel, Splunk and other SIEMs read from the hub; the API identity needs the
"Azure Event Hubs Data Sender" role on the hub.

Hosts come only from the deployment's :class:`~neurosphere_core.cloud.CloudProfile`
(:func:`resolve_namespace`): a bare namespace name gets the profile's suffix
(``.servicebus.usgovcloudapi.net`` on Government), and a fully qualified host from another cloud
is refused, so audit events are never sent across the Commercial/Government boundary.

Failures propagate to :class:`~neurosphere_core.audit.siem.SiemExporter`, which counts them and
never fails the append. Nothing here logs the host, the hub name or the payload.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any, Final, Protocol

from azure.eventhub import EventData

from neurosphere_core.cloud import CloudProfile

__all__ = [
    "DEFAULT_SEND_TIMEOUT_SECONDS",
    "EventBatch",
    "EventHubsProducer",
    "EventHubsSiemSink",
    "resolve_namespace",
]

DEFAULT_SEND_TIMEOUT_SECONDS: Final = 10.0
_CONTENT_TYPE: Final = "application/json"


class EventBatch(Protocol):
    def add(self, event_data: EventData) -> None: ...


class EventHubsProducer(Protocol):
    """The slice of ``azure.eventhub.aio.EventHubProducerClient`` this sink uses."""

    async def create_batch(self) -> Any: ...

    async def send_batch(self, event_data_batch: Any) -> None: ...

    async def close(self) -> None: ...


def resolve_namespace(profile: CloudProfile, value: str) -> str:
    """The namespace NAME for ``value`` (a bare name or a host in ``profile``'s cloud).

    A host whose suffix is not the profile's Event Hubs suffix (for example a Commercial
    ``.servicebus.windows.net`` host on a Government profile) raises ``ValueError``: no
    cross-cloud send. The name is validated by the profile's account-name rule.
    """
    candidate = value.strip().lower()
    if candidate.startswith(("amqps://", "https://", "sb://")):
        candidate = candidate.split("://", 1)[1]
    candidate = candidate.rstrip("/")
    if "." in candidate:
        suffix = profile.eventhubs_suffix
        if not candidate.endswith(suffix):
            raise ValueError("event hubs namespace host is not in this deployment's cloud")
        candidate = candidate[: -len(suffix)]
    # eventhubs_fqdn validates the name and builds the host from the profile only.
    profile.eventhubs_fqdn(candidate)
    return candidate


def _body(event: Mapping[str, Any]) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class EventHubsSiemSink:
    """``SiemSink`` that sends each event as its own batch to one hub."""

    def __init__(
        self,
        producer: EventHubsProducer,
        *,
        name: str = "eventhubs",
        send_timeout_seconds: float = DEFAULT_SEND_TIMEOUT_SECONDS,
    ) -> None:
        if send_timeout_seconds <= 0:
            raise ValueError("send_timeout_seconds must be positive")
        self.name = name
        self._producer = producer
        self._timeout = send_timeout_seconds

    async def emit(self, event: Mapping[str, Any]) -> None:
        data = EventData(_body(event))
        data.content_type = _CONTENT_TYPE
        async with asyncio.timeout(self._timeout):
            batch = await self._producer.create_batch()
            batch.add(data)
            await self._producer.send_batch(batch)

    async def close(self) -> None:
        await self._producer.close()

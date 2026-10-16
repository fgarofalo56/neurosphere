"""Opt-in construction of the ingest edge from settings (called from ``main.create``).

``NS_INGEST_PRODUCERS_FILE`` unset: nothing is configured and every ingest route keeps failing
closed with 503 (``ingest_not_configured``). Set: the producer registry (hashes only), the Event
Hubs publisher and the ``IngestService`` are built and attached with ``configure_ingest``.

The publisher's client is owned by a ``ClientLifetime`` that is closed when the application shuts
down (the lifespan context is wrapped; ``app.py`` has no shutdown hook of its own).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from neurosphere_core.clients import ClientLifetime, create_eventhub_producer
from neurosphere_core.cloud import Settings

from neurosphere_api.ingest.auth import StaticProducerRegistry
from neurosphere_api.ingest.publisher import EventHubsPublisher
from neurosphere_api.ingest.router import build_service, configure_ingest
from neurosphere_api.ingest.settings import IngestSettings


def _close_on_shutdown(app: FastAPI, lifetime: ClientLifetime) -> None:
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[Any]:
        async with original(application) as state:
            try:
                yield state
            finally:
                await lifetime.aclose()

    app.router.lifespan_context = lifespan


def configure_ingest_from_settings(
    app: FastAPI, settings: Settings, ingest_settings: IngestSettings | None = None
) -> bool:
    """Wire the ingest edge when a producers file is configured. True when configured."""
    conf = ingest_settings or IngestSettings()
    if conf.producers_file is None:
        return False
    registry = StaticProducerRegistry.from_file(conf.producers_file)  # fail fast on a bad file
    lifetime = ClientLifetime()
    producer = create_eventhub_producer(
        settings,
        lifetime=lifetime,
        eventhub_name=conf.eventhub_name,
        namespace=conf.eventhubs_namespace,
    )
    service = build_service(settings, conf, EventHubsPublisher(producer), registry=registry)
    configure_ingest(app, service)
    app.state.ingest_lifetime = lifetime
    _close_on_shutdown(app, lifetime)
    return True

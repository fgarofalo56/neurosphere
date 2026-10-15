"""``python -m neurosphere_workers.ingestion``: run the normalizer consumer until SIGTERM/SIGINT.

Fails closed until the quarantine, archive and ledger sinks (PRP-07 items 3-5) exist: wiring a
discarding stand-in would let the checkpoint advance over lost data (PRP-07 C4). Item 6 (or the
integrator) replaces ``build_sinks`` once those packages land.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import NamedTuple

from neurosphere_core.clients import (
    ClientLifetime,
    create_checkpoint_store,
    create_cosmos_client,
    create_eventhub_consumer,
)
from neurosphere_core.cloud import CloudName, load_settings
from neurosphere_core.errors import CapabilityUnavailableError

from neurosphere_workers.ingestion.consumer import IngestionConsumer
from neurosphere_workers.ingestion.cosmos_stores import (
    CosmosAcceptedMarkerStore,
    CosmosWatermarkStore,
    ensure_containers,
)
from neurosphere_workers.ingestion.pipeline import PipelineDeps
from neurosphere_workers.ingestion.protocols import ArchiveSink, LedgerSink, QuarantineSink
from neurosphere_workers.ingestion.settings import IngestionSettings


class Sinks(NamedTuple):
    quarantine: QuarantineSink
    archive: ArchiveSink
    ledger: LedgerSink


def build_sinks() -> Sinks:
    raise CapabilityUnavailableError(
        "sinks_not_wired", "quarantine, archive and ledger sinks arrive with PRP-07 items 3-5"
    )


async def _amain() -> int:
    settings = load_settings()
    ingestion = IngestionSettings()
    sinks = build_sinks()
    async with ClientLifetime() as lifetime:
        checkpoint_store = create_checkpoint_store(
            settings,
            lifetime=lifetime,
            container=ingestion.checkpoint_container,
            account=ingestion.storage_account,
        )
        client = create_eventhub_consumer(
            settings,
            lifetime=lifetime,
            eventhub_name=ingestion.eventhub_name,
            consumer_group=ingestion.consumer_group,
            namespace=ingestion.eventhubs_namespace,
            checkpoint_store=checkpoint_store,
        )
        cosmos = create_cosmos_client(settings, lifetime=lifetime, account=ingestion.cosmos_account)
        database = cosmos.get_database_client(ingestion.cosmos_database)
        if settings.env == "local":
            await ensure_containers(
                database, ingestion.markers_container, ingestion.watermarks_container
            )
        deps = PipelineDeps(
            quarantine=sinks.quarantine,
            archive=sinks.archive,
            ledger=sinks.ledger,
            markers=CosmosAcceptedMarkerStore(
                database.get_container_client(ingestion.markers_container)
            ),
            watermarks=CosmosWatermarkStore(
                database.get_container_client(ingestion.watermarks_container)
            ),
            cloud=(settings.cloud or CloudName.COMMERCIAL).value,
        )
        return await IngestionConsumer(client, deps, ingestion).run()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())

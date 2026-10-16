"""``python -m neurosphere_workers.ingestion``: run the normalizer consumer until SIGTERM/SIGINT.

Sinks and stores are built from settings by ``wiring.build_pipeline_deps`` (the same path the
quarantine replay CLI uses). Infrastructure is auto-created only when NS_ENV=local; elsewhere a
missing container is a startup error.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from neurosphere_core.clients import (
    ClientLifetime,
    create_checkpoint_store,
    create_eventhub_consumer,
)
from neurosphere_core.cloud import load_settings

from neurosphere_workers.ingestion.consumer import IngestionConsumer
from neurosphere_workers.ingestion.settings import IngestionSettings
from neurosphere_workers.ingestion.wiring import build_pipeline_deps


async def _amain() -> int:
    settings = load_settings()
    ingestion = IngestionSettings()
    async with ClientLifetime() as lifetime:
        deps = await build_pipeline_deps(settings, lifetime=lifetime, ingestion=ingestion)
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
        return await IngestionConsumer(client, deps, ingestion).run()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())

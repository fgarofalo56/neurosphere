"""``python -m neurosphere_workers.runtime``: health endpoint plus idle loop until shutdown."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from neurosphere_workers.runtime.checkpoint import InMemoryCheckpointStore
from neurosphere_workers.runtime.health import HealthServer, HealthStatus
from neurosphere_workers.runtime.worker import IdleWorker, WorkerRunner


async def _amain() -> int:
    host = os.environ.get("NS_WORKER_HEALTH_HOST", "127.0.0.1")
    port = int(os.environ.get("NS_WORKER_HEALTH_PORT", "8090"))
    holder: list[WorkerRunner] = []

    def _status() -> HealthStatus:
        return holder[0].status if holder else "ok"

    runner = WorkerRunner(
        IdleWorker(), InMemoryCheckpointStore(), health=HealthServer(_status, host, port)
    )
    holder.append(runner)
    return await runner.run()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())

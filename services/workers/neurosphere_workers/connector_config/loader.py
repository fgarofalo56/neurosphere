"""Read the stored connector config of one kind for the worker's customer (PRP-42).

The read is bounded by a timeout. A store that is unreachable, slow, throttled or holds a row that
fails validation yields ``None`` and ONE structured log line with the reason code
``connector_config_store_unavailable``; it is never a startup failure (the role then behaves as it
does without a store). Nothing about the store error, the document or any setting value is logged.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Final

from neurosphere_contracts.admin.v1.connector_config import ConnectorConfig
from neurosphere_core.admin import AdminConfigRepository, CosmosAdminConfigRepository
from neurosphere_core.clients import ClientLifetime, create_cosmos_client

if TYPE_CHECKING:
    from neurosphere_workers.runtime.factories import RuntimeConfig

__all__ = ["STORE_UNAVAILABLE", "load_stored_config", "open_repository"]

STORE_UNAVAILABLE: Final = "connector_config_store_unavailable"
_log = logging.getLogger("neurosphere_workers.connector_config")


def open_repository(cfg: RuntimeConfig, lifetime: ClientLifetime) -> AdminConfigRepository:
    """The ``admin_config`` repository on a Cosmos client of this deployment (raises if none)."""
    client = create_cosmos_client(cfg.settings, lifetime=lifetime, account=cfg.store.cosmos_account)
    return CosmosAdminConfigRepository.from_client(
        client,
        database=cfg.store.database,
        cloud=cfg.cloud,  # type: ignore[arg-type]
    )


def log_store_unavailable(kind: str) -> None:
    _log.warning(
        "connector config store unavailable; using the environment",
        extra={
            "event": "worker.connector_config_store_unavailable",
            "reason": STORE_UNAVAILABLE,
            "connector_kind": kind,
        },
    )


async def load_stored_config(
    repository: AdminConfigRepository, customer_id: str, kind: str, *, timeout_seconds: float
) -> ConnectorConfig | None:
    """The one active stored config of ``kind``; ``None`` when none exists or the read failed."""
    try:
        documents = await asyncio.wait_for(
            repository.list_by_kind(customer_id, "connector_config"), timeout_seconds
        )
    except Exception:
        log_store_unavailable(kind)
        return None
    for document in documents:
        body = document.body
        if isinstance(body, ConnectorConfig) and body.connector_kind == kind:
            return body
    return None

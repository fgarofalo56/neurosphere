"""The ingestion ledger price table from stored price snapshots plus the file table (item 5)."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any, Final

from azure.cosmos import CosmosClient as SyncCosmosClient
from azure.identity import DefaultAzureCredential as SyncDefaultAzureCredential
from neurosphere_core.admin.platform import merge_price_tables
from neurosphere_core.clients.factories import ENV_COSMOS_ENDPOINT, ENV_COSMOS_KEY
from neurosphere_core.ledger import PriceTable
from neurosphere_core.pricing.cosmos_store import CosmosPriceSnapshotStore
from neurosphere_core.pricing.models import PriceSnapshot

from neurosphere_workers.ingestion.wiring import LedgerSettings, load_price_table

if TYPE_CHECKING:
    from neurosphere_workers.runtime.factories import RuntimeConfig

__all__ = ["PRICE_STORE_UNAVAILABLE", "ledger_price_table", "list_stored_snapshots"]

PRICE_STORE_UNAVAILABLE: Final = "price_snapshot_store_unavailable"
_LOCAL_COSMOS_DEFAULT: Final = "https://127.0.0.1:8081"
_TIMEOUT_SECONDS: Final = 15.0
_log = logging.getLogger("neurosphere_workers.admin_platform")


def _sync_client(cfg: RuntimeConfig) -> Any:
    """The sync client the price snapshot protocol requires (always used off the event loop)."""
    if cfg.settings.env == "local":
        key = os.environ.get(ENV_COSMOS_KEY)
        if not key:
            raise RuntimeError("cosmos_key_missing")
        endpoint = os.environ.get(ENV_COSMOS_ENDPOINT, _LOCAL_COSMOS_DEFAULT)
        return SyncCosmosClient(endpoint, key, enable_endpoint_discovery=False)
    account = cfg.store.cosmos_account
    if not account:
        raise RuntimeError("cosmos_account_missing")
    profile = cfg.settings.cloud_profile
    return SyncCosmosClient(
        profile.cosmos_endpoint(account), SyncDefaultAzureCredential(authority=profile.login_host)
    )


async def list_stored_snapshots(cfg: RuntimeConfig) -> list[PriceSnapshot]:
    """Every stored snapshot, read through the sync Cosmos store in a thread."""

    def load() -> list[PriceSnapshot]:
        client = _sync_client(cfg)
        try:
            store = CosmosPriceSnapshotStore.from_client(client, database=cfg.store.database)
            return store.list_snapshots()
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    return await asyncio.to_thread(load)


async def ledger_price_table(cfg: RuntimeConfig, file_path: Any = None) -> PriceTable:
    """Stored snapshots (this cloud) merged with the file table.

    ``file_path`` defaults to ``NS_LEDGER_PRICE_TABLE_FILE``. A store failure leaves the file table
    (one log line, reason code only). Equal ids with different content raise
    ``PriceVersionConflictError`` (``price_version_conflict``): never a silent pick.
    """
    path = file_path if file_path is not None else LedgerSettings().price_table_file
    file_table = load_price_table(path)
    try:
        snapshots = await asyncio.wait_for(list_stored_snapshots(cfg), _TIMEOUT_SECONDS)
    except Exception:
        _log.warning(
            "stored price snapshots unavailable; using the file price table",
            extra={
                "event": "worker.price_snapshot_store_unavailable",
                "reason": PRICE_STORE_UNAVAILABLE,
            },
        )
        return file_table
    table = merge_price_tables(snapshots, file_table, cloud=cfg.cloud)
    _log.info(
        "ledger price table resolved",
        extra={
            "event": "worker.ledger_price_table",
            "stored_snapshots": len(snapshots),
            "versions": len(table.versions),
        },
    )
    return table

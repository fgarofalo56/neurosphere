"""Production wiring for the normalizer: real sinks and stores built from settings.

``build_pipeline_deps`` is the single construction path used by ``python -m
neurosphere_workers.ingestion`` and by the quarantine replay CLI, so a replay runs through exactly
the sinks the live consumer uses (PRP-07: replay never writes the ledger directly).

Sinks, all behind the item 2 protocols:

* quarantine: ``BlobQuarantineSink`` over the quarantine container,
* archive: ``create_archive_sink`` (one cloud, one storage account),
* ledger: ``CostLedgerSink`` over the Cosmos ledger and outbox containers.

Containers (blob and Cosmos) are created if missing ONLY when ``NS_ENV=local`` (emulators).
Everywhere else they are provisioned by IaC; a missing one is a clear startup error, never a
silent create. Client lifetimes belong to the caller's ``ClientLifetime``.

Prices: ``NS_LEDGER_PRICE_TABLE_FILE`` names an optional JSON file ``{"versions": [...]}`` of
``PriceVersion`` documents. Without it the table is EMPTY, so every estimate is honestly
``price_unresolved``; prices are never invented here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from azure.core.exceptions import ResourceExistsError
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import ContainerClient
from neurosphere_core.clients import (
    ClientLifetime,
    blob_account_url,
    create_cosmos_client,
    translating,
)
from neurosphere_core.clients.factories import ENV_BLOB_CONNECTION_STRING
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from neurosphere_core.ledger import CostLedger, PriceTable, PriceVersion
from neurosphere_core.ledger.cosmos import CosmosLedgerStore
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from neurosphere_workers.archive.factory import create_archive_sink
from neurosphere_workers.archive.settings import ArchiveSettings
from neurosphere_workers.ingestion.cosmos_stores import (
    CosmosAcceptedMarkerStore,
    CosmosWatermarkStore,
    ensure_containers,
)
from neurosphere_workers.ingestion.pipeline import PipelineDeps
from neurosphere_workers.ingestion.settings import IngestionSettings
from neurosphere_workers.projections.outbox import (
    CosmosOutboxStore,
    CostLedgerSink,
    OutboxWriter,
)
from neurosphere_workers.quarantine import (
    BlobQuarantineSink,
    QuarantineSettings,
    create_quarantine_container,
)


class LedgerSettings(BaseSettings):
    """Ledger/outbox wiring (env prefix ``NS_LEDGER_``). Cosmos database comes from ingestion."""

    model_config = SettingsConfigDict(env_prefix="NS_LEDGER_", frozen=True, extra="forbid")

    ledger_container: str = Field(default="cost-ledger", min_length=1)
    outbox_container: str = Field(default="outbox", min_length=1)
    # Per-sink outbox checkpoints (read side, PRP-10+); created/checked here so IaC drift shows
    # up at startup rather than at the first projection.
    checkpoint_container: str = Field(default="outbox-checkpoints", min_length=1)
    # Optional synthetic/operator price sheet. None -> empty table -> price_unresolved.
    price_table_file: Path | None = None


def _config_error(pointer: str, detail: str) -> InvalidSchemaError:
    return InvalidSchemaError(detail, errors=[ValidationIssue(pointer, detail)], reason="config")


def load_price_table(path: Path | None) -> PriceTable:
    """The configured price sheet, or an EMPTY table (estimates become ``price_unresolved``)."""
    if path is None:
        return PriceTable([])
    doc = json.loads(path.read_text(encoding="utf-8"))
    return PriceTable([PriceVersion.model_validate(v) for v in doc["versions"]])


async def ensure_blob_container(client: Any, name: str, *, create: bool) -> None:
    """Create (local) or verify (everywhere else) one blob container."""
    if create:
        try:
            await client.create_container()
        except ResourceExistsError:
            return
        return
    if not await client.exists():
        raise _config_error(
            "/container",
            f"blob container '{name}' does not exist; it must be provisioned by IaC",
        )


async def ensure_cosmos_containers(database: Any, names: list[str], *, create: bool) -> None:
    """Create (local) or verify (everywhere else) the Cosmos containers."""
    if create:
        await ensure_containers(database, *names)
        return
    for name in names:
        with translating():
            try:
                await database.get_container_client(name).read()
            except CosmosResourceNotFoundError:
                raise _config_error(
                    "/container",
                    f"cosmos container '{name}' does not exist; it must be provisioned by IaC",
                ) from None


def _blob_container_client(
    settings: Settings, name: str, account: str | None, lifetime: ClientLifetime
) -> ContainerClient:
    """A container client used only for the existence check/creation of ``name``."""
    if settings.env == "local":
        conn = os.environ.get(ENV_BLOB_CONNECTION_STRING)
        if not conn:
            raise _config_error("/connection_string", f"{ENV_BLOB_CONNECTION_STRING} is required")
        return lifetime.register(ContainerClient.from_connection_string(conn, name))
    if not account:
        raise _config_error("/storage_account", "storage account is required")
    credential = lifetime.register(
        DefaultAzureCredential(authority=settings.cloud_profile.login_host)
    )
    url = blob_account_url(settings.cloud_profile, account)
    return lifetime.register(ContainerClient(url, name, credential=credential))


async def build_pipeline_deps(
    settings: Settings,
    *,
    lifetime: ClientLifetime,
    ingestion: IngestionSettings | None = None,
    ledger: LedgerSettings | None = None,
    archive: ArchiveSettings | None = None,
    quarantine: QuarantineSettings | None = None,
) -> PipelineDeps:
    """Construct every sink and store. Raises a ``config`` error for missing infrastructure."""
    ingestion = ingestion or IngestionSettings()
    ledger = ledger or LedgerSettings()
    archive = archive or ArchiveSettings()
    quarantine = quarantine or QuarantineSettings()
    create = settings.env == "local"

    # Blob containers: archive, quarantine and the checkpoint store's own container.
    for name, account in (
        (archive.container, archive.storage_account),
        (quarantine.container, quarantine.storage_account),
        (ingestion.checkpoint_container, ingestion.storage_account),
    ):
        probe = _blob_container_client(settings, name, account, lifetime)
        await ensure_blob_container(probe, name, create=create)

    cosmos = create_cosmos_client(settings, lifetime=lifetime, account=ingestion.cosmos_account)
    if create:
        await cosmos.create_database_if_not_exists(ingestion.cosmos_database)
    database = cosmos.get_database_client(ingestion.cosmos_database)
    names = [
        ingestion.markers_container,
        ingestion.watermarks_container,
        ledger.ledger_container,
        ledger.outbox_container,
        ledger.checkpoint_container,
    ]
    await ensure_cosmos_containers(database, names, create=create)

    ledger_sink = CostLedgerSink(
        CostLedger(CosmosLedgerStore(database.get_container_client(ledger.ledger_container))),
        OutboxWriter(CosmosOutboxStore(database.get_container_client(ledger.outbox_container))),
        load_price_table(ledger.price_table_file),
    )
    return PipelineDeps(
        quarantine=BlobQuarantineSink(
            create_quarantine_container(settings, lifetime=lifetime, quarantine=quarantine)  # type: ignore[arg-type]
        ),
        archive=create_archive_sink(settings, archive, lifetime=lifetime),
        ledger=ledger_sink,
        markers=CosmosAcceptedMarkerStore(
            database.get_container_client(ingestion.markers_container)
        ),
        watermarks=CosmosWatermarkStore(
            database.get_container_client(ingestion.watermarks_container)
        ),
        cloud=(settings.cloud or CloudName.COMMERCIAL).value,
    )

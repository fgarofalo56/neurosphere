"""Ingestion worker settings (env prefix ``NS_INGESTION_``). Frozen, unknown fields refused."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NS_INGESTION_", frozen=True, extra="forbid")

    # PRP-07 C7: lateness is configuration, not logic. An event is late when its event time is
    # older than (newest event time seen for its source) minus this window. Late events are
    # still accepted and flagged; they are never dropped. 300 s covers ordinary producer
    # batching/clock skew without letting a stalled source hold hot aggregates open for long.
    lateness_seconds: float = Field(default=300.0, ge=0)

    # PRP-07 C8: total tries per sink write (first try included), then quarantine.
    max_attempts: int = Field(default=3, ge=1)
    backoff_base_seconds: float = Field(default=0.5, gt=0)
    backoff_max_seconds: float = Field(default=30.0, gt=0)

    # Event Hubs; names match infra/compose/eventhubs.config.json.
    eventhub_name: str = "telemetry"
    consumer_group: str = "normalizer"
    max_batch_size: int = Field(default=100, ge=1)
    max_wait_seconds: float = Field(default=5.0, gt=0)

    # Blob checkpoint store (Azurite locally).
    checkpoint_container: str = "ns-ingestion-checkpoints"

    # Cosmos (partition key /customer_id on both containers).
    cosmos_database: str = "neurosphere"
    markers_container: str = "ingestion-accepted"
    watermarks_container: str = "ingestion-watermarks"

    # Non-local only (managed identity). Local emulator values come from the NS_* client env.
    eventhubs_namespace: str | None = None
    storage_account: str | None = None
    cosmos_account: str | None = None

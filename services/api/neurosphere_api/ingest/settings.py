"""Ingest edge settings (``NS_INGEST_*``), read once into a frozen object.

Body-size interaction with the global middleware: ``RequestSizeLimitMiddleware`` (default
1 MiB, set by ``create_app(max_request_bytes=...)``) wraps every route and runs first, so the
effective cap on an ingest request is ``min(global limit, max_body_bytes)``. The edge limit
exists as a per-route security control that holds even if the global value is raised, and it
counts bytes while the stream is read, before ``json.loads``. Both failures are
``invalid_schema`` (422); the global one carries reason ``request_too_large`` and the edge one
``body_too_large``. Raising ``NS_INGEST_MAX_BODY_BYTES`` above the global limit has no effect
unless ``create_app`` is given a larger ``max_request_bytes`` too.
"""

from __future__ import annotations

from pathlib import Path

from neurosphere_core.payload import DEFAULT_MAX_BODY_BYTES, DEFAULT_MAX_DEPTH
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Hub name declared in infra/compose/eventhubs.config.json (read-only reference).
DEFAULT_EVENTHUB_NAME = "telemetry"


class IngestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NS_INGEST_", frozen=True, extra="forbid")

    max_body_bytes: int = Field(default=DEFAULT_MAX_BODY_BYTES, gt=0)
    max_depth: int = Field(default=DEFAULT_MAX_DEPTH, gt=0)
    # Per-producer token bucket: sustained requests per second and burst capacity.
    rate_limit_rps: float = Field(default=20.0, gt=0)
    rate_limit_burst: int = Field(default=40, gt=0)
    eventhub_name: str = DEFAULT_EVENTHUB_NAME
    # JSON file of producer registrations (hashes only); None means no producer can authenticate.
    producers_file: Path | None = None
    # Non-local only (managed identity): the Event Hubs namespace. Local uses the emulator
    # connection string from NS_EVENTHUBS_CONNECTION_STRING.
    eventhubs_namespace: str | None = None

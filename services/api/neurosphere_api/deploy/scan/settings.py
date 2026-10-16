"""Resource scan settings (``NS_SCAN_*``), read once into a frozen object."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScanSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NS_SCAN_", frozen=True, extra="forbid")

    request_timeout_seconds: float = Field(default=30.0, gt=0)
    # Rows per Resource Graph page (service maximum is 1000).
    page_size: int = Field(default=1000, gt=0, le=1000)
    # Upper bound on pages per query so a runaway skip-token chain cannot loop forever.
    max_pages: int = Field(default=50, gt=0)
    # Upper bound on subscriptions in one scan request.
    max_subscriptions: int = Field(default=100, gt=0, le=1000)

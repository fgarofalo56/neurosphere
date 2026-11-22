"""Agent identity settings (read by later PRP-137 items; nothing wires them yet)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentIdentitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NS_AGENT_IDENTITY_", frozen=True, extra="ignore")

    positive_ttl_seconds: float = Field(default=60.0, ge=0)
    negative_ttl_seconds: float = Field(default=15.0, ge=0)
    rescan_max_events: int = Field(default=50_000, ge=1)
    # Domain stamped on events with none whose agent is derived (not in the catalog). Must be an
    # owned domain id of the event's cloud and customer, else it is ignored.
    discovery_domain: str | None = Field(default=None)

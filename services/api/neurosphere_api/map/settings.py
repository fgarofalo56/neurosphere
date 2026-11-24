"""Live-map topology settings (PRP-74): ``NS_MAP_*`` environment variables.

Every budget is range-checked here so a misconfiguration fails at startup, never at request
time. No ``from __future__ import annotations``: pydantic resolves these annotations at import.
"""

from typing import Final

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["MapSettings"]

DEFAULT_POLL_SECONDS: Final = 3.0
DEFAULT_FAILING_RATIO: Final = 0.5
DEFAULT_DEGRADED_RATIO: Final = 0.34


class MapSettings(BaseSettings):
    """Frozen; read once at startup (``MapSettings()`` reads the environment)."""

    model_config = SettingsConfigDict(env_prefix="NS_MAP_", frozen=True, extra="forbid")

    topology_enabled: bool = True
    topology_poll_seconds: float = Field(default=DEFAULT_POLL_SECONDS, ge=1, le=60)
    topology_scan_pages: int = Field(default=20, ge=1, le=200)
    search_scan_pages: int = Field(default=100, ge=1, le=200)
    search_timeout_ms: int = Field(default=8000, ge=100, le=60_000)
    derived_failing_ratio: float = Field(default=DEFAULT_FAILING_RATIO, gt=0, le=1)
    """Share of direct dependents that must be failing for the fallback rule to say failing."""
    derived_degraded_ratio: float = Field(default=DEFAULT_DEGRADED_RATIO, gt=0, le=1)
    """Share of direct dependents that must be degraded or worse to infer degraded."""

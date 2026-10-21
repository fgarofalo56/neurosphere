"""Realtime gateway settings (PRP-18 item 1): ``NS_REALTIME_*`` environment variables.

Every budget is bounded here so a misconfiguration fails at startup, never at request time.
Defaults: a 2 s poll of the hot aggregates, 8 subscriptions and 5 messages/s (burst 10) per
session, 5 sessions per principal.
"""

from typing import Final

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["RealtimeSettings"]

DEFAULT_POLL_INTERVAL_SECONDS: Final = 2.0


class RealtimeSettings(BaseSettings):
    """Frozen; read once at startup (``RealtimeSettings()`` reads the environment)."""

    model_config = SettingsConfigDict(env_prefix="NS_REALTIME_", frozen=True, extra="forbid")

    poll_interval_seconds: float = Field(default=DEFAULT_POLL_INTERVAL_SECONDS, gt=0, le=60)
    heartbeat_seconds: float = Field(default=15.0, gt=0, le=300)
    """Resend an unchanged delta this often so lag and coverage labels stay current."""
    scope_refresh_seconds: float = Field(default=1.0, ge=0, le=60)
    """Upper bound on the age of the scope a delta is filtered by (also bounded by the
    revocation TTL: see ``effective_refresh_seconds``)."""
    max_subscriptions: int = Field(default=8, ge=1, le=64)
    max_sessions_per_principal: int = Field(default=5, ge=1, le=100)
    message_rate_per_second: float = Field(default=5.0, gt=0, le=1000)
    message_burst: int = Field(default=10, ge=1, le=1000)
    max_rate_violations: int = Field(default=3, ge=1, le=1000)
    """Rate-limit breaches tolerated per session before the socket closes with 4429."""
    max_message_bytes: int = Field(default=4096, ge=64, le=1_048_576)
    send_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    """A client that cannot take a frame within this long is dropped (4429, counted)."""
    delayed_after_seconds: float = Field(default=30.0, gt=0)
    """Aggregate lag above this labels the delta's coverage ``delayed``."""
    health_degraded_error_rate: float = Field(default=0.05, ge=0, le=1)
    health_failing_error_rate: float = Field(default=0.25, ge=0, le=1)

    def effective_refresh_seconds(self, revocation_ttl_seconds: float) -> float:
        """Scope refresh period: at most half the revocation TTL.

        Half, not the whole TTL, because the revocation checker may serve a cached "not revoked"
        answer for up to one TTL; refreshing twice per TTL guarantees a refresh that lands after
        that entry expired, so a revocation closes the socket within one TTL of being recorded
        (plus one poll interval).
        """
        return min(self.scope_refresh_seconds, revocation_ttl_seconds / 2)

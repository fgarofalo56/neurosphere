"""Settings for the ``gateway_poll`` role (``NS_GATEWAY_POLL_*`` plus ``NS_API_BASE_URL``).

The producer secret is read from ``NS_GATEWAY_POLL_PRODUCER_SECRET`` (a vault reference in
production). It is held as a ``SecretStr`` so it never prints in a repr or a log line.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["DEFAULT_PRODUCER_ID", "DEFAULT_SOURCE_ID", "GatewayPollSettings"]

DEFAULT_PRODUCER_ID = "apim-gateway-poll"
#: The ``source_id`` stamped on every polled event; it must be a key of the producer's ``sources``.
DEFAULT_SOURCE_ID = "apim-gateway-poll"
_GUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")


class GatewayPollSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NS_GATEWAY_POLL_", frozen=True, extra="ignore", populate_by_name=True
    )

    #: Seconds between polls of the registered gateways.
    interval_seconds: float = Field(default=900.0, gt=0)
    #: Longest span of logs one poll covers (bounds the connector window).
    window_seconds: int = Field(default=3600, gt=0)
    #: How far back the first poll of a gateway reaches.
    lookback_seconds: int = Field(default=86400, gt=0)
    #: Same opt-in as the connector: Government is configuration-only and unverified.
    allow_unverified_government: bool = False
    #: Comma list of domain ids whose registrations this worker polls (required).
    domain_ids: str | None = None
    producer_id: str = Field(default=DEFAULT_PRODUCER_ID, min_length=1, max_length=128)
    source_id: str = Field(default=DEFAULT_SOURCE_ID, min_length=1, max_length=128)
    producer_secret: SecretStr | None = None
    api_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("NS_API_BASE_URL", "NS_GATEWAY_POLL_API_BASE_URL"),
    )
    #: Events per ingest request.
    batch_size: int = Field(default=100, ge=1, le=500)

    #: Optional App Insights application id (a GUID, not a secret) enabling the best-effort
    #: customMetrics poll that attributes a cost center. Unset means no metrics poll.
    metrics_app_id: str | None = None

    @field_validator("domain_ids", "api_base_url", "metrics_app_id", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("metrics_app_id")
    @classmethod
    def _guid(cls, value: str | None) -> str | None:
        if value is not None and _GUID.fullmatch(value) is None:
            raise ValueError("metrics_app_id must be a GUID")
        return value

    @property
    def unconfigured(self) -> bool:
        """True when neither a domain list nor a producer secret is set.

        The role is part of ``all``, so a deployment with no gateway polling configured must start
        it as a harmless no-op instead of failing. Any partial configuration (domains without a
        secret, or the reverse) is an operator error and is still refused by the factory.
        """
        return not self.domains and self.producer_secret is None

    @property
    def domains(self) -> tuple[str, ...]:
        raw = self.domain_ids or ""
        return tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))

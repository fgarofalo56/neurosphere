"""Settings for the ``azure_monitor_ai`` role (``NS_AZURE_MONITOR_AI_*`` plus ``NS_API_BASE_URL``).

The producer secret is read from ``NS_AZURE_MONITOR_AI_PRODUCER_SECRET`` (a vault reference in
production) and held as a ``SecretStr`` so it never prints in a repr or a log line. Every volume
guard of PRP-141 clarification 7 is a validated field limit.
"""

from __future__ import annotations

import re
from typing import Any, Self

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "DEFAULT_PRODUCER_ID",
    "DEFAULT_SOURCE_ID",
    "MAX_WORKSPACES",
    "AzureMonitorAiSettings",
]

DEFAULT_PRODUCER_ID = "azure-monitor-ai"
#: The ``source_id`` stamped on every event; it must be a key of the producer's ``sources``.
DEFAULT_SOURCE_ID = "azure-monitor-ai"
MAX_WORKSPACES = 4
_GUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")


def _split(raw: str | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(part.strip() for part in (raw or "").split(",") if part.strip()))


class AzureMonitorAiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NS_AZURE_MONITOR_AI_", frozen=True, extra="ignore", populate_by_name=True
    )

    #: Comma list of Log Analytics workspace ids (GUIDs, not secrets), 1..4 when configured.
    workspace_ids: str | None = None
    #: The one domain every event of this configuration belongs to (PRP-141 clarification 11).
    domain_id: str | None = None
    interval_seconds: float = Field(default=300.0, ge=60)
    #: Longest span of logs one poll of one workspace and kind covers.
    window_seconds: int = Field(default=3600, ge=60, le=86400)
    #: How far back the first poll reaches (no historical backfill beyond 7 days).
    lookback_seconds: int = Field(default=86400, ge=60, le=604800)
    #: Re-read of the last seconds before the watermark (late rows; event ids are deterministic).
    overlap_seconds: int = Field(default=600, ge=0)
    max_queries_per_tick: int = Field(default=24, ge=1, le=200)
    max_events_per_tick: int = Field(default=20000, ge=1, le=100000)
    #: Optional comma list; rows of other ``AppRoleName`` values are skipped in the mapper.
    app_role_names: str | None = None
    allow_unverified_government: bool = False
    producer_id: str = Field(default=DEFAULT_PRODUCER_ID, min_length=1, max_length=128)
    source_id: str = Field(default=DEFAULT_SOURCE_ID, min_length=1, max_length=128)
    producer_secret: SecretStr | None = None
    api_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("NS_API_BASE_URL", "NS_AZURE_MONITOR_AI_API_BASE_URL"),
    )
    batch_size: int = Field(default=100, ge=1, le=500)
    managed_identity_client_id: str | None = None

    @field_validator(
        "workspace_ids",
        "domain_id",
        "app_role_names",
        "api_base_url",
        "managed_identity_client_id",
        mode="before",
    )
    @classmethod
    def _blank(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("workspace_ids")
    @classmethod
    def _workspaces(cls, value: str | None) -> str | None:
        if value is None:
            return None
        ids = _split(value)
        if not 1 <= len(ids) <= MAX_WORKSPACES:
            raise ValueError(f"workspace_ids must hold 1..{MAX_WORKSPACES} workspaces")
        if any(_GUID.fullmatch(item) is None for item in ids):
            raise ValueError("workspace_ids must be GUIDs")
        return ",".join(dict.fromkeys(item.lower() for item in ids))

    @field_validator("domain_id")
    @classmethod
    def _one_domain(cls, value: str | None) -> str | None:
        if value is not None and "," in value:
            raise ValueError("domain_id must be exactly one domain")
        return value

    @field_validator("managed_identity_client_id")
    @classmethod
    def _client_guid(cls, value: str | None) -> str | None:
        if value is not None and _GUID.fullmatch(value) is None:
            raise ValueError("managed_identity_client_id must be a GUID")
        return value

    @model_validator(mode="after")
    def _overlap_below_window(self) -> Self:
        if self.overlap_seconds >= self.window_seconds:
            raise ValueError("overlap_seconds must be below window_seconds")
        return self

    @property
    def workspaces(self) -> tuple[str, ...]:
        return _split(self.workspace_ids)

    @property
    def roles(self) -> tuple[str, ...] | None:
        """The ``AppRoleName`` allowlist, or ``None`` for every role."""
        names = _split(self.app_role_names)
        return names or None

    @property
    def unconfigured(self) -> bool:
        """True when neither a workspace list nor a producer secret is set.

        The role is part of ``all``, so a deployment that does not read Azure Monitor idles. Any
        partial configuration is an operator error and is refused by the builder.
        """
        return not self.workspaces and self.producer_secret is None

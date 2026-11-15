"""``NS_WORKER_CONNECTOR_CONFIG_*``: where the connector roles take their configuration from."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["ConnectorConfigSettings"]


class ConnectorConfigSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NS_WORKER_CONNECTOR_CONFIG_", frozen=True, extra="ignore"
    )

    #: ``auto`` (default): a stored config wins per connector kind, else the environment.
    #: ``env``: ignore the store (the rollback switch). ``store``: ignore the environment.
    source: Literal["auto", "env", "store"] = "auto"
    #: Bound of the store read and of each Key Vault read, in seconds.
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)

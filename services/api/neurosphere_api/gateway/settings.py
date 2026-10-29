"""Gateway registry settings (``NS_GATEWAY_*``) and store selection.

``NS_GATEWAY_STORE``: ``auto`` (default) and ``cosmos`` always use Cosmos; ``memory`` is
the only in-memory choice and is refused outside ``NS_ENV=local``
(``NS_GATEWAY_COSMOS_ACCOUNT`` outside local, emulator keys come from the usual ``NS_COSMOS_*``).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final, Literal

from neurosphere_core.cloud import Settings
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["GatewaySettings", "resolve_store_kind"]

DEFAULT_ARM_API_VERSION: Final = "2024-05-01"


class GatewaySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    store: Literal["auto", "memory", "cosmos"] = "auto"
    cosmos_account: str | None = None
    cosmos_database: str = Field(default="neurosphere", min_length=1)
    cosmos_container: str = Field(default="gateways", min_length=1)
    arm_api_version: str = Field(default=DEFAULT_ARM_API_VERSION, pattern=r"^\d{4}-\d{2}-\d{2}")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> GatewaySettings:
        env = os.environ if environ is None else environ
        values: dict[str, str] = {}
        for field, name in (
            ("store", "NS_GATEWAY_STORE"),
            ("cosmos_account", "NS_GATEWAY_COSMOS_ACCOUNT"),
            ("cosmos_database", "NS_GATEWAY_COSMOS_DATABASE"),
            ("cosmos_container", "NS_GATEWAY_COSMOS_CONTAINER"),
            ("arm_api_version", "NS_GATEWAY_ARM_API_VERSION"),
        ):
            if env.get(name):
                values[field] = env[name]
        return cls.model_validate(values)


def resolve_store_kind(settings: Settings, gateway: GatewaySettings) -> Literal["memory", "cosmos"]:
    if gateway.store == "memory":
        if settings.env != "local":
            raise InvalidSchemaError(
                "the in-memory gateway store is only allowed when NS_ENV=local",
                errors=[ValidationIssue("/NS_GATEWAY_STORE", "memory store requires NS_ENV=local")],
                reason="config",
            )
        return "memory"
    return "cosmos"

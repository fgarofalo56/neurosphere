"""Synapse adapter configuration and the cloud boundary (PRP-11 item 3).

Authentication is Entra / managed identity only: the model has no secret field and forbids
unknown keys, so a password or connection string cannot be smuggled in. ``client_id`` selects
a user-assigned managed identity and is an identifier, not a secret.

Endpoint hosts (observed 2026-10-18):

* Commercial ``<workspace>.sql.azuresynapse.net`` (dedicated) and
  ``<workspace>-ondemand.sql.azuresynapse.net`` (serverless built-in pool).
* Government ``<workspace>.sql.azuresynapse.usgovcloudapi.net`` and
  ``<workspace>-ondemand.sql.azuresynapse.usgovcloudapi.net``. Suffix source:
  https://learn.microsoft.com/azure/private-link/private-endpoint-dns#government
* The legacy ``<server>.database.windows.net`` host form for a standalone (formerly SQL DW)
  dedicated pool is deliberately NOT supported: it is a different resource type with a
  different Government suffix and no citation was verified for it.

Every check here runs at construction. A Government configuration that names a Commercial
host (or the reverse) never builds an adapter, so nothing can be routed across clouds.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from neurosphere_core.analytics.base.models import Cloud
from neurosphere_core.errors import InvalidSchemaError

SynapseMode = Literal["serverless", "dedicated"]

HOST_SUFFIX: Final[dict[str, str]] = {
    "commercial": ".sql.azuresynapse.net",
    "government": ".sql.azuresynapse.usgovcloudapi.net",
}
ONDEMAND_MARK: Final = "-ondemand"
LEGACY_DEDICATED_SUFFIX: Final = ".database.windows.net"

_IDENT = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
_WORKSPACE = r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$"
_GOV_REGION_RE = re.compile(r"^us(gov|dod)[a-z0-9]+$")
_REGION_RE = re.compile(r"^[a-z][a-z0-9]{2,39}$")


def _bad(detail: str, reason: str) -> InvalidSchemaError:
    return InvalidSchemaError(detail, reason=reason)


class SynapseConfig(BaseModel):
    """Frozen, ``extra="forbid"`` adapter configuration. ``host`` defaults to the canonical
    host derived from ``workspace`` and ``mode`` (per cloud) when omitted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: SynapseMode
    workspace: str = Field(pattern=_WORKSPACE)
    database: str = Field(pattern=_IDENT)
    host: str | None = Field(default=None, max_length=255)
    schema_name: str = Field(default="ns", pattern=_IDENT)
    auth: Literal["entra_managed_identity"] = "entra_managed_identity"
    client_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{36}$")
    external_data_source: str | None = Field(default=None, pattern=_IDENT)

    @model_validator(mode="after")
    def _host_agrees_with_mode(self) -> Self:
        if self.host is not None:
            host = self.host
            if host != host.lower() or host.endswith(LEGACY_DEDICATED_SUFFIX):
                raise ValueError(
                    "host must be a lowercase Synapse SQL endpoint; the legacy "
                    f"{LEGACY_DEDICATED_SUFFIX} dedicated-pool host form is not supported"
                )
            label = host.split(".", 1)[0]
            if label.endswith(ONDEMAND_MARK) != (self.mode == "serverless"):
                raise ValueError(
                    f"host does not match mode {self.mode!r}: the serverless endpoint "
                    f"carries {ONDEMAND_MARK!r}, the dedicated endpoint does not"
                )
        if self.mode == "dedicated" and self.external_data_source is not None:
            raise ValueError("external_data_source applies to serverless mode only")
        return self


def parse_config(config: SynapseConfig | Mapping[str, Any]) -> SynapseConfig:
    if isinstance(config, SynapseConfig):
        return config
    try:
        return SynapseConfig.model_validate(dict(config))
    except ValidationError as exc:
        # Field names plus our own static validator messages (they never embed input values);
        # never echo input: a mistaken secret must not reach a log.
        fields = sorted({".".join(str(p) for p in e["loc"]) or "config" for e in exc.errors()})
        rules = sorted(
            str(e["msg"]).removeprefix("Value error, ")
            for e in exc.errors()
            if e["type"] == "value_error"
        )
        detail = f"invalid Synapse configuration (fields: {', '.join(fields)})"
        if rules:
            detail += "; " + "; ".join(rules)
        raise _bad(detail, "synapse_config") from None


def resolve_endpoint(config: SynapseConfig, *, cloud: Cloud, region: str) -> str:
    """Validate cloud/region/host consistency and return the endpoint host. Raises
    ``InvalidSchemaError`` (no network, no partial object) on any mismatch."""
    if cloud not in HOST_SUFFIX:
        raise _bad(f"unknown cloud {cloud!r}", "synapse_cloud")
    if not _REGION_RE.match(region):
        raise _bad("region must be a lowercase ARM region name", "synapse_region")
    if bool(_GOV_REGION_RE.match(region)) != (cloud == "government"):
        raise _bad(f"region {region!r} does not belong to cloud {cloud!r}", "synapse_region")
    suffix = HOST_SUFFIX[cloud]
    mark = ONDEMAND_MARK if config.mode == "serverless" else ""
    expected = f"{config.workspace}{mark}{suffix}"
    if config.host is None:
        return expected
    for other_cloud, other_suffix in HOST_SUFFIX.items():
        if other_cloud != cloud and config.host.endswith(other_suffix):
            raise _bad(
                f"host belongs to the {other_cloud} cloud but the adapter is {cloud}",
                "synapse_cloud_host_mismatch",
            )
    if config.host != expected:
        raise _bad(
            f"host must be {expected!r} for {cloud} {config.mode} workspace {config.workspace!r}",
            "synapse_cloud_host_mismatch",
        )
    return config.host

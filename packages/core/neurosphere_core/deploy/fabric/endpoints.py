"""Per-cloud Fabric endpoint sets. Government never carries a Commercial host."""

from __future__ import annotations

from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, model_validator

from neurosphere_core.cloud import CloudName, profile_for
from neurosphere_core.errors import InvalidSchemaError

# Source: https://learn.microsoft.com/fabric/enterprise/us-government-community-cloud-high
# ("API endpoints" table), observed 2026-10-16.
COMMERCIAL_FABRIC_API = "https://api.fabric.microsoft.com"
COMMERCIAL_FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
GOVERNMENT_FABRIC_API = "https://highapi.fabric.microsoft.us"

_GOV_HOST_SUFFIXES = (".us", "usgovcloudapi.net")


def _host(url: str) -> str:
    host = urlsplit(url).hostname
    if not host:
        raise ValueError(f"{url!r} has no host")
    return host.lower()


class FabricEndpoints(BaseModel):
    """Fabric REST base, token scope and ARM management URL for one cloud."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cloud: CloudName
    fabric_api_base: str
    token_scope: str
    management_url: str

    @model_validator(mode="after")
    def _hosts_belong_to_cloud(self) -> Self:
        for name in ("fabric_api_base", "token_scope", "management_url"):
            url = getattr(self, name)
            if urlsplit(url).scheme != "https":
                raise ValueError(f"{name} must be an https URL")
            host = _host(url)
            if self.cloud is CloudName.GOVERNMENT:
                if not host.endswith(_GOV_HOST_SUFFIXES):
                    raise ValueError(f"{name} host {host!r} is not in the government suffix set")
            elif host.endswith(_GOV_HOST_SUFFIXES):
                raise ValueError(f"{name} host {host!r} is a government host in a commercial set")
        if self.cloud is CloudName.GOVERNMENT:
            if _host(self.fabric_api_base) != _host(GOVERNMENT_FABRIC_API):
                raise ValueError("fabric_api_base is not the GCC High Fabric API host")
        elif _host(self.fabric_api_base) != _host(COMMERCIAL_FABRIC_API):
            raise ValueError("fabric_api_base is not the Commercial Fabric API host")
        if self.management_url != profile_for(self.cloud).management_url:
            raise ValueError("management_url is not the cloud profile management URL")
        return self

    @property
    def allowed_hosts(self) -> frozenset[str]:
        """Hosts this endpoint set may call (also used to vet LRO ``Location`` URLs)."""
        return frozenset({_host(self.fabric_api_base), _host(self.management_url)})


def fabric_endpoints_for(cloud: CloudName, *, token_scope: str | None = None) -> FabricEndpoints:
    """Canonical endpoint set for ``cloud``.

    Government requires an explicitly configured ``token_scope``: the GCC High token
    audience could NOT be verified from Microsoft Learn (UNVERIFIED), so it is never guessed.
    """
    if cloud is CloudName.GOVERNMENT:
        if not token_scope:
            raise InvalidSchemaError(
                "Government Fabric token scope is unverified and must be configured",
                reason="fabric_gov_scope_required",
            )
        base = GOVERNMENT_FABRIC_API
        scope = token_scope
    else:
        base = COMMERCIAL_FABRIC_API
        scope = token_scope or COMMERCIAL_FABRIC_SCOPE
    try:
        return FabricEndpoints(
            cloud=cloud,
            fabric_api_base=base,
            token_scope=scope,
            management_url=profile_for(cloud).management_url,
        )
    except ValueError as exc:
        raise InvalidSchemaError(str(exc), reason="fabric_endpoints_invalid") from exc

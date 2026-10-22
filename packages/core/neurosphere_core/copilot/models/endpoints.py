"""Adapter configuration and the cloud/endpoint boundary check.

An endpoint is accepted only when its parsed hostname belongs to the deployment's own cloud:
Government deployments use Government hosts (``*.azure.us``, ``*.usgovcloudapi.net``) and a
Commercial host is refused there, because Government data is never routed to Commercial. The
configuration has no key field (``extra="forbid"``): identity is a managed-identity credential
supplied by the caller, never a raw key.
"""

from __future__ import annotations

from typing import Final, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from neurosphere_core.copilot.models.protocol import AdapterKind
from neurosphere_core.errors import CapabilityUnavailableError

Cloud = Literal["commercial", "government"]

GOVERNMENT_SUFFIXES: Final = (".azure.us", ".usgovcloudapi.net")
COMMERCIAL_SUFFIXES: Final = (
    ".openai.azure.com",
    ".services.ai.azure.com",
    ".cognitiveservices.azure.com",
)

_DEFAULT_SCOPES: Final[dict[tuple[AdapterKind, Cloud], str]] = {
    ("approved_endpoint", "commercial"): "https://cognitiveservices.azure.com/.default",
    ("approved_endpoint", "government"): "https://cognitiveservices.azure.us/.default",
    ("foundry_agent", "commercial"): "https://ai.azure.com/.default",
}


class AdapterConfig(BaseModel):
    """Deployment-config entry for one adapter. No key, secret or connection-string field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: AdapterKind
    endpoint: str | None = Field(default=None, max_length=512)
    # Azure OpenAI deployment name (approved_endpoint) or agent name (foundry_agent).
    deployment: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    # Capability-matrix identity of the model behind it (service ``foundry``).
    model_feature: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,127}$")
    sku: str | None = Field(default=None, min_length=1, max_length=128)
    api_version: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._-]{1,32}$")
    oauth_scope: str | None = Field(default=None, max_length=256)


def endpoint_problem(cloud: Cloud, endpoint: str | None) -> tuple[str, str] | None:
    """``(reason_code, reason)`` when ``endpoint`` may not be used in ``cloud``, else ``None``."""
    if not endpoint:
        return "endpoint_missing", "no endpoint is configured for this adapter"
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return "endpoint_invalid", "the endpoint must be an https URL with a host"
    if parts.username or parts.password:
        return "endpoint_invalid", "the endpoint must not embed credentials"
    is_gov = host.endswith(GOVERNMENT_SUFFIXES)
    if cloud == "government":
        if not is_gov:
            return (
                "endpoint_cloud_mismatch",
                f"{host} is not a Government-cloud endpoint; Government data is never "
                "routed to a Commercial endpoint",
            )
        return None
    if is_gov:
        return (
            "endpoint_cloud_mismatch",
            f"{host} is a Government-cloud endpoint but the deployment is Commercial",
        )
    if not host.endswith(COMMERCIAL_SUFFIXES):
        return "endpoint_not_approved", f"{host} is not an approved Azure AI endpoint host"
    return None


def require_endpoint(cloud: Cloud, endpoint: str | None) -> str:
    """Return ``endpoint`` (no trailing slash) or raise ``capability_unavailable``."""
    problem = endpoint_problem(cloud, endpoint)
    if problem is not None or endpoint is None:
        code, reason = problem or ("endpoint_missing", "no endpoint is configured")
        raise CapabilityUnavailableError(code, reason)
    return endpoint.rstrip("/")


def token_scope(config: AdapterConfig, cloud: Cloud) -> str:
    """Explicit scope from config, else the documented default; Foundry in Government has none."""
    if config.oauth_scope:
        return config.oauth_scope
    default = _DEFAULT_SCOPES.get((config.kind, cloud))
    if default is None:
        raise CapabilityUnavailableError(
            "token_scope_required",
            f"{config.kind} in {cloud} needs an explicit oauth_scope in deployment config",
        )
    return default

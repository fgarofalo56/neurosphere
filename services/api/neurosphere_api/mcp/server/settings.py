"""MCP resource-server settings (``NS_MCP_*``), read once into a frozen object (PRP-22 item 1).

The MCP server is its own OAuth 2.1 protected resource, distinct from the REST API:

* ``NS_MCP_RESOURCE_SERVER_URL`` - the MCP resource identifier (RFC 8707 / RFC 9728
  ``resource``). HTTPS only, no query, fragment or userinfo, and its path is fixed to
  :data:`MCP_PATH` so the RFC 9728 metadata route is one exact, parameter-free path.
* ``NS_MCP_AUDIENCES`` - JSON list of accepted token audiences (the Entra application ID URI
  and/or client id of the MCP app registration). Empty means ``[resource_server_url]``. It must
  never overlap the REST API audiences (checked when the server is built).
* ``NS_MCP_REQUIRED_SCOPE`` - delegated scope every caller must hold (default ``mcp.invoke``);
  a valid token without it is 403 ``insufficient_scope``.
* ``NS_MCP_ALLOWED_HOSTS`` - JSON list of extra ``Host`` header values accepted by the
  DNS-rebinding guard (for example an ingress host). The resource host is always allowed.

The authorization server is never configured here: it is the Entra v2 issuer of the deployment's
cloud profile and tenant, taken from the MCP ``JwtConfig`` (:func:`authorization_server_for`), so
a Government deployment advertises ``login.microsoftonline.us`` and Commercial
``login.microsoftonline.com`` without either being hard-coded.
"""

from __future__ import annotations

import os
import re
from typing import Final
from urllib.parse import urlsplit

from neurosphere_core.auth.jwt import DevIssuerTrust, JwtConfig, entra_issuers
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "DEFAULT_REQUIRED_SCOPE",
    "ENV_PREFIX",
    "MCP_PATH",
    "PROTECTED_RESOURCE_METADATA_PATH",
    "McpServerSettings",
    "authorization_server_for",
    "load_mcp_server_settings",
    "mcp_jwt_config",
]

ENV_PREFIX: Final = "NS_MCP_"
#: Path of the streamable HTTP endpoint (and of the resource identifier URL).
MCP_PATH: Final = "/mcp"
#: RFC 9728 section 3.1: the well-known segment is inserted between host and resource path.
PROTECTED_RESOURCE_METADATA_PATH: Final = "/.well-known/oauth-protected-resource" + MCP_PATH
DEFAULT_REQUIRED_SCOPE: Final = "mcp.invoke"

_SCOPE_NAME: Final = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")
_HOST: Final = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?(:[0-9]{1,5})?$")


class McpServerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, frozen=True, extra="forbid")

    resource_server_url: str
    audiences: tuple[str, ...] = Field(default=(), max_length=8)
    required_scope: str = DEFAULT_REQUIRED_SCOPE
    allowed_hosts: tuple[str, ...] = Field(default=(), max_length=8)

    @field_validator("resource_server_url")
    @classmethod
    def _https_resource(cls, value: str) -> str:
        parts = urlsplit(value.strip())
        if parts.scheme != "https":
            raise ValueError("resource_server_url must use https")
        if not parts.hostname or parts.username is not None or parts.password is not None:
            raise ValueError("resource_server_url must name a host and carry no userinfo")
        if parts.query or parts.fragment:
            raise ValueError("resource_server_url must have no query or fragment")
        if parts.path != MCP_PATH:
            raise ValueError(f"resource_server_url path must be {MCP_PATH}")
        host = parts.hostname.lower()
        netloc = host if parts.port is None else f"{host}:{parts.port}"
        return f"https://{netloc}{MCP_PATH}"

    @field_validator("audiences")
    @classmethod
    def _explicit_audiences(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for aud in value:
            if not aud or aud != aud.strip() or "*" in aud or any(c.isspace() for c in aud):
                raise ValueError("audiences must be explicit, non-empty and contain no wildcard")
        return value

    @field_validator("required_scope")
    @classmethod
    def _scope_name(cls, value: str) -> str:
        if not _SCOPE_NAME.fullmatch(value):
            raise ValueError("required_scope must be a single scope name")
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def _hosts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for host in value:
            if not _HOST.fullmatch(host):
                raise ValueError("allowed_hosts entries must be exact lowercase host[:port]")
        return value

    @property
    def effective_audiences(self) -> tuple[str, ...]:
        """Accepted token audiences: the configured ones, else the resource identifier."""
        return self.audiences or (self.resource_server_url,)

    @property
    def resource_host(self) -> str:
        """``host[:port]`` of the resource identifier (always allowed by the Host guard)."""
        return urlsplit(self.resource_server_url).netloc

    @property
    def protected_resource_metadata_url(self) -> str:
        """Absolute RFC 9728 metadata URL (the ``resource_metadata`` of ``WWW-Authenticate``)."""
        return f"https://{self.resource_host}{PROTECTED_RESOURCE_METADATA_PATH}"


def _issues(exc: ValidationError) -> list[ValidationIssue]:
    return [
        ValidationIssue("/" + "/".join(str(p) for p in err["loc"]), str(err["msg"])[:200])
        for err in exc.errors(include_input=False, include_url=False)
    ]


def load_mcp_server_settings() -> McpServerSettings | None:
    """Read ``NS_MCP_*`` once. ``None`` when the MCP server is not configured (no resource URL);
    an invalid configuration raises ``invalid_schema`` (reason ``config``) at startup."""
    if not os.environ.get(f"{ENV_PREFIX}RESOURCE_SERVER_URL"):
        return None
    try:
        return McpServerSettings()  # pyright: ignore[reportCallIssue]
    except ValidationError as exc:
        raise InvalidSchemaError(
            "invalid MCP server configuration", errors=_issues(exc), reason="config"
        ) from None


def mcp_jwt_config(
    settings: Settings,
    mcp: McpServerSettings,
    *,
    tenant_id: str,
    dev_issuer: DevIssuerTrust | None = None,
) -> JwtConfig:
    """Token-validation config for the MCP resource: the deployment's cloud and tenant, and the
    MCP audiences ONLY (never the REST API audience)."""
    return JwtConfig.from_settings(
        settings, tenant_id=tenant_id, audiences=mcp.effective_audiences, dev_issuer=dev_issuer
    )


def authorization_server_for(config: JwtConfig) -> str:
    """The Entra v2 issuer (authorization server) of ``config``'s cloud and tenant."""
    for issuer, version in entra_issuers(config.cloud, config.tenant_id).items():
        if version == "2.0":
            return issuer
    raise InvalidSchemaError("no v2 issuer for the configured cloud", reason="config")

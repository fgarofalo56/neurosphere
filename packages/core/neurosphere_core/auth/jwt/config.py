"""Per-cloud issuer, audience and JWKS configuration for Entra access tokens (PRP-06 C3, C4).

Issuers are a fixed per-cloud table keyed by the configured tenant; they are never derived from
a token and never borrowed from the other cloud. Multi-tenant authorities (``common``,
``organizations``, ``consumers``) cannot be configured because the tenant must be a GUID.

A dev issuer (self-signed local JWKS, see ``dev_issuer``) may be configured only when
``NS_ENV=local``; any other environment fails at construction, which is startup.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from neurosphere_core.cloud import CloudName, Settings, profile_for
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue

Env = Literal["local", "dev", "test", "staging", "prod"]
TokenVersion = Literal["1.0", "2.0"]

#: The only signature algorithm accepted (RFC 8725 3.1). The algorithm is pinned from the key.
ALLOWED_ALGORITHMS: Final = frozenset({"RS256"})

DEFAULT_LEEWAY_SECONDS: Final = 60
MAX_LEEWAY_SECONDS: Final = 300

# v1 access-token issuer host per cloud. Commercial is ``sts.windows.net`` (measured from public
# OIDC metadata 2026-10-12). Government's ``/common`` metadata also advertises
# ``sts.windows.net``, which would let a Commercial v1 issuer string pass a Government
# deployment, so Government allowlists only its own STS host. Government v1 issuance is
# unverified until a Government tenant is available (gate OPEN); v2 tokens are the default path.
_V1_ISSUER_HOST: Final = {
    CloudName.COMMERCIAL: "sts.windows.net",
    CloudName.GOVERNMENT: "sts.usgovcloudapi.net",
}

DEV_ISSUER_BASE: Final = "https://dev-issuer.neurosphere.invalid"


def entra_issuers(cloud: CloudName, tenant_id: str) -> dict[str, TokenVersion]:
    """Exact allowlisted issuer strings for ``tenant_id`` in ``cloud``, mapped to token version."""
    login_host = profile_for(cloud).login_host
    return {
        f"https://{login_host}/{tenant_id}/v2.0": "2.0",
        f"https://{_V1_ISSUER_HOST[cloud]}/{tenant_id}/": "1.0",
    }


def entra_jwks_uri(cloud: CloudName, tenant_id: str) -> str:
    """Tenant-specific signing-key endpoint on the cloud's own authority."""
    return f"https://{profile_for(cloud).login_host}/{tenant_id}/discovery/v2.0/keys"


def dev_issuer_for(tenant_id: str) -> str:
    return f"{DEV_ISSUER_BASE}/{tenant_id}/v2.0"


def normalize_tenant_id(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise ValueError(
            "tenant_id must be a tenant GUID (multi-tenant authorities are not allowed)"
        ) from None
    canonical = str(parsed)
    if value.lower() != canonical:
        raise ValueError("tenant_id must be in canonical 8-4-4-4-12 GUID form")
    return canonical


class DevIssuerTrust(BaseModel):
    """Public half of a local dev issuer: its issuer string and JWKS. Local only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer: str
    jwks: Mapping[str, Any]

    @field_validator("issuer")
    @classmethod
    def _issuer_is_dev(cls, value: str) -> str:
        if not value.startswith(f"{DEV_ISSUER_BASE}/"):
            raise ValueError(f"dev issuer must start with {DEV_ISSUER_BASE}/")
        return value


class JwtConfig(BaseModel):
    """Validated, frozen token-validation settings for exactly one cloud and one tenant."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    env: Env
    cloud: CloudName
    tenant_id: str
    audiences: tuple[str, ...] = Field(min_length=1, max_length=8)
    leeway_seconds: int = Field(default=DEFAULT_LEEWAY_SECONDS, ge=0, le=MAX_LEEWAY_SECONDS)
    dev_issuer: DevIssuerTrust | None = None

    @field_validator("tenant_id")
    @classmethod
    def _tenant_guid(cls, value: str) -> str:
        return normalize_tenant_id(value)

    @field_validator("audiences")
    @classmethod
    def _audiences_explicit(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for aud in value:
            if not aud.strip() or aud != aud.strip() or "*" in aud:
                raise ValueError("audiences must be explicit, non-empty and contain no wildcard")
        return value

    @model_validator(mode="after")
    def _dev_issuer_local_only(self) -> Self:
        if self.dev_issuer is not None:
            if self.env != "local":
                raise ValueError("a dev issuer may be configured only when NS_ENV=local")
            if self.dev_issuer.issuer != dev_issuer_for(self.tenant_id):
                raise ValueError("dev issuer must be bound to the configured tenant")
        return self

    @property
    def entra_issuers(self) -> dict[str, TokenVersion]:
        return entra_issuers(self.cloud, self.tenant_id)

    @property
    def jwks_uri(self) -> str:
        return entra_jwks_uri(self.cloud, self.tenant_id)

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        tenant_id: str,
        audiences: tuple[str, ...] | list[str],
        leeway_seconds: int = DEFAULT_LEEWAY_SECONDS,
        dev_issuer: DevIssuerTrust | None = None,
    ) -> JwtConfig:
        """Build from startup settings; any invalid combination raises ``invalid_schema``."""
        try:
            return cls(
                env=settings.env,
                cloud=settings.cloud_profile.cloud,
                tenant_id=tenant_id,
                audiences=tuple(audiences),
                leeway_seconds=leeway_seconds,
                dev_issuer=dev_issuer,
            )
        except ValidationError as exc:
            issues = [
                ValidationIssue("/" + "/".join(str(p) for p in err["loc"]), _value_free(err["msg"]))
                for err in exc.errors(include_input=False, include_url=False)
            ]
            raise InvalidSchemaError(
                "invalid token validation configuration", errors=issues, reason="config"
            ) from None


def _value_free(message: str) -> str:
    # Pydantic messages for our validators are fixed strings; keep them bounded regardless.
    return message[:200]

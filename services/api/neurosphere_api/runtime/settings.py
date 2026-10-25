"""Composition settings, one class per concern (PRP-29 wire contract). Frozen, unknown refused.

* ``NS_AUTH_*`` (:class:`AuthSettings`): the deployment's Entra tenant, REST audiences, customer
  binding, principal pseudonym key and policy container.
* ``NS_STORE_*`` (:class:`StoreSettings`): the Cosmos database (and, outside local, account).
  The emulator endpoint and key keep ``NS_COSMOS_ENDPOINT``/``NS_COSMOS_KEY`` (local only,
  read by ``neurosphere_core.clients``).
* ``NS_CORS_*`` (:class:`CorsSettings`): the optional exact-origin allow-list.

Comma lists (``NS_AUTH_AUDIENCES``, ``NS_CORS_ALLOWED_ORIGINS``) are plain ``a,b`` strings, not
JSON. The shared core ``Settings`` (``NS_ENV``/``NS_CLOUD``) is not extended here.
"""

from __future__ import annotations

from typing import Annotated, Any, Final
from urllib.parse import urlsplit

from neurosphere_core.auth.scope import DEFAULT_POLICY_CONTAINER
from neurosphere_core.stores import DEFAULT_DATABASE
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

__all__ = [
    "LOCAL_DEFAULT_CUSTOMER_ID",
    "AuthSettings",
    "CorsSettings",
    "StoreSettings",
]

#: ``NS_ENV=local`` customer binding when ``NS_AUTH_CUSTOMER_ID`` is unset; equals the synthetic
#: sandbox customer (``sandbox/config.py`` ``DEFAULT_CUSTOMER``; a test pins the equality).
LOCAL_DEFAULT_CUSTOMER_ID: Final = "synthco"


def _split_commas(value: Any) -> Any:
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    return value


class AuthSettings(BaseSettings):
    """``NS_AUTH_*``. Absent values are reported by the authz builder as readiness reasons."""

    model_config = SettingsConfigDict(env_prefix="NS_AUTH_", frozen=True, extra="forbid")

    tenant_id: str | None = None
    audiences: Annotated[tuple[str, ...], NoDecode] = Field(default=(), max_length=8)
    customer_id: str | None = None
    #: HMAC key for principal pseudonyms, delivered by the platform's Key Vault reference.
    pseudonym_key: SecretStr | None = None
    #: The Key Vault secret URI the key was resolved from (``PseudonymKey`` requires it).
    pseudonym_key_reference: str | None = None
    policy_container: str = Field(default=DEFAULT_POLICY_CONTAINER, min_length=1, max_length=255)

    @field_validator("audiences", mode="before")
    @classmethod
    def _comma_audiences(cls, value: Any) -> Any:
        return _split_commas(value)

    @field_validator("tenant_id", "customer_id", "pseudonym_key_reference", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    def resolved_customer_id(self, env: str) -> str | None:
        """The configured customer, the synthetic default when local, else ``None``."""
        if self.customer_id is not None:
            return self.customer_id
        return LOCAL_DEFAULT_CUSTOMER_ID if env == "local" else None


class StoreSettings(BaseSettings):
    """``NS_STORE_*``: where the composed Cosmos stores live."""

    model_config = SettingsConfigDict(env_prefix="NS_STORE_", frozen=True, extra="forbid")

    database: str = Field(default=DEFAULT_DATABASE, min_length=1, max_length=255)
    #: Outside ``NS_ENV=local`` only: the Cosmos account name (managed identity, no key).
    cosmos_account: str | None = None


def _exact_origin(origin: str) -> str:
    if "*" in origin:
        raise ValueError("CORS origins must be exact; wildcards are refused")
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("CORS origins must be http(s)://host[:port]")
    if parts.username is not None or parts.password is not None:
        raise ValueError("CORS origins must carry no userinfo")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("CORS origins must have no path, query or fragment")
    netloc = parts.hostname.lower() if parts.port is None else f"{parts.hostname}:{parts.port}"
    return f"{parts.scheme}://{netloc.lower()}"


class CorsSettings(BaseSettings):
    """``NS_CORS_ALLOWED_ORIGINS``: comma list of exact origins; empty (default) = no CORS."""

    model_config = SettingsConfigDict(env_prefix="NS_CORS_", frozen=True, extra="forbid")

    allowed_origins: Annotated[tuple[str, ...], NoDecode] = Field(default=(), max_length=16)

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _comma_origins(cls, value: Any) -> Any:
        return _split_commas(value)

    @field_validator("allowed_origins")
    @classmethod
    def _exact(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(_exact_origin(origin) for origin in value))

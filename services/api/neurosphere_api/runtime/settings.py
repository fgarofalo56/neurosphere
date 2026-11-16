"""Composition settings, one class per concern (PRP-29 wire contract). Frozen, unknown refused.

* ``NS_AUTH_*`` (:class:`AuthSettings`): the deployment's Entra tenant, REST audiences, customer
  binding, principal pseudonym key and policy container.
* ``NS_STORE_*`` (:class:`StoreSettings`): the Cosmos database (and, outside local, account).
  The emulator endpoint and key keep ``NS_COSMOS_ENDPOINT``/``NS_COSMOS_KEY`` (local only,
  read by ``neurosphere_core.clients``).
* ``NS_CORS_*`` (:class:`CorsSettings`): the optional exact-origin allow-list.
* ``NS_AUDIT_SIEM_*`` (:class:`AuditSiemSettings`): the optional SIEM export sink for audit
  records (``none`` by default; ``stdout`` or a local JSON-lines ``file``).

Comma lists (``NS_AUTH_AUDIENCES``, ``NS_CORS_ALLOWED_ORIGINS``) are plain ``a,b`` strings, not
JSON. The shared core ``Settings`` (``NS_ENV``/``NS_CLOUD``) is not extended here.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self
from urllib.parse import urlsplit

from neurosphere_core.auth.scope import DEFAULT_POLICY_CONTAINER
from neurosphere_core.stores import DEFAULT_DATABASE
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

__all__ = [
    "COSMOS_ACCOUNT_PATTERN",
    "LOCAL_DEFAULT_CUSTOMER_ID",
    "AdmissionSettings",
    "AuditSiemSettings",
    "AuthSettings",
    "CorsSettings",
    "StoreSettings",
]

#: ``NS_ENV=local`` customer binding when ``NS_AUTH_CUSTOMER_ID`` is unset; equals the synthetic
#: sandbox customer (``sandbox/config.py`` ``DEFAULT_CUSTOMER``; a test pins the equality).
LOCAL_DEFAULT_CUSTOMER_ID: Final = "synthco"
#: Azure Cosmos DB account naming: 3 to 44 characters, lowercase letters, digits and hyphens.
COSMOS_ACCOUNT_PATTERN: Final = re.compile(r"[a-z0-9][a-z0-9-]{1,42}[a-z0-9]")


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

    model_config = SettingsConfigDict(
        env_prefix="NS_STORE_", frozen=True, extra="forbid", hide_input_in_errors=True
    )

    database: str = Field(default=DEFAULT_DATABASE, min_length=1, max_length=255)
    #: Outside ``NS_ENV=local`` only: the Cosmos account NAME (managed identity, no key). A URL,
    #: connection string or key is refused at load without echoing it (PRP-51).
    cosmos_account: str | None = None

    @field_validator("cosmos_account", mode="before")
    @classmethod
    def _cosmos_account(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            if COSMOS_ACCOUNT_PATTERN.fullmatch(value):
                return value
        raise ValueError("NS_STORE_COSMOS_ACCOUNT must be a Cosmos account name, not a URL or key")


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


class AdmissionSettings(BaseSettings):
    """``NS_ADMISSION_ENABLED`` and ``NS_ADMISSION_POLICY_FILE`` (PRP-21 round 2).

    Off by default. When enabled with no policy file the conservative default quota applies (and
    a warning is logged); admission is never unlimited.
    """

    model_config = SettingsConfigDict(env_prefix="NS_ADMISSION_", frozen=True, extra="forbid")

    enabled: bool = False
    policy_file: Path | None = None

    @field_validator("policy_file", mode="before")
    @classmethod
    def _blank_path_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class AuditSiemSettings(BaseSettings):
    """``NS_AUDIT_SIEM_SINK`` (``none`` | ``stdout`` | ``file``) and ``NS_AUDIT_SIEM_FILE_PATH``.

    Every sink receives only ``to_siem_event`` output (redacted again at export) and needs no
    network or secret. ``file`` appends JSON lines to a local path and requires the path.
    """

    model_config = SettingsConfigDict(env_prefix="NS_AUDIT_SIEM_", frozen=True, extra="forbid")

    sink: Literal["none", "stdout", "file", "eventhubs"] = "none"
    file_path: Path | None = None
    #: PRP-40: Event Hubs namespace (bare name or a host in this deployment's cloud), hub name
    #: and optional user-assigned managed identity client id. Identity only, never a key.
    eventhubs_namespace: str | None = Field(default=None, max_length=256)
    eventhubs_name: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
    eventhubs_client_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$",
    )

    @field_validator("eventhubs_namespace", "eventhubs_name", "eventhubs_client_id", mode="before")
    @classmethod
    def _blank_eventhubs_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _eventhubs_needs_hub(self) -> Self:
        if self.sink == "eventhubs" and self.eventhubs_name is None:
            raise ValueError("NS_AUDIT_SIEM_SINK=eventhubs requires NS_AUDIT_SIEM_EVENTHUBS_NAME")
        return self

    @field_validator("sink", mode="before")
    @classmethod
    def _normalized_sink(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower() or "none"
        return value

    @field_validator("file_path", mode="before")
    @classmethod
    def _blank_path_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _file_needs_path(self) -> Self:
        if self.sink == "file" and self.file_path is None:
            raise ValueError("NS_AUDIT_SIEM_SINK=file requires NS_AUDIT_SIEM_FILE_PATH")
        return self

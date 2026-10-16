"""Archive settings (env prefix ``NS_ARCHIVE_``). Frozen, unknown fields refused."""

from __future__ import annotations

from typing import Final

from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# A fixed, public, NON-secret key so local runs and tests pseudonymize deterministically.
# It is accepted ONLY when NS_ENV=local; every other environment must supply its own key.
LOCAL_DEV_PSEUDONYM_KEY: Final = SecretStr("neurosphere-local-dev-archive-pseudonym-key")


class ArchiveSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NS_ARCHIVE_", frozen=True, extra="forbid")

    # Blob container for the redacted archive (Azurite locally).
    container: str = Field(default="ns-archive", min_length=3)

    # HMAC key for person-identifier pseudonyms (NS_ARCHIVE_PSEUDONYM_KEY). From a vault
    # reference in non-local environments; never logged (SecretStr).
    pseudonym_key: SecretStr | None = None

    # Non-local only (managed identity): the single storage account this archive writes to.
    storage_account: str | None = None


def resolve_pseudonym_key(settings: ArchiveSettings, *, env: str) -> SecretStr:
    """The configured key, the dev key when ``env == "local"``, else a configuration error."""
    configured = settings.pseudonym_key
    if configured is not None and configured.get_secret_value():
        return configured
    if env == "local":
        return LOCAL_DEV_PSEUDONYM_KEY
    detail = "NS_ARCHIVE_PSEUDONYM_KEY is required unless NS_ENV=local"
    raise InvalidSchemaError(
        detail, errors=[ValidationIssue("/pseudonym_key", detail)], reason="config"
    )

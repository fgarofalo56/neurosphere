"""Interaction content storage and key settings (PRP-102 item 4, clarification 7).

The configuration source is the PRP-99 stored setting ``InteractionCaptureSetting``: the
key-encryption-key provider (``key_vault_key`` or ``local_development``), the Key Vault key
identifier, the content storage account and container and the identity reference. The only
environment variable is ``NS_INTERACTION_LOCAL_KEY_FILE``, the local key path, honoured only
under ``NS_ENV=local``.

* ``key_vault_key`` requires ``kek_uri`` on the deployment's own cloud (``key_host_refused``
  otherwise); there is no weaker fallback (GD-18). An unknown provider is
  ``key_wrap_unavailable``.
* ``local_development`` is refused outside ``NS_ENV=local`` and needs the key path variable.
  The index ``content_ref.kek_uri`` must be a Key Vault key identifier (PRP-99 grammar), so a
  local deployment records the fixed placeholder :func:`local_kek_placeholder` for its cloud;
  it names no real key and is never dereferenced (the envelope header holds the local key id).

Messages name fields and rules, never values.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal
from urllib.parse import urlsplit

from neurosphere_contracts.admin.v1.system_setting import InteractionCaptureSetting

from neurosphere_core.clients.factories import blob_account_url
from neurosphere_core.cloud import CloudName, Settings, load_settings, profile_for
from neurosphere_core.crypto import (
    KEY_HOST_REFUSED,
    KEY_WRAP_UNAVAILABLE,
    EnvelopeError,
    KeyVaultKeyWrapper,
    KeyWrapper,
    LocalFileKeyWrapper,
    TokenProvider,
    default_key_vault_token_provider,
)
from neurosphere_core.crypto.keyvault import VAULT_SUFFIXES
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue

__all__ = [
    "ENV_INTERACTION_LOCAL_KEY_FILE",
    "InteractionSettings",
    "build_key_wrapper",
    "local_kek_placeholder",
]

ENV_INTERACTION_LOCAL_KEY_FILE: Final = "NS_INTERACTION_LOCAL_KEY_FILE"
_LOCAL_PLACEHOLDER_VAULT: Final = "ns-local-dev"
_LOCAL_PLACEHOLDER_KEY: Final = "local-development"
_STORAGE_ACCOUNT: Final = re.compile(
    r"/providers/Microsoft\.Storage/storageAccounts/(?P<name>[a-z0-9]{3,24})$", re.IGNORECASE
)

KekProvider = Literal["key_vault_key", "local_development"]


def _config_error(pointer: str, detail: str) -> InvalidSchemaError:
    return InvalidSchemaError(detail, errors=[ValidationIssue(pointer, detail)], reason="config")


def local_kek_placeholder(cloud: CloudName) -> str:
    """The ``content_ref.kek_uri`` a ``local_development`` deployment records for ``cloud``."""
    host = f"{_LOCAL_PLACEHOLDER_VAULT}{VAULT_SUFFIXES[CloudName(cloud)]}"
    return f"https://{host}/keys/{_LOCAL_PLACEHOLDER_KEY}"


def _vault_on_cloud(kek_uri: str, cloud: CloudName) -> bool:
    host = (urlsplit(kek_uri).hostname or "").lower()
    return host.endswith(VAULT_SUFFIXES[cloud])


@dataclass(frozen=True, slots=True)
class InteractionSettings:
    """Resolved interaction content settings. Holds identifiers only, never a secret."""

    cloud: CloudName
    kek_provider: KekProvider
    #: The configured Key Vault key identifier (``key_vault_key``); ``None`` for local.
    kek_uri: str | None
    #: What the index records as ``content_ref.kek_uri``.
    content_kek_uri: str
    storage_account: str
    content_account_url: str
    content_container: str
    managed_identity_client_id: str | None
    local_key_file: Path | None
    max_content_chars_per_interaction: int

    @classmethod
    def from_setting(
        cls,
        setting: InteractionCaptureSetting,
        cloud: CloudName | str,
        *,
        settings: Settings | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> InteractionSettings:
        cloud_name = CloudName(cloud)
        provider = setting.kek_provider
        local_key_file: Path | None = None
        if provider == "key_vault_key":
            if setting.kek_uri is None:
                raise _config_error("/kek_uri", "kek_uri is required for key_vault_key")
            kek_uri: str | None = setting.kek_uri.root
            if not _vault_on_cloud(kek_uri, cloud_name):
                raise EnvelopeError(KEY_HOST_REFUSED)
            content_kek_uri = kek_uri
        elif provider == "local_development":
            try:
                env = (settings or load_settings()).env
            except Exception:
                env = None  # an unreadable environment is not local
            if env != "local":
                raise _config_error(
                    "/kek_provider", "local_development is available only when NS_ENV=local"
                )
            raw_path = (os.environ if environ is None else environ).get(
                ENV_INTERACTION_LOCAL_KEY_FILE, ""
            )
            if not raw_path.strip():
                raise _config_error(
                    f"/{ENV_INTERACTION_LOCAL_KEY_FILE}",
                    f"{ENV_INTERACTION_LOCAL_KEY_FILE} is required for local_development",
                )
            local_key_file = Path(raw_path)
            kek_uri = None
            content_kek_uri = local_kek_placeholder(cloud_name)
        else:  # open-ended contract value this build does not support
            raise EnvelopeError(KEY_WRAP_UNAVAILABLE)

        match = _STORAGE_ACCOUNT.search(setting.content_storage_account_resource_id.root)
        if match is None:
            raise _config_error(
                "/content_storage_account_resource_id",
                "content_storage_account_resource_id is not a storage account resource id",
            )
        account = match["name"].lower()
        identity = setting.credential
        client_id = (
            identity.managed_identity_client_id if identity.kind == "managed_identity" else None
        )
        return cls(
            cloud=cloud_name,
            kek_provider=provider,
            kek_uri=kek_uri,
            content_kek_uri=content_kek_uri,
            storage_account=account,
            content_account_url=blob_account_url(profile_for(cloud_name), account),
            content_container=setting.content_container,
            managed_identity_client_id=client_id,
            local_key_file=local_key_file,
            max_content_chars_per_interaction=setting.max_content_chars_per_interaction or 65536,
        )


def build_key_wrapper(
    settings: InteractionSettings,
    *,
    token_provider: TokenProvider | None = None,
    env_settings: Settings | None = None,
) -> KeyWrapper:
    """The key wrapper for ``settings``: a Key Vault key, or the local file key (local only)."""
    if settings.kek_provider == "key_vault_key":
        if settings.kek_uri is None:
            raise _config_error("/kek_uri", "kek_uri is required for key_vault_key")
        provider = token_provider or default_key_vault_token_provider(
            settings.cloud, client_id=settings.managed_identity_client_id
        )
        return KeyVaultKeyWrapper(settings.kek_uri, cloud=settings.cloud, token_provider=provider)
    if settings.kek_provider == "local_development":
        if settings.local_key_file is None:
            raise _config_error(
                f"/{ENV_INTERACTION_LOCAL_KEY_FILE}",
                f"{ENV_INTERACTION_LOCAL_KEY_FILE} is required for local_development",
            )
        return LocalFileKeyWrapper(settings.local_key_file, settings=env_settings)
    raise EnvelopeError(KEY_WRAP_UNAVAILABLE)

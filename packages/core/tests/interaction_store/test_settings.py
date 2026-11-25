"""PRP-102 item 4: InteractionSettings from the stored InteractionCaptureSetting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.admin.v1.system_setting import InteractionCaptureSetting
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.crypto import EnvelopeError, KeyVaultKeyWrapper, LocalFileKeyWrapper
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.interactions import (
    ENV_INTERACTION_LOCAL_KEY_FILE,
    InteractionSettings,
    build_key_wrapper,
)
from neurosphere_core.interactions.settings import local_kek_placeholder

from ._support import GOV_KEK_URI, KEK_URI, make_record, new_id

_ACCOUNT = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-ns"
    "/providers/Microsoft.Storage/storageAccounts/nscontent01"
)
_CLIENT_ID = "11111111-2222-3333-4444-555555555555"


def _setting(**overrides: Any) -> InteractionCaptureSetting:
    identity_field = "credential"
    doc: dict[str, Any] = {
        "kek_provider": "key_vault_key",
        "kek_uri": KEK_URI,
        "content_storage_account_resource_id": _ACCOUNT,
        "content_container": "ns-interactions",
        identity_field: {"kind": "managed_identity", "managed_identity_client_id": _CLIENT_ID},
    }
    doc.update(overrides)
    return InteractionCaptureSetting.model_validate(doc)


async def _token() -> str:
    return "unused"


def test_key_vault_key_settings() -> None:
    settings = InteractionSettings.from_setting(_setting(), "commercial")
    assert settings.kek_uri == settings.content_kek_uri == KEK_URI
    assert settings.storage_account == "nscontent01"
    assert settings.content_account_url == "https://nscontent01.blob.core.windows.net/"
    assert settings.content_container == "ns-interactions"
    assert settings.managed_identity_client_id == _CLIENT_ID
    wrapper = build_key_wrapper(settings, token_provider=_token)
    assert isinstance(wrapper, KeyVaultKeyWrapper)


def test_key_vault_key_requires_kek_uri() -> None:
    with pytest.raises(InvalidSchemaError) as caught:
        InteractionSettings.from_setting(_setting(kek_uri=None), CloudName.COMMERCIAL)
    assert caught.value.reason == "config"


@pytest.mark.parametrize(
    ("kek_uri", "cloud"), [(GOV_KEK_URI, "commercial"), (KEK_URI, "government")]
)
def test_vault_must_be_on_the_deployment_cloud(kek_uri: str, cloud: str) -> None:
    with pytest.raises(EnvelopeError) as caught:
        InteractionSettings.from_setting(_setting(kek_uri=kek_uri), cloud)
    assert caught.value.reason == "key_host_refused"
    assert kek_uri not in str(caught.value)


def test_government_account_url() -> None:
    settings = InteractionSettings.from_setting(_setting(kek_uri=GOV_KEK_URI), "government")
    assert settings.content_account_url == "https://nscontent01.blob.core.usgovcloudapi.net/"


def test_local_development_only_under_local(tmp_path: Path) -> None:
    environ = {ENV_INTERACTION_LOCAL_KEY_FILE: str(tmp_path / "kek.bin")}
    setting = _setting(kek_provider="local_development", kek_uri=None)
    with pytest.raises(InvalidSchemaError):
        InteractionSettings.from_setting(
            setting,
            "commercial",
            settings=Settings(env="prod", cloud=CloudName.COMMERCIAL),
            environ=environ,
        )
    local = Settings(env="local")
    with pytest.raises(InvalidSchemaError):
        InteractionSettings.from_setting(setting, "commercial", settings=local, environ={})
    settings = InteractionSettings.from_setting(
        setting, "commercial", settings=local, environ=environ
    )
    assert settings.local_key_file == tmp_path / "kek.bin"
    assert settings.content_kek_uri == local_kek_placeholder(CloudName.COMMERCIAL)
    wrapper = build_key_wrapper(settings, env_settings=local)
    assert isinstance(wrapper, LocalFileKeyWrapper)


@pytest.mark.parametrize("cloud", list(CloudName))
def test_local_placeholder_is_a_valid_content_ref_kek_uri(cloud: CloudName) -> None:
    iid = new_id()
    ref = {
        "pointer": "p",
        "kek_uri": local_kek_placeholder(cloud),
        "algorithm": "aes_256_gcm",
        "ciphertext_sha256": "a" * 64,
        "byte_length": 1,
    }
    make_record(iid, cloud=cloud.value, content_ref=ref)

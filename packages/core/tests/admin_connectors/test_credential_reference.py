"""PRP-42 item 1: credential references are checked as DNS labels on the deployment cloud."""

from __future__ import annotations

import pytest
from neurosphere_core.admin.connectors import (
    check_credential_reference,
    parse_key_vault_secret,
)
from neurosphere_core.errors import InvalidSchemaError

COMMERCIAL = "https://ns-kv.vault.azure.net/secrets/producer-key"
GOVERNMENT = "https://ns-kv.vault.usgovcloudapi.net/secrets/producer-key"
GUID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"


def _kv(uri: str) -> dict[str, str]:
    return {"kind": "key_vault_secret", "secret_uri": uri}


def test_commercial_reference_is_accepted_on_commercial_only() -> None:
    assert check_credential_reference(_kv(COMMERCIAL), "commercial").kind == "key_vault_secret"
    with pytest.raises(InvalidSchemaError) as caught:
        check_credential_reference(_kv(COMMERCIAL), "government")
    assert caught.value.reason == "cross_cloud"


def test_government_reference_is_accepted_on_government_only() -> None:
    assert check_credential_reference(_kv(GOVERNMENT), "government").secret_uri == GOVERNMENT
    with pytest.raises(InvalidSchemaError) as caught:
        check_credential_reference(_kv(GOVERNMENT), "commercial")
    assert caught.value.reason == "cross_cloud"


@pytest.mark.parametrize(
    "uri",
    [
        "https://evil-vault.azure.net/secrets/x",
        "https://vault.azure.net.evil.test/secrets/x",
        "https://a.b.vault.azure.net/secrets/x",
        "https://user:pw@ns-kv.vault.azure.net/secrets/x",
        "https://ns-kv.vault.azure.net:8443/secrets/x",
        "https://ns-kv.vault.azure.net/secrets/x?api-version=7.4",
        "http://ns-kv.vault.azure.net/secrets/x",
        "https://ns-kv.vault.azure.net/keys/x",
    ],
)
def test_lookalike_or_decorated_uris_are_refused_without_echo(uri: str) -> None:
    with pytest.raises(InvalidSchemaError) as caught:
        parse_key_vault_secret(uri, "commercial")
    assert uri not in repr(caught.value.errors) and uri not in str(caught.value)


def test_managed_identity_reference_needs_the_client_id_only() -> None:
    ok = check_credential_reference(
        {"kind": "managed_identity", "managed_identity_client_id": GUID}, "commercial"
    )
    assert ok.managed_identity_client_id == GUID
    with pytest.raises(InvalidSchemaError):
        check_credential_reference({"kind": "managed_identity"}, "commercial")


def test_secret_value_member_does_not_exist() -> None:
    with pytest.raises(InvalidSchemaError) as caught:
        check_credential_reference(
            {"kind": "key_vault_secret", "secret_value": "s3cr3t-value"}, "commercial"
        )
    assert "s3cr3t-value" not in repr([e.detail for e in caught.value.errors or ()])


def test_parse_returns_name_and_optional_version() -> None:
    ref = parse_key_vault_secret(COMMERCIAL + "/" + "a" * 32, "commercial")
    assert ref.name == "producer-key" and ref.version == "a" * 32
    assert "producer-key" not in repr(ref)

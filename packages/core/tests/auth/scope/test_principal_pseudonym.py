"""Pseudonymous principal id = HMAC-SHA256(vault key, tenant id + object id) (C15)."""

from __future__ import annotations

import copy
import hashlib
import hmac
import logging
import pickle

import pytest
from neurosphere_contracts.scope.v1.identity_scope import Principal
from neurosphere_core.auth.scope import PrincipalPseudonymizer, PseudonymKey
from neurosphere_core.cloud import CloudName

from .scope_helpers import (
    KEY_MATERIAL,
    KEY_REFERENCE,
    OBJECT_ID,
    OTHER_TENANT,
    TENANT,
    make_claims,
    make_deriver,
    make_key,
    make_repo,
    pseudonymizer,
)


def test_pseudonym_is_hmac_sha256_of_tenant_and_object_id() -> None:
    expected = hmac.new(KEY_MATERIAL, f"{TENANT}:{OBJECT_ID}".encode(), hashlib.sha256).hexdigest()
    assert pseudonymizer().pseudonym(TENANT, OBJECT_ID) == "p-" + expected


def test_pseudonym_is_stable_and_input_sensitive() -> None:
    p = pseudonymizer()
    base = p.pseudonym(TENANT, OBJECT_ID)
    assert p.pseudonym(TENANT, OBJECT_ID) == base
    assert p.pseudonym(OTHER_TENANT, OBJECT_ID) != base
    assert p.pseudonym(TENANT, OBJECT_ID[:-1] + "0") != base
    other_key = PrincipalPseudonymizer(make_key(bytes(range(1, 33))))
    assert other_key.pseudonym(TENANT, OBJECT_ID) != base


def test_principal_id_is_canonical_and_contract_valid() -> None:
    pid = pseudonymizer().principal_id(
        cloud=CloudName.GOVERNMENT,
        customer_id="agency-x",
        tenant_id=TENANT,
        object_id=OBJECT_ID,
        kind="user",
    )
    pseudonym = pid.rsplit(":", 1)[-1]
    assert pid == f"government:agency-x:entra:person:{pseudonym}"
    Principal.model_validate(
        {"principal_id": pid, "principal_pseudonym": pseudonym, "principal_kind": "user"}
    )
    assert OBJECT_ID not in pid
    assert TENANT not in pid


def test_principal_id_refuses_bad_customer_segment() -> None:
    with pytest.raises(ValueError):
        pseudonymizer().principal_id(
            cloud=CloudName.COMMERCIAL,
            customer_id="Contoso:evil",
            tenant_id=TENANT,
            object_id=OBJECT_ID,
            kind="user",
        )


def test_key_material_is_never_rendered() -> None:
    key = make_key()
    for text in (repr(key), str(key), repr(PrincipalPseudonymizer(key))):
        assert KEY_MATERIAL.hex() not in text
        assert repr(KEY_MATERIAL) not in text
        assert KEY_REFERENCE in text
    with pytest.raises(TypeError):
        pickle.dumps(key)
    with pytest.raises(TypeError):
        copy.copy(key)
    with pytest.raises(TypeError):
        copy.deepcopy(key)


@pytest.mark.parametrize("material", [b"", b"short", bytes(31)])
def test_short_keys_are_refused(material: bytes) -> None:
    with pytest.raises(ValueError):
        PseudonymKey(material, reference=KEY_REFERENCE)


@pytest.mark.parametrize(
    "reference",
    [
        "/etc/neurosphere/pseudonym.key",
        "C:/keys/pseudonym.key",
        "file:///keys/pseudonym.key",
        "http://ns-test-kv.vault.azure.net/secrets/k",
        "https://evil.example.com/secrets/k",
        "https://ns-test-kv.vault.azure.net/keys/k",
        "",
    ],
)
def test_key_reference_must_be_a_vault_secret_uri(reference: str) -> None:
    with pytest.raises(ValueError):
        PseudonymKey(KEY_MATERIAL, reference=reference)


def test_government_vault_reference_is_accepted() -> None:
    key = PseudonymKey(
        KEY_MATERIAL, reference="https://ns-gov-kv.vault.usgovcloudapi.net/secrets/pseudonym-key"
    )
    assert key.reference.endswith("/secrets/pseudonym-key")


def test_pseudonymizer_requires_a_vault_key_object() -> None:
    with pytest.raises(TypeError):
        PrincipalPseudonymizer(KEY_MATERIAL)  # type: ignore[arg-type]


async def test_derivation_logs_no_object_id_or_key(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    scope = await make_deriver(make_repo()).from_verified_claims(make_claims())
    assert scope.to_contract().principal.principal_pseudonym.startswith("p-")
    logged = caplog.text
    assert OBJECT_ID not in logged
    assert KEY_MATERIAL.hex() not in logged

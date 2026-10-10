"""ConnectorManifest rules beyond JSON Schema (``check_connector_manifest``).

Named by the schema description: credential_refs names are unique; no scope or name holds
high-entropy or known-prefix secret material; a vault_ref host matches a supported cloud.
Secret-shaped probe strings are assembled at runtime so the repository secret scanners
never see a literal credential pattern in this file.
"""

from __future__ import annotations

import copy

import pytest
from contract_support import load_schema, schema_errors, valid_cases
from validators import check_connector_manifest, looks_like_secret

SCHEMA = "connectors/v1/connector-manifest.schema.json"
MANIFESTS = {c.file.stem: c.load() for c in valid_cases() if c.schema == SCHEMA}
VAULT = MANIFESTS["write-capable-vault-reference"]


@pytest.mark.parametrize("name", sorted(MANIFESTS))
def test_examples_pass(name: str) -> None:
    assert check_connector_manifest(MANIFESTS[name]) == []


def test_duplicate_credential_names_rejected() -> None:
    doc = copy.deepcopy(VAULT)
    doc["credential_refs"].append(copy.deepcopy(doc["credential_refs"][0]))
    assert schema_errors(SCHEMA, doc) == []  # JSON Schema cannot see it
    assert any("appears 2 times" in p for p in check_connector_manifest(doc))


def test_vault_host_must_match_supported_cloud() -> None:
    doc = copy.deepcopy(VAULT)  # government-only connector
    doc["credential_refs"][0]["vault_ref"] = (
        "https://kv-ns-com01.vault.azure.net/secrets/foundry-client-cert"
    )
    assert schema_errors(SCHEMA, doc) == []
    assert any("commercial vault host" in p for p in check_connector_manifest(doc))
    doc["supported_clouds"] = ["government", "commercial"]
    assert check_connector_manifest(doc) == []


FAKE_PREFIXED = [
    "gh" + "p_" + "fake0123456789abcdefFAKE0123456789ab",
    "x" + "oxb-" + "fake-0000-placeholder",
    "AK" + "IA" + "FAKEFAKEFAKEFAKE",
    "ey" + "J" + "fakeheader",
]
FAKE_HIGH_ENTROPY = "api://app/" + "Zx9" + "Qm4Lr7Tb2Wc8Yh5Kd1Np6"


@pytest.mark.parametrize("value", [*FAKE_PREFIXED, FAKE_HIGH_ENTROPY])
def test_secret_like_scope_rejected(value: str) -> None:
    assert looks_like_secret(value)
    doc = copy.deepcopy(VAULT)
    doc["scopes"] = [value]
    assert schema_errors(SCHEMA, doc) == []  # the scope pattern alone lets it through
    assert any("secret material" in p for p in check_connector_manifest(doc))


@pytest.mark.parametrize(
    "value",
    [
        "https://management.azure.com/.default",
        "https://management.usgovcloudapi.net/.default",
        "api://00000000-0000-0000-0000-000000000000/user_impersonation",
        "Reports.Read.All",
        "client_assertion_cert",
    ],
)
def test_ordinary_scopes_are_not_flagged(value: str) -> None:
    assert not looks_like_secret(value)


def test_no_member_can_hold_a_secret_value() -> None:
    ref = load_schema(SCHEMA)["$defs"]["credential_ref"]
    assert set(ref["properties"]) == {"name", "vault_ref"}
    assert ref["additionalProperties"] is False

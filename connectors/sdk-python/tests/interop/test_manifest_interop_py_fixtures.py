"""Python-produced manifest fixtures: regenerated with ``build_manifest`` and diff-checked.

The committed ``fixtures/*.json`` are what the TypeScript SDK validates in
``connectors/sdk-ts/tests/manifest.interop.test.ts``. Set ``UPDATE_INTEROP_FIXTURES=1`` to
rewrite them after an intentional change.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from neurosphere_connector import build_manifest
from neurosphere_contracts.connectors.v1.connector_manifest import (
    ConnectorManifest,
    CredentialRef,
    Freshness,
    Granularity,
    RateLimit,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _vault_both_clouds() -> ConnectorManifest:
    return build_manifest(
        name="py-vault-demo",
        version="1.2.3",
        capabilities=["usage_reports", "health_reporting"],
        supported_clouds=["commercial", "government"],
        granularity=Granularity(time_grain="hour", subject_level="deployment"),
        freshness=Freshness(typical_delay_ms=300000, max_delay_ms=3600000),
        scopes=["Reports.Read.All"],
        rate_limits=[RateLimit(limit_scope="per_credential", max_requests=100, window_ms=60000)],
        credential_refs=[
            CredentialRef(
                name="api_key", vault_ref="https://demo-vault.vault.azure.net/secrets/api-key"
            ),
            CredentialRef(
                name="gov_key",
                vault_ref="https://demo-gov.vault.usgovcloudapi.net/secrets/gov-key"
                "/0123456789abcdef0123456789abcdef",
            ),
        ],
        documentation_url="https://docs.example.com/connectors/py-vault-demo",
    )


def _managed_identity_unknowns() -> ConnectorManifest:
    return build_manifest(
        name="py-mi-demo",
        version="0.1.0",
        capabilities=["telemetry_ingest"],
        supported_clouds=["commercial"],
        granularity=Granularity(time_grain="unknown", subject_level="unknown"),
    )


def _workload_identity_no_limits() -> ConnectorManifest:
    return build_manifest(
        name="py-wif-demo",
        version="2.0.0-rc.1",
        capabilities=["cost_ingest", "catalog_discovery"],
        supported_clouds=["government"],
        granularity=Granularity(time_grain="day", subject_level="tenant"),
        freshness=Freshness(typical_delay_ms=None, max_delay_ms=86400000),
        rate_limits=[],
        auth_mode="workload_identity_federation",
    )


PY_FIXTURES: dict[str, Callable[[], ConnectorManifest]] = {
    "py-vault-reference-both-clouds": _vault_both_clouds,
    "py-managed-identity-unknowns": _managed_identity_unknowns,
    "py-workload-identity-no-limits": _workload_identity_no_limits,
}


def _render(manifest: ConnectorManifest) -> str:
    doc: dict[str, Any] = manifest.model_dump(mode="json")
    if doc.get("documentation_url") is None:
        doc.pop("documentation_url", None)
    return json.dumps(doc, indent=2) + "\n"


def test_fixture_dir_is_not_empty() -> None:
    assert sorted(p.name for p in FIXTURES.glob("*.json")) == sorted(
        f"{name}.json" for name in PY_FIXTURES
    )


@pytest.mark.parametrize("name", sorted(PY_FIXTURES))
def test_committed_fixture_matches_build_manifest(name: str) -> None:
    path = FIXTURES / f"{name}.json"
    text = _render(PY_FIXTURES[name]())
    if os.environ.get("UPDATE_INTEROP_FIXTURES") == "1":
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.read_text(encoding="utf-8") == text

"""DeploymentManifest rules beyond JSON Schema (``check_deployment_manifest``).

Named by the schema description: each service appears at most once and an
existing_resource_id is not reused across services. Also: cloud is a single scalar, so a
manifest cannot express routing Government data to Commercial (NS-07).
"""

from __future__ import annotations

import copy

import pytest
from contract_support import load_schema, schema_errors, valid_cases
from validators import check_deployment_manifest

SCHEMA = "deployment/v1/deployment-manifest.schema.json"
MANIFESTS = {c.file.stem: c.load() for c in valid_cases() if c.schema == SCHEMA}


@pytest.mark.parametrize("name", sorted(MANIFESTS))
def test_examples_pass(name: str) -> None:
    assert check_deployment_manifest(MANIFESTS[name]) == []


def test_duplicate_service_rejected() -> None:
    doc = copy.deepcopy(MANIFESTS["commercial-aks-fabric-approved"])
    doc["services"].append(copy.deepcopy(doc["services"][0]))
    problems = check_deployment_manifest(doc)
    assert any("appears 2 times" in p for p in problems)


def test_reused_resource_id_rejected_case_insensitively() -> None:
    doc = copy.deepcopy(MANIFESTS["commercial-aks-fabric-approved"])
    reuse = [s for s in doc["services"] if s.get("existing_resource_id")]
    assert reuse, "example needs a reuse decision"
    twin = copy.deepcopy(reuse[0])
    twin["service"] = next(
        name
        for name in load_schema(SCHEMA)["$defs"]["service_plan"]["properties"]["service"]["enum"]
        if name not in {s["service"] for s in doc["services"]}
    )
    twin["existing_resource_id"] = (
        reuse[0]["existing_resource_id"].upper().replace("/SUBSCRIPTIONS/", "/subscriptions/")
    )
    doc["services"].append(twin)
    assert any("existing_resource_id" in p for p in check_deployment_manifest(doc))


def test_cloud_is_a_single_scalar() -> None:
    cloud = load_schema(SCHEMA)["properties"]["cloud"]
    assert cloud["type"] == "string"
    doc = copy.deepcopy(MANIFESTS["government-appservice-synapse-draft"])
    doc["cloud"] = ["government", "commercial"]
    assert schema_errors(SCHEMA, doc)

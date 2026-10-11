"""Shared helpers for the sandbox generator tests (all offline)."""

from __future__ import annotations

import functools
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = REPO_ROOT / "packages" / "contracts" / "schemas"

CATALOG_SCHEMAS = {
    "domains.ndjson": "catalog/v1/domain.schema.json",
    "owners.ndjson": "catalog/v1/owner.schema.json",
    "persons.ndjson": "catalog/v1/person.schema.json",
    "model_deployments.ndjson": "catalog/v1/model_deployment.schema.json",
    "grounding_sources.ndjson": "catalog/v1/grounding_source.schema.json",
    "tools.ndjson": "catalog/v1/tool.schema.json",
    "agents.ndjson": "catalog/v1/agent.schema.json",
    "agent_versions.ndjson": "catalog/v1/agent_version.schema.json",
}
TELEMETRY_SCHEMA = "telemetry/v1/telemetry-event.schema.json"
COST_SCHEMA = "cost/v1/cost-record.schema.json"
DATA_FILES = (*CATALOG_SCHEMAS, "relations.ndjson", "telemetry.ndjson", "cost.ndjson")
ALL_FILES = (
    *DATA_FILES,
    "bad-event-manifest.ndjson",
    "bad-event-manifest.json",
    "anomaly-manifest.json",
    "run-manifest.json",
)


@functools.cache
def _registry() -> Registry:
    resources = []
    for path in SCHEMA_ROOT.glob("*/*/*.schema.json"):
        contents = json.loads(path.read_text(encoding="utf-8"))
        resources.append((contents["$id"], Resource.from_contents(contents, DRAFT202012)))
    return Registry().with_resources(resources)


@functools.cache
def validator(rel: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_ROOT / rel).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=_registry())


def schema_valid(rel: str, doc: Any) -> bool:
    return validator(rel).is_valid(doc)


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def read_json(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return result


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hashes(directory: Path) -> dict[str, str]:
    return {name: sha256_of(directory / name) for name in ALL_FILES}

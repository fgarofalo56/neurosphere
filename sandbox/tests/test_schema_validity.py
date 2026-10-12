"""Tiny profile validates against the generated Pydantic models AND the JSON Schemas."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.catalog.v1 import (
    agent,
    agent_version,
    delegates_to,
    domain,
    grounded_by,
    grounding_source,
    invokes,
    model_deployment,
    owned_by,
    owner,
    person,
    tool,
    uses_model,
)
from neurosphere_contracts.cost.v1.cost_record import CostRecord
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from pydantic import BaseModel, ValidationError

from sandbox.tests.support import (
    CATALOG_SCHEMAS,
    COST_SCHEMA,
    TELEMETRY_SCHEMA,
    read_json,
    read_ndjson,
    schema_valid,
)

CANONICAL = re.compile(
    r"(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+"
)
CATALOG_MODELS: dict[str, type[BaseModel]] = {
    "domains.ndjson": domain.Domain,
    "owners.ndjson": owner.Owner,
    "persons.ndjson": person.Person,
    "model_deployments.ndjson": model_deployment.ModelDeployment,
    "grounding_sources.ndjson": grounding_source.GroundingSource,
    "tools.ndjson": tool.Tool,
    "agents.ndjson": agent.Agent,
    "agent_versions.ndjson": agent_version.AgentVersion,
}
RELATION_MODELS: dict[str, type[BaseModel]] = {
    "invokes": invokes.InvokesRelation,
    "delegates_to": delegates_to.DelegatesToRelation,
    "uses_model": uses_model.UsesModelRelation,
    "grounded_by": grounded_by.GroundedByRelation,
    "owned_by": owned_by.OwnedByRelation,
}


def _walk_ids(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if (
                key
                in {
                    "id",
                    "source_id",
                    "target_id",
                    "domain_id",
                    "agent_id",
                    "principal_id",
                    "canonical_agent_id",
                    "current_version_id",
                }
                and isinstance(value, str)
                and value.count(":") >= 4
            ):
                found.append(value)
            else:
                found.extend(_walk_ids(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk_ids(item))
    return found


@pytest.mark.parametrize("name", sorted(CATALOG_MODELS))
def test_catalog_entities_validate(tiny_dir: Path, name: str) -> None:
    docs = read_ndjson(tiny_dir / name)
    assert docs
    for doc in docs:
        CATALOG_MODELS[name].model_validate(doc)
        assert schema_valid(CATALOG_SCHEMAS[name], doc), doc["id"]


def test_relations_validate_declared_and_inferred(tiny_dir: Path) -> None:
    docs = read_ndjson(tiny_dir / "relations.ndjson")
    statuses = {d["status"] for d in docs}
    assert statuses == {"asserted", "inferred"}
    assert {d["relation_type"] for d in docs} == set(RELATION_MODELS)
    for doc in docs:
        RELATION_MODELS[doc["relation_type"]].model_validate(doc)
        assert schema_valid(f"catalog/v1/{doc['relation_type']}.schema.json", doc), doc["id"]
        if doc["status"] == "inferred":
            assert doc["evidence_ids"], "inferred relations must cite evidence"
            assert doc["provenance"]["method"] == "trace_observation"


def test_canonical_ids_follow_grammar_and_cloud(tiny_dir: Path) -> None:
    for name in (*CATALOG_MODELS, "relations.ndjson", "telemetry.ndjson", "cost.ndjson"):
        for doc in read_ndjson(tiny_dir / name):
            for ident in _walk_ids(doc):
                assert CANONICAL.fullmatch(ident), ident
                assert ident.startswith("commercial:synthco:"), ident


def test_telemetry_valid_events_pass_and_malformed_fail(tiny_dir: Path) -> None:
    manifest = read_ndjson(tiny_dir / "bad-event-manifest.ndjson")
    malformed_lines = {m["line"] for m in manifest if m["kind"] == "malformed"}
    assert malformed_lines, "tiny profile must contain malformed events"
    lines = (tiny_dir / "telemetry.ndjson").read_text(encoding="utf-8").splitlines()
    for n, raw in enumerate(lines, start=1):
        doc = json.loads(raw)
        ok_schema = schema_valid(TELEMETRY_SCHEMA, doc)
        try:
            TelemetryEvent.model_validate(doc)
            ok_model = True
        except ValidationError:
            ok_model = False
        if n in malformed_lines:
            assert not ok_schema and not ok_model, f"line {n} should be invalid"
        else:
            assert ok_schema and ok_model, f"line {n} should be valid"


def test_trace_structure(tiny_dir: Path) -> None:
    docs = read_ndjson(tiny_dir / "telemetry.ndjson")
    kinds = {d.get("span_kind") for d in docs}
    assert {"request", "agent_run", "model_call", "tool_call", "retrieval", "delegation"} <= kinds
    assert {"retry", "error", "cancellation"} & kinds or len(docs) < 5000  # rare events
    assert {d.get("environment") for d in docs} == {"sandbox"}
    valid = [d for d in docs if "trace_id" in d and "span_id" in d]
    spans = {(d["trace_id"], d["span_id"]) for d in valid}
    for d in valid:
        parent = d.get("parent_span_id")
        if parent is not None and re.fullmatch(r"[0-9a-f]{16}", str(parent)):
            assert d["span_id"] != parent
            assert (d["trace_id"], parent) in spans, "parent span must exist in the same trace"


def test_cost_records_validate_and_dedupe_views(tiny_dir: Path) -> None:
    docs = read_ndjson(tiny_dir / "cost.ndjson")
    groups: dict[str, set[str]] = {}
    for doc in docs:
        CostRecord.model_validate(doc)
        assert schema_valid(COST_SCHEMA, doc), doc["cost_id"]
        groups.setdefault(doc["dedupe_key"], set()).add(doc["observation_source"])
        assert isinstance(doc["amount"], str)
    assert {d["kind"] for d in docs} == {"estimated", "invoiced"}
    for views in groups.values():
        assert {"gateway", "application"} <= views
    assert any("billing" in views for views in groups.values())
    for doc in docs:
        if doc["kind"] == "estimated":
            assert doc["price_version"]
        else:
            assert doc["observation_source"] == "billing"


def test_people_are_pseudonymous_only(tiny_dir: Path) -> None:
    allowed = {
        "schema_version",
        "id",
        "entity_type",
        "version",
        "etag",
        "lifecycle_status",
        "created_at",
        "updated_at",
        "cloud",
        "customer_id",
        "principal_pseudonym",
        "pseudonym_scheme",
        "principal_kind",
        "domain_id",
    }
    for doc in read_ndjson(tiny_dir / "persons.ndjson"):
        assert set(doc) <= allowed
        assert re.fullmatch(r"psn_[0-9a-f]{32}", doc["principal_pseudonym"])
    for doc in read_ndjson(tiny_dir / "owners.ndjson"):
        if doc["owner_kind"] == "person":
            assert "display_name" not in doc


def test_run_manifest_counts_match_files(tiny_dir: Path) -> None:
    run = read_json(tiny_dir / "run-manifest.json")
    for name, info in run["files"].items():
        count = len((tiny_dir / name).read_text(encoding="utf-8").splitlines())
        assert info["records"] == count, name
    assert run["cloud"] == "commercial"

"""Curated demo world catalog (PRP-71 item 1): schema validity, completeness, edge integrity."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.catalog.v1 import (
    agent,
    agent_version,
    depends_on,
    domain,
    grounded_by,
    grounding_source,
    invokes,
    mcp_server,
    model_deployment,
    owned_by,
    owner,
    reads,
    service,
    tool,
    uses_model,
    writes,
)
from pydantic import BaseModel

from sandbox.demo.build import OUTPUT_FILES, DemoWorld, build_demo_world, write_demo_world
from sandbox.tests.support import read_ndjson, schema_valid
from sandbox.tests.test_no_legacy_terms import EMAIL, LEGACY, NAME_KEYS, SSN

Doc = dict[str, Any]

ENTITY_MODELS: dict[str, tuple[type[BaseModel], str]] = {
    "domains": (domain.Domain, "domain"),
    "owners": (owner.Owner, "owner"),
    "models": (model_deployment.ModelDeployment, "model_deployment"),
    "sources": (grounding_source.GroundingSource, "grounding_source"),
    "services": (service.Service, "service"),
    "mcp_servers": (mcp_server.McpServer, "mcp_server"),
    "tools": (tool.Tool, "tool"),
    "agents": (agent.Agent, "agent"),
    "agent_versions": (agent_version.AgentVersion, "agent_version"),
}
RELATION_MODELS: dict[str, type[BaseModel]] = {
    "owned_by": owned_by.OwnedByRelation,
    "uses_model": uses_model.UsesModelRelation,
    "invokes": invokes.InvokesRelation,
    "reads": reads.ReadsRelation,
    "writes": writes.WritesRelation,
    "depends_on": depends_on.DependsOnRelation,
    "grounded_by": grounded_by.GroundedByRelation,
}
SEMVER = re.compile(r"\d+\.\d+\.\d+")


@pytest.fixture(scope="module")
def world() -> DemoWorld:
    return build_demo_world("commercial")


def _by_id(docs: list[Doc]) -> dict[str, Doc]:
    return {d["id"]: d for d in docs}


def test_every_document_validates(world: DemoWorld) -> None:
    for attr, (model, schema) in ENTITY_MODELS.items():
        for doc in world.documents(attr):
            model.model_validate(doc)
            assert schema_valid(f"catalog/v1/{schema}.schema.json", doc), (attr, doc["id"])
    for doc in world.relations:
        RELATION_MODELS[doc["relation_type"]].model_validate(doc)
        assert schema_valid(f"catalog/v1/{doc['relation_type']}.schema.json", doc), doc["id"]


def test_government_cloud_builds_and_ids_carry_the_cloud() -> None:
    gov = build_demo_world("government")
    assert all(a["id"].startswith("government:synthco:sandbox:agent:") for a in gov.agents)
    assert {a["residency_region"] for a in gov.agents} == {"usgovvirginia"}


def test_ids_are_unique_and_edges_are_unique(world: DemoWorld) -> None:
    ids = [d["id"] for _, attr in OUTPUT_FILES for d in world.documents(attr)]
    assert len(ids) == len(set(ids))


def test_world_size_minimums(world: DemoWorld) -> None:
    assert len(world.agents) >= 30
    assert len(world.domains) == 4
    assert len(world.services) >= 6
    assert len(world.tools) >= 12
    assert len(world.models) >= 4
    assert len(world.sources) >= 10
    assert {a["domain_id"] for a in world.agents} == {d["id"] for d in world.domains}
    sensitivity = {c for s in world.sources for c in s["sensitivity_categories"]}
    assert {"pii", "phi", "financial"} <= sensitivity
    assert {s["residency_geography"] for s in world.sources} >= {"eu_eea", "united_states"}
    assert len({s["classification"] for s in world.sources}) >= 3


def test_agents_are_complete(world: DemoWorld) -> None:
    owners = _by_id(world.owners)
    owned = {
        r["source_id"]: r["target_id"] for r in world.relations if r["relation_type"] == "owned_by"
    }
    names = [a["display_name"] for a in world.agents]
    assert len(names) == len(set(names))
    for a in world.agents:
        assert a["description"].strip(), a["id"]
        assert a["description"].count(". ") == 0 and a["description"].endswith("."), a["id"]
        assert len(a["tags"]) >= 2, a["id"]
        assert a["capabilities"], a["id"]
        assert a["environment"] != "unknown", a["id"]
        assert owned[a["id"]] in owners, a["id"]
        assert owners[owned[a["id"]]]["owner_kind"] == "team"
    versions = _by_id(world.agent_versions)
    for a in world.agents:
        current = versions[a["current_version_id"]]
        assert SEMVER.fullmatch(current["semver"])
        assert current["agent_id"] == a["id"]
        assert current["capabilities"] == a["capabilities"]


def test_other_entities_carry_metadata(world: DemoWorld) -> None:
    for attr in ("tools", "services", "mcp_servers", "models", "sources"):
        for doc in world.documents(attr):
            assert len(doc["tags"]) >= 1, doc["id"]
            assert doc["environment"] != "unknown", doc["id"]
    for t in world.tools:
        assert t["capabilities"], t["id"]
    mcp_ids = {m["id"] for m in world.mcp_servers}
    for t in world.tools:
        if t["tool_kind"] == "mcp_tool":
            assert t["mcp_server_ref"] in mcp_ids


def test_edge_endpoints_exist_and_never_target_telemetry_only_agents(world: DemoWorld) -> None:
    entities = {d["id"] for attr in ENTITY_MODELS for d in world.documents(attr)}
    shadow = set(world.undeclared_agent_ids)
    assert len(shadow) == 4
    for r in world.relations:
        assert r["source_id"] in entities, r["id"]
        assert r["target_id"] in entities, r["id"]
        assert r["source_id"] not in shadow and r["target_id"] not in shadow
    assert {r["relation_type"] for r in world.relations} == set(RELATION_MODELS)


def test_telemetry_only_agents_absent_from_catalog(world: DemoWorld, tmp_path: Path) -> None:
    write_demo_world(world, tmp_path)
    text = "".join((tmp_path / name).read_text(encoding="utf-8") for name, _ in OUTPUT_FILES)
    for agent_id in world.undeclared_agent_ids:
        assert agent_id not in text
    for a in world.undeclared_agents:
        assert a.name and a.name not in text
        assert a.model_id and a.tool_ids and a.service_ids


def test_a_data_asset_has_two_writer_agents(world: DemoWorld) -> None:
    agent_ids = {a["id"] for a in world.agents}
    writers: dict[str, set[str]] = defaultdict(set)
    for r in world.relations:
        if r["relation_type"] == "writes" and r["source_id"] in agent_ids:
            writers[r["target_id"]].add(r["source_id"])
    assert any(len(w) >= 2 for w in writers.values())


def test_an_eu_pii_asset_has_a_reader(world: DemoWorld) -> None:
    eu_pii = {
        s["id"]
        for s in world.sources
        if s["residency_geography"] == "eu_eea" and "pii" in s["sensitivity_categories"]
    }
    assert eu_pii
    readers = {r["target_id"] for r in world.relations if r["relation_type"] == "reads"}
    assert eu_pii & readers


def test_three_agents_have_two_versions_with_different_capabilities(world: DemoWorld) -> None:
    by_agent: dict[str, list[Doc]] = defaultdict(list)
    for v in world.agent_versions:
        by_agent[v["agent_id"]].append(v)
    differing = [
        agent_id
        for agent_id, vs in by_agent.items()
        if len(vs) == 2 and set(vs[0]["capabilities"]) != set(vs[1]["capabilities"])
    ]
    assert len(differing) >= 3
    for agent_id in differing:
        assert len({v["semver"] for v in by_agent[agent_id]}) == 2


def test_outage_service_has_downstream_and_unrelated_agents(world: DemoWorld) -> None:
    assert world.outage_service_id in {s["id"] for s in world.services}
    downstream = set(world.downstream_agent_ids)
    unrelated = set(world.unrelated_agent_ids)
    assert downstream and unrelated
    assert not downstream & unrelated
    assert downstream | unrelated == {a["id"] for a in world.agents}
    assert len(downstream) >= 4 and len(unrelated) >= 20
    # Transitive via tools adds nothing: every agent using a tool that depends on the outage
    # service also declares the dependency itself, so the downstream set is unambiguous.
    tool_deps = {
        r["source_id"]
        for r in world.relations
        if r["relation_type"] == "depends_on"
        and r["target_id"] == world.outage_service_id
        and r["source_id"].split(":")[3] == "tool"
    }
    via_tools = {
        r["source_id"]
        for r in world.relations
        if r["relation_type"] == "invokes" and r["target_id"] in tool_deps
    }
    assert via_tools <= downstream
    # Several domains are affected, so the incident crosses team boundaries.
    domains = {a["domain_id"] for a in world.agents if a["id"] in downstream}
    assert len(domains) >= 3


def test_two_builds_are_byte_identical(world: DemoWorld, tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    counts = write_demo_world(world, first)
    assert write_demo_world(build_demo_world("commercial"), second) == counts
    for name, _ in OUTPUT_FILES:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name
    assert counts["services.ndjson"] >= 6
    assert counts["agents.ndjson"] >= 30
    assert len(read_ndjson(first / "relations.ndjson")) == counts["relations.ndjson"]


def test_no_legacy_or_personal_terms(world: DemoWorld, tmp_path: Path) -> None:
    write_demo_world(world, tmp_path)
    for name, _ in OUTPUT_FILES:
        text = (tmp_path / name).read_text(encoding="utf-8")
        for label, pattern in (
            ("legacy", LEGACY),
            ("email", EMAIL),
            ("ssn", SSN),
            ("name-key", NAME_KEYS),
        ):
            assert pattern.search(text) is None, (label, name)
    data = Path(__file__).resolve().parents[1] / "demo" / "data"
    for path in data.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert LEGACY.search(text) is None, path.name
        assert EMAIL.search(text) is None, path.name
        assert re.search(r"[0-9a-f]{64}", text) is None, path.name

# pyright: reportMissingImports=false
"""`seed` run twice: the second run creates zero documents and zero events."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sbx_seam import DATABASE, CosmosSeam, HubSeam

from .conftest import cli_json, fresh_event_hubs, run_cli

pytestmark = pytest.mark.integration

CONTAINERS = ("sandbox-entities", "sandbox-relations")


def test_second_seed_creates_nothing(stack: None, data_dir: Path) -> None:
    assert run_cli("reset").returncode == 0
    fresh_event_hubs()
    manifest = json.loads((data_dir / "run-manifest.json").read_text(encoding="utf-8"))
    files = manifest["files"]
    expected_docs = sum(
        files[f]["records"]
        for f in (
            "domains.ndjson",
            "owners.ndjson",
            "persons.ndjson",
            "model_deployments.ndjson",
            "grounding_sources.ndjson",
            "tools.ndjson",
            "agents.ndjson",
            "agent_versions.ndjson",
            "relations.ndjson",
        )
    )
    expected_events = files["telemetry.ndjson"]["records"]
    args = ("seed", "--data-dir", str(data_dir))

    assert HubSeam().event_count() == 0
    first = cli_json(*args)
    cosmos = CosmosSeam()
    docs_after_first = sum(cosmos.count(DATABASE, c) for c in CONTAINERS)
    events_after_first = HubSeam().event_count()
    assert first["documents"]["created"] == expected_docs
    assert docs_after_first == expected_docs
    assert first["events"]["sent"] == expected_events
    assert events_after_first == expected_events

    second = cli_json(*args)
    assert second["documents"] == {"created": 0, "updated": 0, "unchanged": expected_docs}
    assert second["events"]["sent"] == 0
    assert sum(cosmos.count(DATABASE, c) for c in CONTAINERS) == docs_after_first
    assert HubSeam().event_count() == events_after_first


def test_changed_document_is_updated_not_duplicated(stack: None, data_dir: Path) -> None:
    cli_json("seed", "--data-dir", str(data_dir), "--no-events")
    cosmos = CosmosSeam()
    db = cosmos.ensure_database(DATABASE)
    container = cosmos.ensure_container(db, "sandbox-entities")
    doc = next(iter(container.query_items("SELECT * FROM c", enable_cross_partition_query=True)))
    container.upsert_item(
        {**{k: v for k, v in doc.items() if not k.startswith("_")}, "version": 99}
    )
    before = cosmos.count(DATABASE, "sandbox-entities")
    again = cli_json("seed", "--data-dir", str(data_dir), "--no-events")
    assert again["documents"]["updated"] == 1
    assert again["documents"]["created"] == 0
    assert cosmos.count(DATABASE, "sandbox-entities") == before

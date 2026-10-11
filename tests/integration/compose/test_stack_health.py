"""The default emulator services come up healthy and the hub config stays within limits."""

from __future__ import annotations

import json

import pytest

from .conftest import REPO_ROOT, compose

pytestmark = pytest.mark.integration

# eventhubs has no in-container healthcheck (no shell in the image); `eventhubs-health`
# is the sidecar that probes its AMQP port, and eventhubs itself must be running.
DEFAULT_SERVICES = {"cosmos", "azurite", "eventhubs-health"}


def test_default_services_are_healthy(stack: None) -> None:
    result = compose("--profile", "test", "ps", "--format", "json")
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    by_service = {row["Service"]: row for row in rows}
    assert DEFAULT_SERVICES <= set(by_service)
    assert by_service["eventhubs"]["State"] == "running"
    for name in DEFAULT_SERVICES:
        assert by_service[name]["State"] == "running", name
        assert by_service[name]["Health"] == "healthy", name


def test_eventhubs_config_keeps_required_hubs_within_limit() -> None:
    path = REPO_ROOT / "infra" / "compose" / "eventhubs.config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    entities = config["UserConfig"]["NamespaceConfig"][0]["Entities"]
    hubs = {e["Name"]: {g["Name"] for g in e["ConsumerGroups"]} for e in entities}
    assert len(hubs) <= 10
    assert {"normalizer", "aggregates"} <= hubs["telemetry"]
    assert "replay" in hubs["quarantine"]

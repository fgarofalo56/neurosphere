"""The ``demo-world`` generator profile (PRP-71 item 3): layout, manifests, determinism, schemas."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from neurosphere_contracts.cost.v1.cost_record import CostRecord
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent

from sandbox.config import DEMO_PROFILES, PROFILES, BadEventRates, GenerateConfig
from sandbox.generate import generate, main
from sandbox.tests.support import (
    ALL_FILES,
    COST_SCHEMA,
    REPO_ROOT,
    TELEMETRY_SCHEMA,
    read_json,
    read_ndjson,
    schema_valid,
    sha256_of,
    tree_hashes,
)

EXTRA_FILES = ("services.ndjson", "mcp_servers.ndjson", "incident-manifest.json")


def _cfg(seed: int = 1, epoch: str = "2026-10-01T00:00:00Z") -> GenerateConfig:
    return GenerateConfig(
        seed=seed, profile=DEMO_PROFILES["demo-world"], cloud="commercial", epoch=epoch
    )


@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("demo-world")
    generate(_cfg(), out)
    return out


def test_layout_is_the_existing_one_plus_services_and_the_incident_manifest(
    demo_dir: Path,
) -> None:
    for name in (*ALL_FILES, *EXTRA_FILES):
        assert (demo_dir / name).exists(), name
    assert len(read_ndjson(demo_dir / "services.ndjson")) >= 6
    manifest = read_json(demo_dir / "incident-manifest.json")
    assert manifest["kind"] == "sandbox-incident-manifest"
    assert manifest["service_id"].endswith(":service:payments-gateway")
    assert manifest["downstream_agent_ids"]


def test_run_manifest_lists_the_telemetry_only_agents(demo_dir: Path) -> None:
    run = read_json(demo_dir / "run-manifest.json")
    assert run["profile"] == "demo-world"
    undeclared = run["demo_world"]["undeclared_agents"]
    assert len(undeclared) == 4
    agent_ids = {doc["id"] for doc in read_ndjson(demo_dir / "agents.ndjson")}
    assert all(item["agent_id"] not in agent_ids for item in undeclared)
    assert (
        run["demo_world"]["outage_service_id"]
        == read_json(demo_dir / "incident-manifest.json")["service_id"]
    )
    assert run["files"]["services.ndjson"]["records"] == len(
        read_ndjson(demo_dir / "services.ndjson")
    )
    assert run["incident_manifest_file"] == "incident-manifest.json"


def test_same_seed_and_epoch_is_byte_identical(tmp_path: Path) -> None:
    generate(_cfg(), tmp_path / "a")
    generate(_cfg(), tmp_path / "b")
    names = (*ALL_FILES, *EXTRA_FILES)
    assert {n: sha256_of(tmp_path / "a" / n) for n in names} == {
        n: sha256_of(tmp_path / "b" / n) for n in names
    }


def test_identical_across_processes_through_the_cli(tmp_path: Path) -> None:
    for name in ("p1", "p2"):
        subprocess.run(  # noqa: S603 - fixed argv, no shell, our own module
            [
                sys.executable,
                "-m",
                "sandbox.generate",
                "--seed",
                "1",
                "--profile",
                "demo-world",
                "--cloud",
                "commercial",
                "--out",
                str(tmp_path / name),
            ],
            check=True,
            cwd=REPO_ROOT,
            capture_output=True,
        )
    for name in (*ALL_FILES, *EXTRA_FILES):
        assert sha256_of(tmp_path / "p1" / name) == sha256_of(tmp_path / "p2" / name), name
    generate(_cfg(), tmp_path / "api")
    assert sha256_of(tmp_path / "p1" / "telemetry.ndjson") == sha256_of(
        tmp_path / "api" / "telemetry.ndjson"
    )


def test_a_different_epoch_changes_the_output(tmp_path: Path) -> None:
    generate(_cfg(), tmp_path / "a")
    generate(_cfg(epoch="2027-01-01T00:00:00Z"), tmp_path / "b")
    assert sha256_of(tmp_path / "a" / "telemetry.ndjson") != sha256_of(
        tmp_path / "b" / "telemetry.ndjson"
    )


def test_telemetry_and_cost_validate(demo_dir: Path) -> None:
    for doc in read_ndjson(demo_dir / "telemetry.ndjson"):
        TelemetryEvent.model_validate(doc)
        assert schema_valid(TELEMETRY_SCHEMA, doc)
    for doc in read_ndjson(demo_dir / "cost.ndjson"):
        CostRecord.model_validate(doc)
        assert schema_valid(COST_SCHEMA, doc)


def test_bad_event_rates_and_scale_overrides_are_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    for flag in ("--malformed-rate=0.1", "--agents=100"):
        with pytest.raises(SystemExit) as stop:
            main(["--seed", "1", "--profile", "demo-world", "--cloud", "commercial", flag])
        assert stop.value.code == 2
        assert "cannot be combined" in capsys.readouterr().err


def test_existing_profiles_are_untouched(tmp_path: Path) -> None:
    assert set(PROFILES) == {"tiny", "pilot", "custom"}
    generate(GenerateConfig(seed=3, profile=PROFILES["tiny"], cloud="commercial"), tmp_path)
    assert not (tmp_path / "services.ndjson").exists()
    assert not (tmp_path / "incident-manifest.json").exists()
    assert read_json(tmp_path / "run-manifest.json")["profile"] == "tiny"
    assert "demo_world" not in read_json(tmp_path / "run-manifest.json")
    assert set(tree_hashes(tmp_path)) == set(ALL_FILES)
    assert BadEventRates().duplicate > 0  # the default rates still apply to the other profiles

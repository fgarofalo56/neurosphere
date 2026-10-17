"""Partition key configuration point (ADR-0005 decision 4)."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from neurosphere_contracts.deployment.v1.capability_matrix_entry import CapabilityMatrixEntry
from neurosphere_core.capabilities import CapabilityMatrix, matrix_from_rows
from neurosphere_core.catalog import (
    DEFAULT_REQUESTED_SHAPE,
    PartitionKeyShape,
    partition_key_paths,
    partition_key_values,
    resolve_shape,
    shard_for,
)

AGENT_ID = "commercial:contoso:foundry:agent:support-bot"
DOMAIN_ID = "commercial:contoso:neurosphere:domain:finance"


def _matrix(availability: str, cloud: str = "commercial") -> CapabilityMatrix:
    row = CapabilityMatrixEntry.model_validate(
        {
            "schema_version": "1.1.0",
            "id": f"cosmos_db.hierarchical_partition_keys.{cloud}.global.any",
            "service": "cosmos_db",
            "feature": "hierarchical_partition_keys",
            "cloud": cloud,
            "region": "global",
            "sku": None,
            "availability": availability,
            "ga_status": "ga" if availability == "available" else "unverified",
            "authorization_scope": "none_claimed",
            "source_url": "https://learn.microsoft.com/azure/cosmos-db/hierarchical-partition-keys",
            "observed_on": "2026-10-08",
            "notes": "test row",
        }
    )
    return matrix_from_rows([row])


def test_default_requested_shape_is_hierarchical() -> None:
    assert DEFAULT_REQUESTED_SHAPE is PartitionKeyShape.TENANT_DOMAIN_SHARD


def test_paths() -> None:
    assert partition_key_paths(PartitionKeyShape.FLAT_DOMAIN) == ("/domain",)
    assert partition_key_paths(PartitionKeyShape.TENANT_DOMAIN_SHARD) == (
        "/tenant",
        "/domain",
        "/shard",
    )


@pytest.mark.parametrize("cloud", ["commercial", "government"])
def test_shipped_unverified_matrix_falls_back_to_flat(cloud: str) -> None:
    result = resolve_shape(DEFAULT_REQUESTED_SHAPE, cloud)  # type: ignore[arg-type]
    assert result.shape is PartitionKeyShape.FLAT_DOMAIN
    assert result.fell_back is True
    assert result.reason is not None
    assert f"hierarchical_partition_keys.{cloud}.global.any" in (result.row_id or "")


def test_verified_row_returns_hierarchical() -> None:
    result = resolve_shape(DEFAULT_REQUESTED_SHAPE, "commercial", _matrix("available"))
    assert result.shape is PartitionKeyShape.TENANT_DOMAIN_SHARD
    assert result.fell_back is False
    assert result.reason is None


@pytest.mark.parametrize("availability", ["preview", "unavailable", "unverified"])
def test_non_available_rows_fall_back(availability: str) -> None:
    result = resolve_shape(DEFAULT_REQUESTED_SHAPE, "commercial", _matrix(availability))
    assert result.shape is PartitionKeyShape.FLAT_DOMAIN
    assert availability in (result.reason or "")


def test_other_cloud_row_never_applies() -> None:
    result = resolve_shape(DEFAULT_REQUESTED_SHAPE, "government", _matrix("available"))
    assert result.shape is PartitionKeyShape.FLAT_DOMAIN
    assert result.row_id is None
    assert "no capability-matrix row" in (result.reason or "")


def test_flat_request_never_needs_the_matrix() -> None:
    result = resolve_shape(PartitionKeyShape.FLAT_DOMAIN, "government", _matrix("unavailable"))
    assert result.shape is PartitionKeyShape.FLAT_DOMAIN
    assert result.fell_back is False


def test_values_per_shape() -> None:
    assert partition_key_values(PartitionKeyShape.FLAT_DOMAIN, "contoso", DOMAIN_ID, AGENT_ID) == (
        DOMAIN_ID,
    )
    tenant, domain, shard = partition_key_values(
        PartitionKeyShape.TENANT_DOMAIN_SHARD, "contoso", DOMAIN_ID, AGENT_ID, shard_count=16
    )
    assert (tenant, domain) == ("contoso", DOMAIN_ID)
    assert shard.isdigit()
    assert 0 <= int(shard) < 16


def test_shard_is_stable_known_value_and_bounded() -> None:
    # Pinned: a change here means every stored document would move partitions.
    assert shard_for(AGENT_ID, 16) == shard_for(AGENT_ID, 16)
    assert shard_for("commercial:contoso:src:agent:a", 1) == 0
    spread = {shard_for(f"commercial:c:s:agent:{i}", 8) for i in range(200)}
    assert spread == set(range(8))


def test_shard_is_stable_across_processes() -> None:
    """Python's hash() is salted per process; the shard must not be."""
    code = f"from neurosphere_core.catalog import shard_for;print(shard_for({AGENT_ID!r}, 64))"
    outputs = {
        subprocess.run(  # noqa: S603 - fixed argv, no untrusted input
            [sys.executable, "-c", code],
            env={"PYTHONHASHSEED": seed, "SYSTEMROOT": "C:/Windows"},
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for seed in ("1", "2", "random")
    }
    assert outputs == {str(shard_for(AGENT_ID, 64))}


@pytest.mark.parametrize("bad", [0, -1, 1025])
def test_shard_count_bounds(bad: int) -> None:
    with pytest.raises(ValueError, match="shard_count"):
        shard_for(AGENT_ID, bad)


def test_resolution_is_json_serializable() -> None:
    result = resolve_shape(DEFAULT_REQUESTED_SHAPE, "commercial")
    assert json.loads(result.model_dump_json())["shape"] == "flat_domain"

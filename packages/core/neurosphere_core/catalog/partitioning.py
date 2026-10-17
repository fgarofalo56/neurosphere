"""The ONE configuration point for the catalog partition key (ADR-0005 decision 4).

The key shape is PROVISIONAL until the live G03 benchmark closes. Everything that builds a
container definition or a partition-key value goes through this module so the final choice
is a one-line change here (plus a PRP-13 migration for existing containers).

Shapes:

* ``flat_domain``: a single-path key ``/domain``. Always available; the fallback.
* ``tenant_domain_shard``: a hierarchical key ``/tenant``, ``/domain``, ``/shard``. It keeps
  tenant isolation in the key path and lets a hot domain spread across shards. It needs a
  verified capability-matrix row (``cosmos_db`` / ``hierarchical_partition_keys``) for the
  cloud, azure-cosmos >= 4.6, and a NEW container (no in-place conversion).

``resolve_shape`` returns the hierarchical shape only when the matrix row for the cloud is
``available``; any other state (unverified, preview, unavailable, missing row) falls back to
``flat_domain`` with a reason. Nothing is guessed and nothing crosses clouds: only rows of the
requested cloud are consulted.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from neurosphere_core.capabilities import CapabilityMatrix, default_matrix

DEFAULT_SHARD_COUNT = 16
MAX_SHARD_COUNT = 1024
HIERARCHICAL_SERVICE = "cosmos_db"
HIERARCHICAL_FEATURE = "hierarchical_partition_keys"

Cloud = Literal["commercial", "government"]


class PartitionKeyShape(StrEnum):
    """Supported container partition key shapes."""

    FLAT_DOMAIN = "flat_domain"
    TENANT_DOMAIN_SHARD = "tenant_domain_shard"


DEFAULT_REQUESTED_SHAPE = PartitionKeyShape.TENANT_DOMAIN_SHARD
"""PRP-10 clarification 5: hierarchical is requested by default."""

_PATHS: dict[PartitionKeyShape, tuple[str, ...]] = {
    PartitionKeyShape.FLAT_DOMAIN: ("/domain",),
    PartitionKeyShape.TENANT_DOMAIN_SHARD: ("/tenant", "/domain", "/shard"),
}


class ShapeResolution(BaseModel):
    """Outcome of ``resolve_shape``: the effective shape and why."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested: PartitionKeyShape
    shape: PartitionKeyShape
    fell_back: bool
    reason: str | None = None
    row_id: str | None = None
    """Matrix row consulted (None for flat requests or when no row exists)."""


def partition_key_paths(shape: PartitionKeyShape) -> tuple[str, ...]:
    """Container partition key paths for ``shape`` (use when creating a container)."""
    return _PATHS[shape]


def shard_for(canonical_id: str, shard_count: int = DEFAULT_SHARD_COUNT) -> int:
    """Stable shard in ``[0, shard_count)`` from SHA-256 of the ID (never Python ``hash()``)."""
    if not 1 <= shard_count <= MAX_SHARD_COUNT:
        raise ValueError(f"shard_count must be in 1..{MAX_SHARD_COUNT}, got {shard_count}")
    digest = hashlib.sha256(canonical_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % shard_count


def partition_key_values(
    shape: PartitionKeyShape,
    customer_id: str,
    domain_id: str,
    canonical_id: str,
    shard_count: int = DEFAULT_SHARD_COUNT,
) -> tuple[str, ...]:
    """Partition key values for one document, in the order of ``partition_key_paths``.

    ``customer_id``/``domain_id`` must be the server-derived scope values, never caller input.
    The shard is derived from ``canonical_id`` so a document always maps to the same partition.
    """
    if shape is PartitionKeyShape.FLAT_DOMAIN:
        return (domain_id,)
    return (customer_id, domain_id, f"{shard_for(canonical_id, shard_count):04d}")


def resolve_shape(
    requested: PartitionKeyShape,
    cloud: Cloud,
    matrix: CapabilityMatrix | None = None,
) -> ShapeResolution:
    """Effective key shape for ``cloud``.

    Hierarchical is returned only when a ``global`` or ``*`` matrix row for hierarchical
    partition keys in ``cloud`` has ``availability == "available"``. ``matrix`` is injectable
    (tests, what-if); it defaults to the shipped matrix. The shipped rows are currently
    ``unverified``, so the default outcome is a fallback to ``flat_domain``.
    """
    if requested is PartitionKeyShape.FLAT_DOMAIN:
        return ShapeResolution(requested=requested, shape=requested, fell_back=False)
    matrix = matrix if matrix is not None else default_matrix()
    rows = [
        r
        for r in matrix.rows
        if r.service == HIERARCHICAL_SERVICE
        and r.feature == HIERARCHICAL_FEATURE
        and r.cloud == cloud
        and r.region in ("global", "*")
    ]
    if not rows:
        return ShapeResolution(
            requested=requested,
            shape=PartitionKeyShape.FLAT_DOMAIN,
            fell_back=True,
            reason=(
                f"no capability-matrix row for {HIERARCHICAL_SERVICE}.{HIERARCHICAL_FEATURE} "
                f"in {cloud}; unverified, using flat /domain"
            ),
        )
    row = rows[0]
    if row.availability == "available":
        return ShapeResolution(requested=requested, shape=requested, fell_back=False, row_id=row.id)
    return ShapeResolution(
        requested=requested,
        shape=PartitionKeyShape.FLAT_DOMAIN,
        fell_back=True,
        reason=(
            f"row {row.id} availability is {row.availability!r} (source {row.source_url}); "
            "hierarchical keys are not verified available, using flat /domain until G03 "
            "live evidence closes it"
        ),
        row_id=row.id,
    )

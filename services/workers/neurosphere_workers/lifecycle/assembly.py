"""Assemble the lifecycle engine and worker from stores and settings (PRP-23 round 2 item 4).

Pure wiring with no I/O, so it is tested with in-memory stores. ``runtime/factories.py`` builds
the real Cosmos and blob stores and calls :func:`assemble`.

The mode comes from ``NS_LIFECYCLE_MODE`` and defaults to ``dry_run``: the engine decides and
audits but calls no mutating target method. Only ``execute`` deletes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from neurosphere_core.audit import AuditRepository
from neurosphere_core.catalog.lifecycle_delete import CatalogLifecycleBackend, catalog_target
from neurosphere_core.catalog.partitioning import PartitionKeyShape
from neurosphere_core.interactions.blob_content import ContentBackend
from neurosphere_core.interactions.cosmos_index import IndexBackend
from neurosphere_core.interactions.lifecycle_delete import (
    InteractionLifecycleBackend,
    interaction_target,
)
from neurosphere_core.ledger.lifecycle_delete import LedgerLifecycleBackend, ledger_target
from neurosphere_core.lifecycle import LifecycleEngine, TargetRegistry
from neurosphere_core.lifecycle.archive_backend import (
    ArchiveContainer,
    ArchiveLifecycleBackend,
    archive_target,
)
from neurosphere_core.lifecycle.jobs import JobStore
from neurosphere_core.lifecycle.policy import load_policy_file
from neurosphere_core.lifecycle.settings import LifecycleSettings
from neurosphere_core.lifecycle.targets import (
    HoldRegistry,
    PseudonymMappingStore,
    RequestQueue,
)

from neurosphere_workers.lifecycle.job_source import StoreJobSource, outcome_sink
from neurosphere_workers.lifecycle.worker import LifecycleWorker

__all__ = ["LifecycleParts", "assemble", "build_targets"]

logger = logging.getLogger("neurosphere.workers.lifecycle")

Cloud = Literal["commercial", "government"]


@dataclass(frozen=True, slots=True)
class LifecycleParts:
    """The stores one lifecycle worker runs over, all bound to the same customer."""

    jobs: JobStore
    holds: HoldRegistry
    queue: RequestQueue
    mappings: PseudonymMappingStore
    audit: AuditRepository
    targets: TargetRegistry


def build_targets(
    *,
    cloud: str,
    customer_id: str,
    catalog_container: Any | None = None,
    catalog_name: str = "catalog",
    ledger_container: Any | None = None,
    ledger_name: str = "cost-ledger",
    archive_container: ArchiveContainer | None = None,
    archive_name: str = "archive",
    interaction_index: IndexBackend | None = None,
    interaction_blobs: ContentBackend | None = None,
    interaction_name: str = "interaction_index",
) -> TargetRegistry:
    """Register the catalog, ledger, archive and interaction targets that have a store behind them.

    A target whose store is absent is simply not registered, so a request for it fails closed as
    ``unknown_target``. The audit container can never be registered. The interaction target
    (PRP-102, data class ``interaction_content``) needs both its index and its content backend:
    one without the other is a wiring error, because a purge must remove both together.
    """
    registry = TargetRegistry()
    if catalog_container is not None:
        backend = CatalogLifecycleBackend(
            catalog_container,
            shape=PartitionKeyShape.FLAT_DOMAIN,
            cloud=cloud,
            customer_id=customer_id,
        )
        registry.register(catalog_target(catalog_name, backend))
    if ledger_container is not None:
        registry.register(
            ledger_target(
                ledger_name, LedgerLifecycleBackend(ledger_container, customer_id=customer_id)
            )
        )
    if archive_container is not None:
        registry.register(
            archive_target(
                archive_name, ArchiveLifecycleBackend(archive_container, customer_id=customer_id)
            )
        )
    if (interaction_index is None) != (interaction_blobs is None):
        raise ValueError("interaction_index and interaction_blobs are configured together")
    if interaction_index is not None and interaction_blobs is not None:
        registry.register(
            interaction_target(
                interaction_name,
                InteractionLifecycleBackend(
                    interaction_index, interaction_blobs, customer_id=customer_id
                ),
            )
        )
    return registry


def assemble(
    parts: LifecycleParts,
    settings: LifecycleSettings,
    *,
    customer_id: str,
    cloud: Cloud,
    batch_size: int = 50,
) -> tuple[LifecycleEngine, LifecycleWorker]:
    """The engine and the worker that feeds it from the job store and records outcomes."""
    policy = load_policy_file(settings.policy_file)
    engine = LifecycleEngine(
        policy=policy,
        targets=parts.targets,
        holds=parts.holds,
        queue=parts.queue,
        audit=parts.audit,
        audit_chain_id=f"lifecycle.{customer_id}",
        cloud=cloud,
        customer_id=customer_id,
        mappings=parts.mappings,
        mode=settings.mode,
        max_attempts=settings.max_attempts,
    )
    worker = LifecycleWorker(
        engine,
        StoreJobSource(parts.jobs),
        batch_size=batch_size,
        on_outcome=outcome_sink(parts.jobs),
    )
    logger.warning(
        "lifecycle role started",
        extra={
            "event": "worker.lifecycle_mode",
            "mode": engine.mode,
            "policy_status": policy.status,
            "policy_problem": policy.problem,
            "targets": sorted(f"{t.target_kind}:{t.container}" for t in parts.targets.targets()),
        },
    )
    return engine, worker

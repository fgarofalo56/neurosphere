"""Test-only composition of the REAL data builder over in-memory backends (no emulator).

Backends enter through ``CompositionOverrides.backends`` (named after the ``app.state`` key) and
``blob_client``; the test-only token validator comes from the PRP-06 harness and never reaches
production code.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import Any

from authz.authz_helpers import FakeClock  # pyright: ignore[reportMissingImports]
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import BuilderSpec, default_builders
from neurosphere_core.aggregates import InMemoryAggregateStore
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.catalog.repo.memory import InMemoryCatalogRepository
from neurosphere_core.catalog.review_queue import InMemoryReviewQueue
from neurosphere_core.evaluation.store import InMemoryEvaluationStore
from neurosphere_core.hitl import (
    DecisionLog,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewPolicyRegistry,
)
from neurosphere_core.ledger import InMemoryLedgerStore
from neurosphere_core.recommendations import InMemoryRecommendationStore
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    configured_overrides,
    stub_builder,
)

__all__ = [
    "BACKEND_OF",
    "EmptyContainer",
    "builders_with_real_data",
    "data_overrides",
]

#: Component -> the override that satisfies it (``blob_client`` is a field, the rest backends).
BACKEND_OF: dict[str, str] = {
    "catalog": "catalog_repository",
    "aggregates": "aggregate_reader",
    "ledger": "ledger_store",
    "evaluation": "evaluation_store",
    "recommendations": "recommendation_store",
    "audit": "audit_repository",
    "replay": "blob_client",
}


class _NoReviewers:
    async def can_review(self, *_args: Any, **_kwargs: Any) -> bool:
        return False


class EmptyContainer:
    """The aio ``ContainerClient`` slice the archive reader uses, over an empty archive."""

    def list_blobs(self, name_starts_with: str | None = None, **kwargs: Any) -> AsyncIterator[Any]:
        async def _empty() -> AsyncIterator[Any]:
            return
            yield  # pragma: no cover - makes this an async generator

        return _empty()

    async def download_blob(self, blob: str, **kwargs: Any) -> Any:
        raise AssertionError("an empty archive has nothing to download")


def builders_with_real_data() -> tuple[BuilderSpec, ...]:
    """Default order; the REAL data builder; planes stubbed ``ok`` (item 8 owns them)."""
    return tuple(
        stub_builder("stub-planes", spec.components) if spec.name == "planes" else spec
        for spec in default_builders()
    )


def data_overrides(
    clock: FakeClock, *, without: Iterable[str] = (), **extra: Any
) -> CompositionOverrides:
    """The configured authz overrides plus an in-memory backend for every data component.

    ``without`` lists components whose backend is left out (no Cosmos client is configured, so
    that component then reports ``cosmos_unconfigured``).
    """
    audit = AuditRepository(InMemoryAuditStore())
    backends: dict[str, object] = {
        "catalog_repository": InMemoryCatalogRepository(),
        "catalog_review_queue": InMemoryReviewQueue(),
        "aggregate_reader": InMemoryAggregateStore(),
        "ledger_store": InMemoryLedgerStore(),
        "evaluation_store": InMemoryEvaluationStore(),
        "recommendation_store": InMemoryRecommendationStore(),
        "audit_repository": audit,
        "hitl_service": HitlService(
            InMemoryHitlStore(),
            DecisionLog(audit, InMemoryDecisionStore()),
            audit,
            ReviewPolicyRegistry(),
            _NoReviewers(),
        ),
    }
    skipped = set(without)
    for component in skipped:
        backends.pop(BACKEND_OF[component], None)
    blob: object | None = None if "replay" in skipped else EmptyContainer()
    return configured_overrides(clock, backends=backends, blob_client=blob, **extra)

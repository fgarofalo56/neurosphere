"""Stand-ins that let the real role builders run without Cosmos, blob storage or Azure."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from neurosphere_core.catalog.protocol import AliasKey
from neurosphere_core.cloud import Settings
from neurosphere_workers.projections.catalog import (
    InMemoryTraceEventSource,
    LoadedEvent,
    ProjectionStats,
)
from neurosphere_workers.projections.outbox import (
    InMemoryCheckpointStore,
    InMemoryOutboxStore,
    OutboxEntry,
    OutboxReader,
)
from neurosphere_workers.runtime import factories
from neurosphere_workers.runtime.factories import RuntimeConfig
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings

from .fakes import CUSTOMER

WORKER_SCOPE = SimpleNamespace(cloud="commercial", customer_id=CUSTOMER, who="worker")


def config() -> RuntimeConfig:
    return RuntimeConfig(
        Settings(env="local"),
        WorkerSettings(),
        StoreSettings(),
        AuthSettings(),  # type: ignore[arg-type]
    )


class FakeScopes:
    def __init__(self) -> None:
        self.gets = 0

    async def get(self) -> Any:
        self.gets += 1
        return WORKER_SCOPE


class FakeRepo:
    """``CosmosCatalogRepository`` stand-in: only ``resolve_alias``, recording the scope."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.error: Exception | None = None
        self.scopes_seen: list[Any] = []

    async def resolve_alias(self, scope: Any, key: AliasKey) -> str | None:
        self.scopes_seen.append(scope)
        if self.error is not None:
            raise self.error
        return self.values.get(key.alias_value)


class RecordingProjection:
    """Stands in for ``AggregateProjection`` / ``CatalogProjection``: keeps its constructor
    arguments and reads the event through the source it was given, as the real handlers do."""

    instances: ClassVar[list[RecordingProjection]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.stats = ProjectionStats()
        self.seen: list[LoadedEvent | None] = []
        type(self).instances.append(self)

    @property
    def source(self) -> Any:
        return self.kwargs.get("events") or self.kwargs.get("source")

    async def handle(self, entry: OutboxEntry) -> None:
        self.seen.append(await self.source.get_event(entry.customer_id, entry.ref_id))

    async def prune(self, customer_id: str) -> None:
        return None


class TickHolder:
    """What ``_tick_role`` returns here: keeps the tick so a test can run one drain."""

    def __init__(self, name: str, tick: Callable[[], Any]) -> None:
        self.name = name
        self.tick = tick

    async def run(self) -> None:
        return None

    def request_shutdown(self) -> None:
        return None


class Rig:
    def __init__(self) -> None:
        self.repo = FakeRepo()
        self.scopes = FakeScopes()
        self.inner = InMemoryTraceEventSource()
        self.outbox = InMemoryOutboxStore()
        self.checkpoints = InMemoryCheckpointStore()
        self.resolving_calls: list[tuple[str, Any, Any]] = []

    def reader(self) -> OutboxReader:
        return OutboxReader(self.outbox, self.checkpoints)


def install(monkeypatch: pytest.MonkeyPatch) -> Rig:
    rig = Rig()
    RecordingProjection.instances = []

    async def cosmos(*_a: Any, **_k: Any) -> object:
        return object()

    async def prices(*_a: Any, **_k: Any) -> list[Any]:
        return []

    container_db = SimpleNamespace(get_container_client=lambda _name: object())
    stub: Any = lambda *_a, **_k: object()  # noqa: E731
    patches: dict[str, Any] = {
        "_cosmos": cosmos,
        "_database": lambda _cfg, _client: container_db,
        "build_policy_stack": stub,
        "build_identity": lambda *_a, **_k: SimpleNamespace(scope_provider=rig.scopes),
        "CosmosCatalogRepository": lambda _container: rig.repo,
        "_archive_container": stub,
        "ArchiveReader": stub,
        "ArchiveTraceEventSource": lambda _reader: rig.inner,
        "CosmosReviewQueue": SimpleNamespace(from_client=stub),
        "CosmosCandidateQuarantine": SimpleNamespace(from_client=stub),
        "wrap_catalog_for_search": lambda _c, _p, _l, repo: repo,
        "CatalogProjection": RecordingProjection,
        "AggregateProjection": RecordingProjection,
        "CosmosAggregateStore": stub,
        "CosmosLedgerStore": stub,
        "StoreLedgerSource": stub,
        "_list_price_snapshots": prices,
        "_outbox_reader": lambda _db: rig.reader(),
        "_tick_role": lambda name, tick, _cfg: TickHolder(name, tick),
    }
    for name, value in patches.items():
        monkeypatch.setattr(factories, name, value)
    return rig


def entry(doc_id: str = "d1") -> OutboxEntry:
    return OutboxEntry(id=doc_id, customer_id=CUSTOMER, kind="event", ref_id=doc_id, entity="event")

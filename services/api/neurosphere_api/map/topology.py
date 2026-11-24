"""Live-map topology change source (PRP-74 item 4).

``TopologySource`` answers one question for the realtime gateway: did the nodes or edges a scope
can see in one domain change since this session last looked? It scans the in-scope viewport
entity types and the domain's edges (bounded by ``NS_MAP_TOPOLOGY_SCAN_PAGES`` pages of 500) into
a :class:`TopologySnapshot` and :func:`diff_snapshots` turns two snapshots into a
``MapTopologyChange`` notice (ids only; the client refetches the viewport).

Isolation: a snapshot is cached under ``scope_cache_key(scope, namespace="map-topology")`` plus
the domain, so two scopes never share one. Every scan is made WITH the caller's scope, and the
result is re-checked for customer and domain, so an id the scope cannot read is never in a
snapshot, a fingerprint or a notice. One scan per key per half poll interval is shared by every
session with that key (single flight); the cache has a TTL and an entry cap.

Person nodes count toward the fingerprint but their ids are never published: the viewport shows
a pseudonym, not the canonical id, so the id would be useless to a client and is not its to see.
Edges whose endpoints are not both scanned entities are dropped, as the viewport drops them.
"""

import asyncio
import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Literal

from neurosphere_contracts.catalog.v1.model_deployment import ModelDeployment
from neurosphere_contracts.map.v1.map_topology_change import MapTopologyChange
from neurosphere_core.catalog import CatalogEntity, CatalogRepository, EntityFilter
from neurosphere_core.catalog.protocol import EdgeFilter
from neurosphere_core.paging import PageRequest
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz.cache_key import scope_cache_key
from neurosphere_api.map.service import VIEWPORT_ENTITY_TYPES, model_deployment_ids
from neurosphere_api.map.settings import MapSettings

__all__ = [
    "CACHE_NAMESPACE",
    "MAX_CHANGE_IDS",
    "TopologySnapshot",
    "TopologySource",
    "diff_snapshots",
]

CACHE_NAMESPACE: Final = "map-topology"
MAX_CHANGE_IDS: Final = 50
_CACHE_MAX_ENTRIES: Final = 1024
_PAGE: Final = 500
_LIVE: Final = ("draft", "active", "deprecated")
ChangeKind = Literal[
    "node_added", "node_removed", "node_updated", "edge_added", "edge_removed", "edge_updated"
]


def _raw(value: Any) -> Any:
    return getattr(value, "root", value)


@dataclass(frozen=True)
class TopologySnapshot:
    """What one scope saw in one domain at one moment (immutable, shared by reference)."""

    fingerprint: str
    nodes: dict[str, tuple[int, bool]]
    """entity id -> (entity version, is_person)."""
    edges: dict[str, tuple[str, int]]
    """edge id -> (status, version)."""
    models: tuple[ModelDeployment, ...] = ()

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def model_ids(self, provider: str, model_name: str) -> list[str]:
        """Ids of the in-scope deployments of one model (the viewport's model node ids)."""
        return model_deployment_ids(self.models, provider, model_name)


def _fingerprint(nodes: dict[str, tuple[int, bool]], edges: dict[str, tuple[str, int]]) -> str:
    digest = hashlib.sha256()
    digest.update(f"n={len(nodes)};e={len(edges)}\n".encode())
    for entity_id in sorted(nodes):
        digest.update(f"N|{entity_id}|{nodes[entity_id][0]}\n".encode())
    for edge_id in sorted(edges):
        status, version = edges[edge_id]
        digest.update(f"E|{edge_id}|{status}|{version}\n".encode())
    return digest.hexdigest()


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def diff_snapshots(
    previous: TopologySnapshot, current: TopologySnapshot, domain_id: str, now: datetime
) -> MapTopologyChange | None:
    """The notice for ``previous`` -> ``current``, or ``None`` when nothing changed."""
    if previous.fingerprint == current.fingerprint:
        return None
    kinds: list[ChangeKind] = []
    ids: list[str] = []
    total = 0

    def collect(kind: ChangeKind, changed: list[str], published: Callable[[str], bool]) -> None:
        nonlocal total
        if not changed:
            return
        kinds.append(kind)
        total += len(changed)
        ids.extend(i for i in sorted(changed) if published(i))

    def node_public(entity_id: str) -> bool:
        node = current.nodes.get(entity_id) or previous.nodes.get(entity_id)
        return node is not None and not node[1]

    old_n, new_n = previous.nodes, current.nodes
    collect("node_added", [i for i in new_n if i not in old_n], node_public)
    collect("node_removed", [i for i in old_n if i not in new_n], node_public)
    collect("node_updated", [i for i in new_n if i in old_n and new_n[i] != old_n[i]], node_public)
    old_e, new_e = previous.edges, current.edges
    collect("edge_added", [i for i in new_e if i not in old_e], lambda _: True)
    collect("edge_removed", [i for i in old_e if i not in new_e], lambda _: True)
    collect(
        "edge_updated", [i for i in new_e if i in old_e and new_e[i] != old_e[i]], lambda _: True
    )
    if not kinds:
        return None  # a fingerprint collision cannot happen, but never emit an empty notice
    return MapTopologyChange.model_validate(
        {
            "domain_id": domain_id,
            "changed_at": _iso(now),
            "change_kinds": kinds,
            "entity_ids": ids[:MAX_CHANGE_IDS],
            "refetch": True,
            "truncated": total > MAX_CHANGE_IDS,
        }
    )


@dataclass
class _Entry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    fetched_at: float = 0.0
    snapshot: TopologySnapshot | None = None


class TopologySource:
    """Scoped, cached topology snapshots for the realtime gateway."""

    def __init__(
        self,
        repository: CatalogRepository,
        settings: MapSettings,
        *,
        clock: Callable[[], float],
        max_entries: int = _CACHE_MAX_ENTRIES,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._clock = clock
        self._ttl = settings.topology_poll_seconds / 2
        self._evict_after = settings.topology_poll_seconds * 10
        self._max_entries = max_entries
        self._cache: dict[str, _Entry] = {}

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    @staticmethod
    def cache_key(scope: IdentityScope, domain_id: str) -> str:
        return f"{scope_cache_key(scope, namespace=CACHE_NAMESPACE)}|{domain_id}"

    async def snapshot(self, scope: IdentityScope, domain_id: str) -> TopologySnapshot:
        """The current snapshot for (scope, domain); one scan per key per TTL (single flight)."""
        key = self.cache_key(scope, domain_id)
        entry = self._entry(key)
        async with entry.lock:
            now = self._clock()
            fresh = entry.snapshot is not None and 0 <= now - entry.fetched_at < self._ttl
            if fresh and entry.snapshot is not None:
                return entry.snapshot
            snapshot = await self._scan(scope, domain_id)
            entry.snapshot = snapshot
            entry.fetched_at = now
            return snapshot

    def _entry(self, key: str) -> _Entry:
        now = self._clock()
        for stale in [
            k
            for k, e in self._cache.items()
            if e.snapshot is not None
            and not e.lock.locked()
            and not 0 <= now - e.fetched_at < self._evict_after
        ]:
            del self._cache[stale]
        entry = self._cache.pop(key, None) or _Entry()
        self._cache[key] = entry  # re-insert last: dict order is recency
        while len(self._cache) > self._max_entries:
            del self._cache[next(iter(self._cache))]
        return entry

    async def _scan(self, scope: IdentityScope, domain_id: str) -> TopologySnapshot:
        allowed = set(scope.allowed_domains)
        found: list[CatalogEntity] = []
        if domain_id in allowed:
            flt = EntityFilter.model_validate(
                {
                    "entity_types": list(VIEWPORT_ENTITY_TYPES),
                    "domain_ids": [domain_id],
                    "lifecycle_statuses": list(_LIVE),
                }
            )
            cursor: str | None = None
            for _ in range(self._settings.topology_scan_pages):
                page = await self._repository.list_entities(
                    scope, flt, PageRequest(page_size=_PAGE, cursor=cursor)
                )
                found.extend(self._readable(page.items, scope, domain_id))
                cursor = page.next_cursor
                if cursor is None:
                    break
        nodes = {e.id: (int(_raw(e.version)), e.entity_type == "person") for e in found}
        edges = await self._scan_edges(scope, domain_id, set(nodes)) if nodes else {}
        return TopologySnapshot(
            fingerprint=_fingerprint(nodes, edges),
            nodes=nodes,
            edges=edges,
            models=tuple(e for e in found if isinstance(e, ModelDeployment)),
        )

    @staticmethod
    def _readable(
        items: Sequence[CatalogEntity], scope: IdentityScope, domain_id: str
    ) -> list[CatalogEntity]:
        # The repository filters by scope and domain; this re-checks both (defence in depth).
        return [
            e
            for e in items
            if getattr(getattr(e, "domain_id", None), "root", None) == domain_id
            and e.customer_id.root == scope.customer_id
        ]

    async def _scan_edges(
        self, scope: IdentityScope, domain_id: str, node_ids: set[str]
    ) -> dict[str, tuple[str, int]]:
        edges: dict[str, tuple[str, int]] = {}
        cursor: str | None = None
        for _ in range(self._settings.topology_scan_pages):
            page = await self._repository.list_edges_by_domain(
                scope, domain_id, EdgeFilter(), PageRequest(page_size=_PAGE, cursor=cursor)
            )
            for edge in page.items:
                if _raw(edge.source_id) in node_ids and _raw(edge.target_id) in node_ids:
                    edges[str(_raw(edge.id))] = (str(_raw(edge.status)), int(_raw(edge.version)))
            cursor = page.next_cursor
            if cursor is None:
                break
        return edges

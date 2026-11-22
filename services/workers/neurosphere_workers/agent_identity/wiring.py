"""Pieces the worker role factories need to resolve agent identity (PRP-137 item 6).

Kept out of ``runtime/factories.py`` so that file only gains wiring lines. Nothing here reads
the event for scope: the lookup scope is the worker's server-derived one.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Final

from neurosphere_core.agent_identity import (
    AgentIdentityResolver,
    AgentIdentitySettings,
    CatalogAliasLookup,
)
from neurosphere_core.catalog.protocol import AliasKey, CatalogRepository
from neurosphere_core.scope import IdentityScope

from neurosphere_workers.projections.catalog.scope import ScopeProvider
from neurosphere_workers.runtime.supervisor import RoleRunnable

__all__ = [
    "CountersRole",
    "LazyScopeProvider",
    "ScopedAliasLookup",
    "build_agent_identity_resolver",
]

_MAX_ENTRIES: Final = 10_000


class LazyScopeProvider:
    """A ``ScopeProvider`` whose underlying provider is built on first use."""

    def __init__(self, build: Callable[[], ScopeProvider]) -> None:
        self._build = build
        self._provider: ScopeProvider | None = None

    async def get(self) -> IdentityScope:
        if self._provider is None:
            self._provider = self._build()
        return await self._provider.get()


class ScopedAliasLookup:
    """``AliasLookup`` over the catalog in the worker's own scope.

    The scope comes from the worker's ``ScopeProvider`` (derived from its workload identity and
    cached by the provider), read on every lookup; it is never taken from an event.
    """

    def __init__(self, repo: CatalogRepository, scopes: ScopeProvider) -> None:
        self._repo = repo
        self._scopes = scopes

    async def lookup(self, key: AliasKey) -> str | None:
        scope = await self._scopes.get()
        return await CatalogAliasLookup(self._repo, lambda: scope).lookup(key)


def build_agent_identity_resolver(
    repo: CatalogRepository,
    scopes: ScopeProvider,
    *,
    settings: AgentIdentitySettings | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> AgentIdentityResolver:
    """One resolver (and so one cache and one set of counters) per worker role."""
    config = settings or AgentIdentitySettings()
    return AgentIdentityResolver(
        ScopedAliasLookup(repo, scopes),
        clock=clock,
        positive_ttl_seconds=config.positive_ttl_seconds,
        negative_ttl_seconds=config.negative_ttl_seconds,
        max_entries=_MAX_ENTRIES,
    )


class CountersRole:
    """A role runnable that also exposes counters for the worker status surface.

    ``counters()`` returns counter names to integers only (no ids, no content).
    """

    def __init__(self, inner: RoleRunnable, counters: Callable[[], dict[str, int]]) -> None:
        self._inner = inner
        self._counters = counters

    def counters(self) -> dict[str, int]:
        return self._counters()

    async def run(self) -> None:
        await self._inner.run()

    def request_shutdown(self) -> None:
        self._inner.request_shutdown()

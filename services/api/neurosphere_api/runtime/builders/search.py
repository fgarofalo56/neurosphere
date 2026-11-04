"""Catalog search composition (PRP-35 item 3): ``NS_SEARCH_*``.

Called by the data builder (``data._catalog``); it is a helper, not a ``BuilderSpec``, so it adds
no component and no entry to the fixed builder order.

======================  ===========================================================================
``NS_SEARCH_PROVIDER``  unset: no search is composed; ``catalog_graph.search`` fails closed with
                        503 ``search_unavailable`` (behaviour unchanged).
                        ``fixture``: in-process BM25 index fed from the catalog.
                        ``azure``: Azure AI Search behind ``FallbackAuthorizedSearch``; the
                        in-process fixture answers (and Azure is never called) while the capability
                        matrix row ``ai_search.base`` is not supported for the deployment cloud and
                        ``NS_SEARCH_REGION``, or no service is configured.
``NS_SEARCH_SERVICE``   Azure AI Search service name (host comes from the cloud profile only).
``NS_SEARCH_INDEX``     index name (default ``neurosphere-catalog``; created by IaC/operator).
``NS_SEARCH_REGION``    deployment region used for the capability lookup.
``NS_SEARCH_REFRESH_SECONDS``  per-scope re-index interval (default 30).
======================  ===========================================================================

Freshness: the indexer enumerates the catalog only **with the calling principal's own scope**
(there is no unscoped listing), so the index is refreshed lazily at search time, per scope, at most
every ``NS_SEARCH_REFRESH_SECONDS``, and immediately after ``SearchRuntime.invalidate()`` (call it
after a catalog write). Every hit is then re-fetched through the repository with the caller's
scope (``RepositoryGraphQuery.search``), and the search implementations filter by scope before
ranking; this module adds no unfiltered query path. Authentication to Azure is
``DefaultAzureCredential`` (managed identity) only; there is no key or connection string.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal

from azure.identity.aio import DefaultAzureCredential
from neurosphere_core.capabilities import CapabilityResult
from neurosphere_core.catalog import CatalogRepository
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.protocol import GraphQuery, GraphResult, GraphSearchRequest
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.azure import (
    AzureAuthorizedSearch,
    FallbackAuthorizedSearch,
    azure_search_capability,
)
from neurosphere_core.search.azure.client import create_search_client
from neurosphere_core.search.indexer import (
    AzureIndexSink,
    CatalogIndexer,
    CompositeIndexSink,
    FixtureSearchStore,
    IndexSink,
)
from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from neurosphere_api.runtime.builders import BuildContext, ComponentUnavailableError

__all__ = [
    "IndexedGraphQuery",
    "SearchRuntime",
    "SearchSettings",
    "build_catalog_graph",
]

_log = logging.getLogger("neurosphere_api.runtime.search")
_SCOPE_CACHE_LIMIT: Final = 1024


class SearchSettings(BaseSettings):
    """``NS_SEARCH_*``. Unset provider means no search is composed."""

    model_config = SettingsConfigDict(env_prefix="NS_SEARCH_", frozen=True, extra="forbid")

    provider: Literal["fixture", "azure"] | None = None
    service: str | None = None
    index: str = "neurosphere-catalog"
    region: str | None = None
    refresh_seconds: float = 30.0

    @field_validator("provider", "service", "region", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


@dataclass(frozen=True, slots=True)
class SearchRuntime:
    """What is composed; published on ``app.state.search_runtime`` for status and write hooks."""

    provider: Literal["fixture", "azure"]
    azure_enabled: bool
    #: Why Azure is not serving (None when it is, or when the provider is ``fixture``).
    disabled_reason: str | None
    indexer: CatalogIndexer
    _invalidate: Callable[[], None]

    def invalidate(self) -> None:
        """Re-index on the next search of every scope (call after a catalog write)."""
        self._invalidate()


class IndexedGraphQuery(RepositoryGraphQuery):
    """``RepositoryGraphQuery`` that refreshes the index (scoped to the caller) before searching."""

    def __init__(
        self,
        repository: CatalogRepository,
        search: Any,
        indexer: CatalogIndexer,
        *,
        refresh_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(repository, search)
        self._indexer = indexer
        self._refresh_seconds = refresh_seconds
        self._clock = clock
        self._fresh_until: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def invalidate(self) -> None:
        self._fresh_until.clear()

    async def _sync(self, scope: IdentityScope) -> None:
        # scope_hash is a content hash in production; the domains make the key explicit.
        key = f"{scope.scope_hash}|{'|'.join(sorted(scope.allowed_domains))}"
        now = self._clock()
        if self._fresh_until.get(key, -1.0) > now:
            return
        async with self._lock:
            if self._fresh_until.get(key, -1.0) > self._clock():
                return
            try:
                await self._indexer.refresh(scope)
            except Exception as exc:  # stale results beat a failed search; never log bodies
                _log.warning("catalog index refresh failed: %s", type(exc).__name__)
                return
            if len(self._fresh_until) >= _SCOPE_CACHE_LIMIT:
                self._fresh_until.clear()
            self._fresh_until[key] = self._clock() + self._refresh_seconds

    async def search(self, scope: IdentityScope, request: GraphSearchRequest) -> GraphResult:
        await self._sync(scope)
        return await super().search(scope, request)


def _azure_capability(ctx: BuildContext, settings: SearchSettings) -> CapabilityResult | str:
    """The matrix row result, or a reason string when it cannot even be looked up."""
    if not settings.region:
        return "search_region_missing"
    try:
        return azure_search_capability(ctx.settings.cloud_profile.cloud.value, settings.region)
    except (ValidationError, ValueError):
        return "search_region_invalid"


def _azure_backend(ctx: BuildContext, settings: SearchSettings) -> Any | None:
    override = ctx.overrides.backend("search_client")
    if override is not None:
        return override
    if not settings.service:
        return None
    credential = DefaultAzureCredential(
        authority=ctx.settings.cloud_profile.login_host,
        exclude_environment_credential=ctx.settings.env != "local",
    )
    ctx.lifetime.register(credential)  # type: ignore[arg-type]  # closes via close()
    try:
        client = create_search_client(
            ctx.settings.cloud_profile,
            service=settings.service,
            index_name=settings.index,
            credential=credential,
        )
    except (ValueError, InvalidSchemaError):
        raise ComponentUnavailableError("search_service_invalid") from None
    ctx.on_shutdown(client.close)
    return client


def build_catalog_graph(ctx: BuildContext, repository: CatalogRepository) -> GraphQuery | None:
    """The catalog graph with search composed from ``NS_SEARCH_*``; ``None`` when unset."""
    try:
        settings = SearchSettings()
    except ValidationError:
        raise ComponentUnavailableError("search_settings_invalid") from None
    if settings.provider is None:
        return None

    store = FixtureSearchStore()
    sink: IndexSink = store
    search: Any = store
    azure_enabled = False
    reason: str | None = None

    if settings.provider == "azure":
        capability = _azure_capability(ctx, settings)
        backend = None
        if isinstance(capability, str):
            reason = capability
        elif capability.status != "supported":
            reason = capability.reason_code or "capability_unavailable"
        else:
            # Only a supported row may construct a client; nothing is requested otherwise.
            backend = _azure_backend(ctx, settings)
            if backend is None:
                reason = "search_service_missing"
        if backend is not None and not isinstance(capability, str):
            cloud = ctx.settings.cloud_profile.cloud.value
            azure = AzureAuthorizedSearch(backend, cloud=cloud)  # type: ignore[arg-type]
            wrapper = FallbackAuthorizedSearch(store, azure=azure, capability=capability)
            azure_enabled = wrapper.azure_enabled
            search = wrapper
            if azure_enabled:
                sink = CompositeIndexSink(store, AzureIndexSink(backend))
        if reason is not None:
            _log.warning("azure search disabled (%s); the in-process index answers", reason)

    indexer = CatalogIndexer(repository, sink)
    graph = IndexedGraphQuery(repository, search, indexer, refresh_seconds=settings.refresh_seconds)
    ctx.app.state.search_runtime = SearchRuntime(
        provider=settings.provider,
        azure_enabled=azure_enabled,
        disabled_reason=reason,
        indexer=indexer,
        _invalidate=graph.invalidate,
    )
    return graph

"""Worker-side search write-through (PRP-60 item 6).

A projection or discovery write happens in the worker process, which cannot reach the API's
in-process index. When ``NS_SEARCH_PROVIDER=azure``, the Azure AI Search capability row for the
deployment's cloud and ``NS_SEARCH_REGION`` is supported and ``NS_SEARCH_SERVICE`` is set, the
catalog repository is wrapped in :class:`IndexingCatalogRepository` over an Azure index sink, so
each created, updated or deprecated entity is upserted into the index at once. In every other
case (unset, ``fixture``, unsupported cloud or region, no service) the repository is returned
unchanged and no client or credential is created: nothing is requested and nothing falls back
to an in-process index in the worker.

Same ``NS_SEARCH_*`` names as the API. Authentication is the workload identity
(``DefaultAzureCredential``); no key or connection string is read.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final, Literal, cast

from azure.identity.aio import DefaultAzureCredential
from neurosphere_core.capabilities import CapabilityResult
from neurosphere_core.catalog import CatalogRepository
from neurosphere_core.clients.lifetime import ClientLifetime
from neurosphere_core.search.azure import azure_search_capability
from neurosphere_core.search.azure.client import create_search_client
from neurosphere_core.search.indexer import AzureIndexSink, CatalogIndexer
from neurosphere_core.search.write_hook import IndexingCatalogRepository
from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from neurosphere_workers.runtime.factories import RuntimeConfig

__all__ = ["WorkerSearchSettings", "wrap_catalog_for_search"]

_log: Final = logging.getLogger("neurosphere_workers.runtime.search_wiring")


class WorkerSearchSettings(BaseSettings):
    """``NS_SEARCH_*`` as the worker reads it. Unrelated ``NS_SEARCH_*`` names are ignored."""

    model_config = SettingsConfigDict(env_prefix="NS_SEARCH_", frozen=True, extra="ignore")

    provider: Literal["fixture", "azure"] | None = None
    service: str | None = None
    index: str = "neurosphere-catalog"
    region: str | None = None

    @field_validator("provider", "service", "region", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


def wrap_catalog_for_search(
    cfg: RuntimeConfig,
    lifetime: ClientLifetime,
    repository: CatalogRepository,
    *,
    backend: Any | None = None,
    settings: WorkerSearchSettings | None = None,
) -> CatalogRepository:
    """``repository`` wrapped for write-through, or unchanged when Azure search is not serving.

    ``backend`` is the test seam for the Azure ``SearchClient`` (upload/delete slice).
    """
    try:
        search = settings or WorkerSearchSettings()
    except ValidationError:
        _log.warning("worker search settings invalid; catalog writes are not indexed")
        return repository
    if search.provider != "azure" or not search.region:
        return repository
    try:
        capability: CapabilityResult = azure_search_capability(cfg.cloud, search.region)
    except (ValidationError, ValueError):
        _log.warning("worker search region invalid; catalog writes are not indexed")
        return repository
    if capability.status != "supported":
        _log.warning("azure search unsupported for the worker (%s)", capability.reason_code)
        return repository
    if backend is None:
        if not search.service:
            return repository
        credential = lifetime.register(
            DefaultAzureCredential(authority=cfg.settings.cloud_profile.login_host)
        )
        try:
            backend = lifetime.register(
                create_search_client(
                    cfg.settings.cloud_profile,
                    service=search.service,
                    index_name=search.index,
                    credential=credential,
                )
            )
        except ValueError:
            _log.warning("worker search service invalid; catalog writes are not indexed")
            return repository
    indexer = CatalogIndexer(repository, AzureIndexSink(backend))
    return cast(CatalogRepository, IndexingCatalogRepository(repository, indexer))

"""Catalog repositories (PRP-10 item 1): Cosmos NoSQL and in-memory, one shared engine.

The Cosmos module imports azure-cosmos, so it is not re-exported here; import
``neurosphere_core.catalog.repo.cosmos`` directly for the Cosmos types.
"""

from neurosphere_core.catalog.repo.backend import Query, ScopeFilter
from neurosphere_core.catalog.repo.engine import CatalogEngine, require_scope
from neurosphere_core.catalog.repo.memory import InMemoryBackend, InMemoryCatalogRepository

__all__ = [
    "CatalogEngine",
    "InMemoryBackend",
    "InMemoryCatalogRepository",
    "Query",
    "ScopeFilter",
    "require_scope",
]

"""Azure AI Search implementation of ``AuthorizedSearch`` plus the fixture fallback (PRP-10)."""

from neurosphere_core.search.azure.client import (
    AzureAuthorizedSearch,
    SearchBackend,
    create_search_client,
)
from neurosphere_core.search.azure.fallback import (
    FallbackAuthorizedSearch,
    azure_search_capability,
    require_azure_search,
)
from neurosphere_core.search.azure.filters import build_filter, build_search_text, cache_key

__all__ = [
    "AzureAuthorizedSearch",
    "FallbackAuthorizedSearch",
    "SearchBackend",
    "azure_search_capability",
    "build_filter",
    "build_search_text",
    "cache_key",
    "create_search_client",
    "require_azure_search",
]

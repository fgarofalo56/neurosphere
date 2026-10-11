"""Deterministic in-process search index for offline tests."""

from neurosphere_core.search.fixture.index import (
    FixtureSearchIndex,
    SearchDocument,
    documents_from_catalog,
)

__all__ = ["FixtureSearchIndex", "SearchDocument", "documents_from_catalog"]

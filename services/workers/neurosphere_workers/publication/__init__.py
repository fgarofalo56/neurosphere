"""Catalog recording of verified APIM gateway publications (PRP-34 items 5, 6 and 10).

A Grant or McpServer publication is an action intent executed by the APIM connector; once it
has SUCCEEDED and VERIFIED, the catalog entity records it (``provenance`` plus ``attributes``).
This package is the one place those rules live, used by both callers:

* the catalog API routes ``POST /catalog/grants/{id}/publication`` and
  ``POST /catalog/mcp-servers/{id}/publication-record`` (manual or retry path);
* the worker's post-success hand-off (``neurosphere_workers.actions.apim``
  ``PublicationRecordingExecutor``), which calls :class:`CatalogPublicationRecorder` after the
  executor returned, outside every executor phase.

It writes catalog metadata only to RECORD a verified, real gateway change; it never stands in for
one. It is deliberately not part of the action plane (``neurosphere_workers.actions``), which
never writes catalog metadata (PRP-17 D5 test).

:mod:`.records` is the read side of the connector's durable apply records (the same ``gateways``
container and store class the executor writes with), wired into the API as
``app.state.apim_apply_records``.
"""

from neurosphere_workers.publication.recorder import (
    OPERATION,
    CatalogPublicationRecorder,
    ScopeProvider,
)
from neurosphere_workers.publication.records import (
    ApplyRecordLookup,
    ApplyRecordReader,
    CosmosApplyRecordLookup,
    InMemoryApplyRecordLookup,
    RecordedApply,
    RecordedStep,
    reader_for,
)

__all__ = [
    "OPERATION",
    "ApplyRecordLookup",
    "ApplyRecordReader",
    "CatalogPublicationRecorder",
    "CosmosApplyRecordLookup",
    "InMemoryApplyRecordLookup",
    "RecordedApply",
    "RecordedStep",
    "ScopeProvider",
    "reader_for",
]

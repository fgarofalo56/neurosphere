"""Connector run status and the four-source summary (PRP-139 item 3).

Workers record one :class:`ConnectorRunStatus` per connector kind after each tick; the API reads
them with the stored connector configurations and summarizes them with :func:`summarize`.
"""

from neurosphere_core.sources_status.models import (
    CONNECTOR_KINDS,
    NOT_AVAILABLE_IN_RELEASE,
    SOURCE_ACCESS_DENIED,
    ConnectorKind,
    ConnectorRunStatus,
    RunState,
    classify_failure,
    is_code,
)
from neurosphere_core.sources_status.repository import (
    RUN_STATUS_DOC_TYPE,
    CosmosSourceStatusRepository,
    InMemorySourceStatusRepository,
    SourceStatusRepository,
    run_status_item_id,
)
from neurosphere_core.sources_status.summary import (
    AWAITING_FIRST_RUN,
    SOURCE_ORDER,
    ConfiguredConnector,
    ConnectorSummary,
    GatewayHealth,
    SourceKey,
    SourceState,
    SourceSummary,
    SourceSummaryItem,
    summarize,
)

__all__ = [
    "AWAITING_FIRST_RUN",
    "CONNECTOR_KINDS",
    "NOT_AVAILABLE_IN_RELEASE",
    "RUN_STATUS_DOC_TYPE",
    "SOURCE_ACCESS_DENIED",
    "SOURCE_ORDER",
    "ConfiguredConnector",
    "ConnectorKind",
    "ConnectorRunStatus",
    "ConnectorSummary",
    "CosmosSourceStatusRepository",
    "GatewayHealth",
    "InMemorySourceStatusRepository",
    "RunState",
    "SourceKey",
    "SourceState",
    "SourceStatusRepository",
    "SourceSummary",
    "SourceSummaryItem",
    "classify_failure",
    "is_code",
    "run_status_item_id",
    "summarize",
]

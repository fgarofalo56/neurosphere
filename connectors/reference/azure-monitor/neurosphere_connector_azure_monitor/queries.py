"""Fixed KQL templates and validated source identifiers.

Query text is a module constant chosen by source kind. The time window travels in the API's
documented ``timespan`` parameter, so no value is ever interpolated into KQL and no caller or
model can supply query text.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

__all__ = [
    "APIM_GATEWAY_COLUMNS",
    "APIM_LLM_COLUMNS",
    "APIM_MCP_COLUMNS",
    "APIM_USAGE_METRICS_COLUMNS",
    "APP_INSIGHTS_KINDS",
    "MAX_ROWS",
    "TEMPLATES",
    "MonitorSource",
    "SourceKind",
    "template_for",
]

# Fixed row cap per query; reaching it marks the page truncated (the API itself caps at 500,000).
MAX_ROWS: Final = 10_000


class SourceKind(StrEnum):
    LOG_ANALYTICS = "log_analytics"
    APP_INSIGHTS = "app_insights"
    APIM_GATEWAY = "apim_gateway"
    APIM_MCP = "apim_mcp"
    # Application Insights ``customMetrics`` written by the ``llm-emit-token-metric`` policy.
    APIM_USAGE_METRICS = "apim_usage_metrics"


#: Kinds queried through the Application Insights query API (source id = App Insights app id).
APP_INSIGHTS_KINDS: Final = frozenset({SourceKind.APP_INSIGHTS, SourceKind.APIM_USAGE_METRICS})

# Workspace-based Application Insights data lives in Log Analytics tables (AppRequests).
_LOG_ANALYTICS_QUERY: Final = (
    "AppRequests"
    " | summarize requests=count(), failed=countif(Success == false)"
    " by TimeGenerated=bin(TimeGenerated, 5m), AppRoleName"
    f" | order by TimeGenerated asc | take {MAX_ROWS}"
)
# Application Insights query API (classic schema table names).
_APP_INSIGHTS_QUERY: Final = (
    "requests"
    " | summarize requests=count(), failed=countif(success == false)"
    " by timestamp=bin(timestamp, 5m)"
    f" | order by timestamp asc | take {MAX_ROWS}"
)

# API Management gateway logs (resource-specific tables). The column lists are an allowlist:
# bodies, headers and trace records are never projected. The window is the request's
# ``timespan``, applied to both tables, never query text. ``GatewayLogs`` and ``GatewayLlmLogs``
# are separate diagnostic categories; with only the first enabled the LLM columns are all null.
APIM_GATEWAY_COLUMNS: Final = (
    "TimeGenerated, CorrelationId, ApiId, ApiRevision, OperationId, ProductId,"
    " ApimSubscriptionId, BackendId, BackendResponseCode, ResponseCode, IsRequestSuccess,"
    " TotalTime, BackendTime, Region, _ResourceId"
)
APIM_LLM_COLUMNS: Final = (
    "ModelName, DeploymentName, PromptTokens, CompletionTokens, TotalTokens,"
    " IsStreamCompletion, ApiVersion"
)
_APIM_GATEWAY_QUERY: Final = (
    f"ApiManagementGatewayLogs | project {APIM_GATEWAY_COLUMNS}"
    " | join kind=leftouter ("
    f"ApiManagementGatewayLlmLog | project CorrelationId, {APIM_LLM_COLUMNS}"
    ") on CorrelationId"
    " | project-away CorrelationId1"
    f" | order by TimeGenerated asc | take {MAX_ROWS}"
)
APIM_MCP_COLUMNS: Final = (
    "TimeGenerated, CorrelationId, ToolName, ToolCount, TransportType, _ResourceId"
)
_APIM_MCP_QUERY: Final = (
    f"ApiManagementGatewayMCPLog | project {APIM_MCP_COLUMNS}"
    f" | order by TimeGenerated asc | take {MAX_ROWS}"
)

# Token metrics from ``llm-emit-token-metric`` (grant fragment dimensions: API ID, Subscription ID,
# x-ns-cost-center). The metric carries no CorrelationId, so it attributes by dimension, never per
# request. Only the three dimension values are extracted; ``customDimensions`` itself is not
# projected, so no other dimension (and nothing body or header shaped) can leave the query.
APIM_USAGE_METRICS_COLUMNS: Final = (
    "timestamp, name, value, valueSum, valueCount, ApiId, SubscriptionId, ['x-ns-cost-center']"
)
_APIM_USAGE_METRICS_QUERY: Final = (
    'customMetrics | where name in ("Prompt Tokens", "Completion Tokens", "Total Tokens")'
    ' | extend ApiId=tostring(customDimensions["API ID"]),'
    ' SubscriptionId=tostring(customDimensions["Subscription ID"]),'
    " ['x-ns-cost-center']=tostring(customDimensions[\"x-ns-cost-center\"])"
    f" | project {APIM_USAGE_METRICS_COLUMNS}"
    f" | order by timestamp asc | take {MAX_ROWS}"
)

TEMPLATES: Final = {
    SourceKind.LOG_ANALYTICS: _LOG_ANALYTICS_QUERY,
    SourceKind.APP_INSIGHTS: _APP_INSIGHTS_QUERY,
    SourceKind.APIM_GATEWAY: _APIM_GATEWAY_QUERY,
    SourceKind.APIM_MCP: _APIM_MCP_QUERY,
    SourceKind.APIM_USAGE_METRICS: _APIM_USAGE_METRICS_QUERY,
}


def template_for(kind: SourceKind) -> str:
    return TEMPLATES[kind]


@dataclass(frozen=True)
class MonitorSource:
    """One workspace or Application Insights app. The id must be a GUID (it enters a URL path)."""

    kind: SourceKind
    source_id: str

    def __post_init__(self) -> None:
        try:
            canonical = str(uuid.UUID(self.source_id))
        except ValueError as exc:
            raise ValueError("source_id must be a GUID") from exc
        object.__setattr__(self, "source_id", canonical)

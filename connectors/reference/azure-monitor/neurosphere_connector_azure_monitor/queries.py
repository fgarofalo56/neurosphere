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
    "CONTENT_DENYLIST",
    "GENAI_ATTRIBUTE_KEYS",
    "GENAI_COLUMNS",
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
    # GenAI spans in workspace-based Application Insights tables; workspace query API (not in
    # APP_INSIGHTS_KINDS). Dependencies = client/internal spans, requests = server spans.
    APP_GENAI_DEPENDENCIES = "app_genai_dependencies"
    APP_GENAI_REQUESTS = "app_genai_requests"


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

# GenAI spans (PRP-141). Metadata only: columns and attribute keys are allowlists, the
# ``Properties`` bag is never projected whole, and content is never selected. Attribute names
# mirror the OTLP edge tables (services/api ingest/otlp_mapping.py); a parity test in
# tests/unit/azure_monitor_ai asserts they stay equal.
OPERATION_ATTR: Final = "gen_ai.operation.name"
AGENT_ID_ATTRS: Final = ("gen_ai.agent.id",)
PROVIDER_ATTRS: Final = ("gen_ai.provider.name", "gen_ai.system", "llm.provider")
MODEL_ATTRS: Final = (
    "gen_ai.response.model",
    "gen_ai.request.model",
    "llm.model_name",
    "llm.request.model",
)
INPUT_TOKEN_ATTRS: Final = (
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.prompt_tokens",
    "llm.usage.prompt_tokens",
)
OUTPUT_TOKEN_ATTRS: Final = (
    "gen_ai.usage.output_tokens",
    "gen_ai.usage.completion_tokens",
    "llm.usage.completion_tokens",
)
CACHED_TOKEN_ATTRS: Final = (
    "gen_ai.usage.cache_read.input_tokens",
    "gen_ai.usage.cached_tokens",
    "llm.usage.cache_read_input_tokens",
)
REASONING_TOKEN_ATTRS: Final = (
    "gen_ai.usage.reasoning.output_tokens",
    "gen_ai.usage.reasoning_tokens",
)
GENAI_COLUMNS: Final = (
    "TimeGenerated",
    "Id",
    "OperationId",
    "ParentId",
    "Success",
    "DurationMs",
    "ItemCount",
    "AppRoleName",
)
GENAI_ATTRIBUTE_KEYS: Final = (
    OPERATION_ATTR,
    *AGENT_ID_ATTRS,
    *PROVIDER_ATTRS,
    *MODEL_ATTRS,
    *INPUT_TOKEN_ATTRS,
    *OUTPUT_TOKEN_ATTRS,
    *CACHED_TOKEN_ATTRS,
    *REASONING_TOKEN_ATTRS,
)
# Names that must never appear in a GenAI template: content and personal-data attributes, columns
# that can carry command text, targets, URLs, identities or the whole attribute bag, and the
# trace, exception and event tables.
CONTENT_DENYLIST: Final = frozenset(
    {
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "gen_ai.system_instructions",
        "gen_ai.tool.definitions",
        "gen_ai.tool.call.arguments",
        "gen_ai.tool.call.result",
        "gen_ai.evaluation.explanation",
        "gen_ai.prompt",
        "gen_ai.completion",
        "gen_ai.conversation.id",
        "user.id",
        "user.email",
        "user.name",
        "enduser.id",
        "enduser.pseudo.id",
        "client.address",
        "Status.message",
        "db.statement",
        "db.query.text",
        "url.full",
        "http.url",
        "Properties",
        "Measurements",
        "Data",
        "Target",
        "Url",
        "Name",
        "ClientIP",
        "UserId",
        "UserAuthenticatedId",
        "UserAccountId",
        "SessionId",
        "OperationName",
        "AppTraces",
        "AppExceptions",
        "AppEvents",
    }
)


def _genai_query(table: str) -> str:
    # Each allowlisted attribute is extracted to its own bracket-quoted string column; the
    # ``Properties`` bag is read per key and never projected.
    extends = ", ".join(
        f"['{key}']=tostring(Properties[\"{key}\"])" for key in GENAI_ATTRIBUTE_KEYS
    )
    projected = ", ".join((*GENAI_COLUMNS, *(f"['{key}']" for key in GENAI_ATTRIBUTE_KEYS)))
    return (
        f"{table}"
        f' | where isnotempty(tostring(Properties["{OPERATION_ATTR}"]))'
        f" | extend {extends}"
        f" | project {projected}"
        f" | order by TimeGenerated asc | take {MAX_ROWS}"
    )


_APP_GENAI_DEPENDENCIES_QUERY: Final = _genai_query("AppDependencies")
_APP_GENAI_REQUESTS_QUERY: Final = _genai_query("AppRequests")

TEMPLATES: Final = {
    SourceKind.LOG_ANALYTICS: _LOG_ANALYTICS_QUERY,
    SourceKind.APP_INSIGHTS: _APP_INSIGHTS_QUERY,
    SourceKind.APIM_GATEWAY: _APIM_GATEWAY_QUERY,
    SourceKind.APIM_MCP: _APIM_MCP_QUERY,
    SourceKind.APIM_USAGE_METRICS: _APIM_USAGE_METRICS_QUERY,
    SourceKind.APP_GENAI_DEPENDENCIES: _APP_GENAI_DEPENDENCIES_QUERY,
    SourceKind.APP_GENAI_REQUESTS: _APP_GENAI_REQUESTS_QUERY,
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

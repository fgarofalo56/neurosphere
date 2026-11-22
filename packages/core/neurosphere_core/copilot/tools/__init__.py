"""Allowlisted server-side copilot tools with scope pass-through (PRP-19 item 1).

``build_default_registry(ToolDependencies(...))`` returns the registry; ``registry.invoke(name,
raw_args, scope)`` is the only call path. See ``registry`` for the refusal rules.
"""

from neurosphere_core.copilot.tools.args import (
    CostSummaryArgs,
    EvidenceArgs,
    ListRecommendationsArgs,
    ProposeActionArgs,
    SearchCatalogArgs,
    ToolArgs,
)
from neurosphere_core.copilot.tools.builtin import (
    MAX_RESULT_LIMIT,
    TOOL_NAMES,
    ToolDependencies,
    build_default_registry,
)
from neurosphere_core.copilot.tools.copilot_registry import (
    COPILOT_TOOL_NAMES,
    CopilotToolDependencies,
    build_copilot_registry,
)
from neurosphere_core.copilot.tools.errors import (
    ArgumentNotAllowedError,
    ScopeArgumentRefusedError,
    ToolBudgetError,
    ToolNotRegisteredError,
    ToolPermissionError,
    ToolTimeoutError,
)
from neurosphere_core.copilot.tools.graph import (
    MAX_GRAPH_DEPTH,
    MAX_GRAPH_EDGES,
    MAX_GRAPH_NODES,
    MAX_START_IDS,
    GraphQueryArgs,
)
from neurosphere_core.copilot.tools.matching import MAX_MATCH_DOMAINS, RecommendAgentArgs
from neurosphere_core.copilot.tools.models import (
    Citation,
    FreshnessPolicy,
    FreshnessState,
    ToolRecord,
    ToolResult,
    unknown_citations,
)
from neurosphere_core.copilot.tools.ports import (
    AccessReader,
    ActionDrafter,
    AgentMatchReader,
    CatalogReader,
    ChangeLogReader,
    ChangeRecord,
    EvidenceReader,
    EvidenceRecord,
    GraphReader,
    MetricsReader,
    RecommendationReader,
)
from neurosphere_core.copilot.tools.registry import (
    SCOPE_SHAPED_KEYS,
    RefusalEvent,
    RefusalSink,
    ToolCallEvent,
    ToolCallObserver,
    ToolRegistry,
    ToolSpec,
)
from neurosphere_core.copilot.tools.timeline import (
    MAX_TIMELINE_ENTRIES,
    MAX_TIMELINE_WINDOW,
    TimelineArgs,
)

__all__ = [
    "COPILOT_TOOL_NAMES",
    "MAX_GRAPH_DEPTH",
    "MAX_GRAPH_EDGES",
    "MAX_GRAPH_NODES",
    "MAX_MATCH_DOMAINS",
    "MAX_RESULT_LIMIT",
    "MAX_START_IDS",
    "MAX_TIMELINE_ENTRIES",
    "MAX_TIMELINE_WINDOW",
    "SCOPE_SHAPED_KEYS",
    "TOOL_NAMES",
    "AccessReader",
    "ActionDrafter",
    "AgentMatchReader",
    "ArgumentNotAllowedError",
    "CatalogReader",
    "ChangeLogReader",
    "ChangeRecord",
    "Citation",
    "CopilotToolDependencies",
    "CostSummaryArgs",
    "EvidenceArgs",
    "EvidenceReader",
    "EvidenceRecord",
    "FreshnessPolicy",
    "FreshnessState",
    "GraphQueryArgs",
    "GraphReader",
    "ListRecommendationsArgs",
    "MetricsReader",
    "ProposeActionArgs",
    "RecommendAgentArgs",
    "RecommendationReader",
    "RefusalEvent",
    "RefusalSink",
    "ScopeArgumentRefusedError",
    "SearchCatalogArgs",
    "TimelineArgs",
    "ToolArgs",
    "ToolBudgetError",
    "ToolCallEvent",
    "ToolCallObserver",
    "ToolDependencies",
    "ToolNotRegisteredError",
    "ToolPermissionError",
    "ToolRecord",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "ToolTimeoutError",
    "build_copilot_registry",
    "build_default_registry",
    "unknown_citations",
]

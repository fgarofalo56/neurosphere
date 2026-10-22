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
from neurosphere_core.copilot.tools.errors import (
    ArgumentNotAllowedError,
    ScopeArgumentRefusedError,
    ToolBudgetError,
    ToolNotRegisteredError,
    ToolPermissionError,
    ToolTimeoutError,
)
from neurosphere_core.copilot.tools.models import (
    Citation,
    FreshnessPolicy,
    FreshnessState,
    ToolRecord,
    ToolResult,
    unknown_citations,
)
from neurosphere_core.copilot.tools.ports import (
    ActionDrafter,
    CatalogReader,
    EvidenceReader,
    EvidenceRecord,
    MetricsReader,
    RecommendationReader,
)
from neurosphere_core.copilot.tools.registry import (
    SCOPE_SHAPED_KEYS,
    RefusalEvent,
    RefusalSink,
    ToolRegistry,
    ToolSpec,
)

__all__ = [
    "MAX_RESULT_LIMIT",
    "SCOPE_SHAPED_KEYS",
    "TOOL_NAMES",
    "ActionDrafter",
    "ArgumentNotAllowedError",
    "CatalogReader",
    "Citation",
    "CostSummaryArgs",
    "EvidenceArgs",
    "EvidenceReader",
    "EvidenceRecord",
    "FreshnessPolicy",
    "FreshnessState",
    "ListRecommendationsArgs",
    "MetricsReader",
    "ProposeActionArgs",
    "RecommendationReader",
    "RefusalEvent",
    "RefusalSink",
    "ScopeArgumentRefusedError",
    "SearchCatalogArgs",
    "ToolArgs",
    "ToolBudgetError",
    "ToolDependencies",
    "ToolNotRegisteredError",
    "ToolPermissionError",
    "ToolRecord",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "ToolTimeoutError",
    "build_default_registry",
    "unknown_citations",
]

"""The copilot-only registry: the five default tools plus the PRP-78 tools (PRP-78 item 4).

``build_default_registry`` stays exactly the five shared tools, because the MCP server and the
report planner consume it and anything added there would silently reach them. The copilot engine
builds its registry here instead.

Two seams are documented here, by design:

* **observer**: ``build_copilot_registry(..., observer=...)`` hands a ``ToolCallObserver`` to the
  registry. It is told once per invocation (allowed, refused or failed) with names, reason codes,
  domain ids, a record count and the scope hash, never a value, and it can never change the
  outcome. The API-side read auditor (PRP-78 item 5) is the first implementation.
* **extra_specs**: the registration hook for tools owned by later PRPs (PRP-80 ``search_docs``,
  PRP-116). A spec whose name duplicates an existing tool is refused with ``ValueError``.

Ownership of ``registry.py`` (and so of both seams) is handed to PRP-113/116 after W23.

Tool availability: ``graph_query`` needs a bound ``graph``; ``recommend_agent`` needs a bound
``matcher``; ``get_timeline`` is always present (its ``changes`` section reports
``change_log_unavailable`` when no ``changes`` reader is bound).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from neurosphere_core.copilot.tools.builtin import (
    TOOL_NAMES,
    ToolDependencies,
    build_default_registry,
)
from neurosphere_core.copilot.tools.graph import graph_query_spec
from neurosphere_core.copilot.tools.matching import recommend_agent_spec
from neurosphere_core.copilot.tools.models import FreshnessPolicy
from neurosphere_core.copilot.tools.ports import (
    AccessReader,
    ActionDrafter,
    AgentMatchReader,
    CatalogReader,
    ChangeLogReader,
    EvidenceReader,
    GraphReader,
    MetricsReader,
    RecommendationReader,
)
from neurosphere_core.copilot.tools.registry import (
    RefusalSink,
    ToolCallObserver,
    ToolRegistry,
    ToolSpec,
)
from neurosphere_core.copilot.tools.timeline import get_timeline_spec
from neurosphere_core.scope import IdentityScope

__all__ = [
    "COPILOT_TOOL_NAMES",
    "CopilotToolDependencies",
    "build_copilot_registry",
]

COPILOT_TOOL_NAMES: Final = (*TOOL_NAMES, "graph_query", "get_timeline", "recommend_agent")


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CopilotToolDependencies:
    """``ToolDependencies`` plus the optional ports of the PRP-78 tools. Bound once at startup."""

    catalog: CatalogReader
    metrics: MetricsReader
    recommendations: RecommendationReader
    evidence: EvidenceReader
    drafter: ActionDrafter
    clock: Callable[[], datetime] = _utc_now
    freshness: FreshnessPolicy = field(default_factory=FreshnessPolicy)
    graph: GraphReader | None = None
    access: AccessReader | None = None
    changes: ChangeLogReader | None = None
    matcher: AgentMatchReader | None = None
    preferred_domains: Callable[[IdentityScope], Sequence[str]] | None = None


def build_copilot_registry(
    deps: CopilotToolDependencies,
    *,
    sink: RefusalSink | None = None,
    observer: ToolCallObserver | None = None,
    extra_specs: Sequence[ToolSpec] = (),
) -> ToolRegistry:
    """The copilot allowlist: five defaults, then each PRP-78 tool whose ports are bound."""
    base = ToolDependencies(
        catalog=deps.catalog,
        metrics=deps.metrics,
        recommendations=deps.recommendations,
        evidence=deps.evidence,
        drafter=deps.drafter,
        clock=deps.clock,
        freshness=deps.freshness,
    )
    specs: list[ToolSpec] = list(build_default_registry(base).manifest())
    if deps.graph is not None:
        specs.append(
            graph_query_spec(
                graph=deps.graph,
                access=deps.access,
                catalog=deps.catalog,
                clock=deps.clock,
                freshness=deps.freshness,
            )
        )
    specs.append(
        get_timeline_spec(
            changes=deps.changes,
            metrics=deps.metrics,
            recommendations=deps.recommendations,
            clock=deps.clock,
            freshness=deps.freshness,
        )
    )
    if deps.matcher is not None:
        specs.append(
            recommend_agent_spec(
                matcher=deps.matcher,
                clock=deps.clock,
                freshness=deps.freshness,
                preferred_domains=deps.preferred_domains,
            )
        )
    specs.extend(extra_specs)
    return ToolRegistry(specs, sink=sink, observer=observer)  # duplicates raise ValueError

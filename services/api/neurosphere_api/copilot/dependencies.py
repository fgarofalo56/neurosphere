"""Composition of the copilot for the API (PRP-19 item 2).

Collaborators come from ``app.state``; :func:`configure_copilot` sets the copilot-specific ones
and the already-wired read services are reused under their existing keys. A missing or
wrongly-typed REQUIRED collaborator fails closed with 503 (``dependency_transient``, reason
``copilot_unconfigured``).

=============================  =====================================================================
``app.state`` key              Type
=============================  =====================================================================
``copilot_model_adapter``      ``neurosphere_core.copilot.models.ModelAdapter`` (required)
``copilot_conversation_store`` ``neurosphere_api.copilot.store.ConversationStore`` (required)
``catalog_repository``         ``CatalogRepository`` (required; the catalog tool's reader)
``aggregate_reader``           ``AggregateReader`` (required; cost / latency / error aggregates)
``recommendation_store``       ``RecommendationStore`` (required)
``copilot_evidence_reader``    optional ``EvidenceReader``; default reads nothing, so evidence
                               questions abstain until a real evidence store is bound
``copilot_settings``           optional ``CopilotSettings``
``copilot_chart_validator``    optional ``ChartPlanValidator``; default rejects every chart plan
``copilot_refusal_sink``       optional ``RefusalSink`` (audit hook for refused tool calls)
``copilot_clock``              optional ``() -> datetime`` (aware)
=============================  =====================================================================

The action plane is read from the PRP-17 keys (``neurosphere_api.actions.dependencies``); when it
is not configured chat still answers read-only questions and drafting returns 503.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from fastapi import FastAPI, Request
from neurosphere_core.aggregates import AggregateReader
from neurosphere_core.catalog import CatalogRepository
from neurosphere_core.copilot.models import ModelAdapter
from neurosphere_core.copilot.tools import EvidenceRecord, RefusalSink
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.recommendations import RecommendationStore
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.dependencies import ActionPlane, get_action_plane
from neurosphere_api.copilot.engine import ChartPlanValidator, CopilotEngine, ToolPorts
from neurosphere_api.copilot.settings import CopilotSettings
from neurosphere_api.copilot.store import ConversationStore

__all__ = [
    "CopilotRuntime",
    "EmptyEvidenceReader",
    "configure_copilot",
    "get_copilot",
    "get_optional_action_plane",
]

_UNCONFIGURED: Final = "copilot_unconfigured"


class EmptyEvidenceReader:
    """Evidence reader that yields no records (no evidence store is bound yet): the copilot
    then abstains on evidence questions instead of inventing an answer."""

    async def get_many(
        self, scope: IdentityScope, domain_ids: Sequence[str], evidence_ids: Sequence[str]
    ) -> Sequence[EvidenceRecord]:
        return ()


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CopilotRuntime:
    engine: CopilotEngine
    store: ConversationStore
    settings: CopilotSettings
    clock: Callable[[], datetime]

    def now(self) -> datetime:
        at = self.clock()
        if at.tzinfo is None:
            raise DependencyTransientError(
                "copilot clock is not timezone-aware", reason=_UNCONFIGURED
            )
        return at.astimezone(UTC)


def _required(state: Any, key: str, kind: type) -> Any:
    value = getattr(state, key, None)
    if value is None or not isinstance(value, kind):
        raise DependencyTransientError("copilot is not configured", reason=_UNCONFIGURED)
    return value


def get_copilot(request: Request) -> CopilotRuntime:
    state = request.app.state
    adapter: ModelAdapter = _required(state, "copilot_model_adapter", ModelAdapter)
    store: ConversationStore = _required(state, "copilot_conversation_store", ConversationStore)
    catalog = _required(state, "catalog_repository", CatalogRepository)
    metrics = _required(state, "aggregate_reader", AggregateReader)
    recommendations = _required(state, "recommendation_store", RecommendationStore)
    evidence = getattr(state, "copilot_evidence_reader", None) or EmptyEvidenceReader()
    settings = getattr(state, "copilot_settings", None)
    if settings is None:
        settings = CopilotSettings()
    elif not isinstance(settings, CopilotSettings):
        raise DependencyTransientError("copilot is not configured", reason=_UNCONFIGURED)
    clock: Callable[[], datetime] = getattr(state, "copilot_clock", None) or _utc_now
    engine = CopilotEngine(
        adapter=adapter,
        ports=ToolPorts(
            catalog=catalog, metrics=metrics, recommendations=recommendations, evidence=evidence
        ),
        settings=settings,
        chart_validator=getattr(state, "copilot_chart_validator", None),
        refusal_sink=getattr(state, "copilot_refusal_sink", None),
        clock=clock,
    )
    return CopilotRuntime(engine=engine, store=store, settings=settings, clock=clock)


def get_optional_action_plane(request: Request) -> ActionPlane | None:
    """The PRP-17 action plane, or ``None`` when it is not configured (drafting then 503s)."""
    try:
        return get_action_plane(request)
    except DependencyTransientError:
        return None


def configure_copilot(
    app: FastAPI,
    *,
    model_adapter: ModelAdapter,
    conversation_store: ConversationStore,
    evidence_reader: object | None = None,
    settings: CopilotSettings | None = None,
    chart_validator: ChartPlanValidator | None = None,
    refusal_sink: RefusalSink | None = None,
    clock: Callable[[], datetime] | None = None,
) -> None:
    """Install the copilot-specific collaborators on ``app.state`` (one call for item 7)."""
    state = app.state
    state.copilot_model_adapter = model_adapter
    state.copilot_conversation_store = conversation_store
    state.copilot_evidence_reader = evidence_reader
    state.copilot_settings = settings or CopilotSettings()
    state.copilot_chart_validator = chart_validator
    state.copilot_refusal_sink = refusal_sink
    state.copilot_clock = clock

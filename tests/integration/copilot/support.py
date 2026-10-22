"""The in-process composition root for PRP-19: what a deployment's startup code will do.

Nothing in production wires authz, the catalog and the action plane together yet, so this module
IS the composition root under test. The app is built by ``create_app`` (the ``REGISTERED`` hooks,
which now include the copilot and reports routers), the copilot and reports collaborators are
configured through ``configure_copilot`` / ``configure_reports`` (the chart validator is left at
its default: the real one), and the PRP-17 action plane is the one the harness wires.

All data is synthetic and in memory except the conversation and report stores, which the caller
chooses (in-memory here, Cosmos emulator containers in ``test_wiring_cosmos.py``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
from action_plane_harness import (  # pyright: ignore[reportMissingImports]
    ALICE,
    FINANCE,
    KIND,
    OPERATIONS,
    TARGET_VERSION,
    Api,
    make_api,
)
from copilot_api_harness import (  # pyright: ignore[reportMissingImports]
    World,
    agent,
    make_world,
)
from copilot_http_harness import COPILOT_PREFIX  # pyright: ignore[reportMissingImports]
from neurosphere_api.copilot import ConversationStore, configure_copilot
from neurosphere_api.reports import ReportStore, configure_reports
from neurosphere_core.auth.scope import Role
from neurosphere_core.copilot.models import (
    ActionSuggestion,
    Completed,
    FixtureAdapter,
    ModelEvent,
    ModelRequest,
    TextDelta,
    ToolCallRequested,
)
from neurosphere_core.copilot.models.protocol import AdapterDescriptor
from neurosphere_core.copilot.models.recorded import RecordedConversation, load_conversation
from neurosphere_core.copilot.tools import ToolDependencies, build_default_registry
from reports_harness import principal  # pyright: ignore[reportMissingImports]

__all__ = [
    "TARGET",
    "Wiring",
    "action_suggestion_adapter",
    "cited_answer_adapter",
    "compose",
    "text_answer_adapter",
]

TARGET = "commercial:contoso:foundry:agent:chat-prod"
OPS_TARGET = "commercial:contoso:foundry:agent:ops-prod"
REPORTS_PREFIX = "/api/v1/reports"


class SequenceAdapter:
    """One recorded conversation per model invocation (a tool round trip needs two)."""

    def __init__(self, *adapters: FixtureAdapter) -> None:
        self._adapters = adapters
        self._calls = 0
        self._descriptor = AdapterDescriptor(
            kind="fixture", name="recorded-sequence", synthetic=True
        )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        adapter = self._adapters[min(self._calls, len(self._adapters) - 1)]
        self._calls += 1
        return adapter.stream(request)


def _recorded(events: Sequence[ModelEvent]) -> FixtureAdapter:
    """A fixture adapter replaying ``events`` (the request shape is the recorded text answer's)."""
    base = load_conversation("text_answer")
    return FixtureAdapter(RecordedConversation(request=base.request, events=tuple(events)))


def text_answer_adapter() -> FixtureAdapter:
    """The recorded plain-text answer: no tool record backs it, so the copilot abstains."""
    return FixtureAdapter("text_answer")


def cited_answer_adapter() -> SequenceAdapter:
    """Round one asks the catalog tool; round two answers citing its first record."""
    query = {
        "schema_version": "1.0.0",
        "operation": "list",
        "entity": "agent",
        "filters": [{"field": "domain_id", "op": "eq", "value": FINANCE}],
        "budget": {"timeout_ms": 2000, "limit": 20, "max_depth": 0},
    }
    return SequenceAdapter(
        _recorded(
            [
                ToolCallRequested(
                    call_id="call_1", tool_name="search_catalog", arguments={"query": query}
                ),
                Completed(stop_reason="tool_calls"),
            ]
        ),
        _recorded(
            [
                TextDelta(text="One finance agent is registered [cite:r1]."),
                Completed(stop_reason="end_turn"),
            ]
        ),
    )


def action_suggestion_adapter() -> SequenceAdapter:
    """The recorded action-suggestion shape, aimed at a real catalog target and action kind,
    followed by the closing answer that cites the drafted intent's record."""
    closing = _recorded([TextDelta(text="Drafted [cite:r1]."), Completed(stop_reason="end_turn")])
    return SequenceAdapter(_suggestion(), closing)


def _suggestion() -> FixtureAdapter:
    return _recorded(
        [
            TextDelta(text="A swap is possible. Review the draft."),
            ActionSuggestion(
                call_id="s1",
                action_type=KIND,
                target_ref=TARGET,
                rationale="cheaper at equal quality",
                parameters={
                    "target_version": TARGET_VERSION,
                    "proposed_diff": {
                        "format": "json_patch",
                        "operations": [
                            {"op": "test", "path": "/model/version", "value": "2024-08-06"},
                            {"op": "replace", "path": "/model/version", "value": "2026-06-15"},
                        ],
                    },
                },
            ),
            Completed(stop_reason="tool_calls"),
        ]
    )


@dataclass
class Wiring:
    """The composed app plus the handles a test needs."""

    api: Api
    world: World

    @property
    def app(self) -> Any:
        return self.api.h.app

    @property
    def client(self) -> Any:
        return self.api.h.client

    def headers(self, who: str) -> dict[str, str]:
        return self.api.h.auth(who)

    def use_model(self, adapter: Any) -> None:
        """Swap the model adapter (the copilot reads it from ``app.state`` per request)."""
        self.app.state.copilot_model_adapter = adapter

    # -- copilot ------------------------------------------------------------------------------

    def create_conversation(self, who: str) -> Any:
        return self.client.post(f"{COPILOT_PREFIX}/conversations", headers=self.headers(who))

    def send(self, who: str, conversation_id: str, text: str = "What agents do we have?") -> Any:
        return self.client.post(
            f"{COPILOT_PREFIX}/conversations/{conversation_id}/messages",
            headers=self.headers(who),
            json={"text": text, "context": {}},
        )

    # -- reports ------------------------------------------------------------------------------

    def reports(self, method: str, who: str, path: str = "", **kwargs: Any) -> Any:
        url = f"{REPORTS_PREFIX}/domains/{FINANCE}/reports{path}"
        return self.client.request(method, url, headers=self.headers(who), **kwargs)


def compose(
    *, conversation_store: ConversationStore, report_store: ReportStore, model: Any | None = None
) -> Wiring:
    """Build the app as startup code would, over the given stores."""
    api = make_api()  # create_app with the default hooks; actions/review routers swapped in
    h = api.h
    # ALICE also stewards OPERATIONS here so her reports see more rows than a FINANCE viewer's.
    h.repo.put_principal(
        helpers.policy(ALICE, helpers.role(Role.DOMAIN_STEWARD, FINANCE, OPERATIONS))
    )
    h.deriver.invalidate_principal(principal(ALICE))

    world = make_world(
        [agent(TARGET, FINANCE), agent(OPS_TARGET, OPERATIONS)],
        recs=[],
    )
    app = h.app

    def clock() -> datetime:
        return datetime.fromtimestamp(h.clock(), UTC)

    # copilot: default chart validator on purpose (the real one)
    configure_copilot(
        app,
        model_adapter=model or text_answer_adapter(),
        conversation_store=conversation_store,
        evidence_reader=world.evidence,
        clock=clock,
    )
    app.state.catalog_repository = world.catalog
    app.state.aggregate_reader = world.metrics
    app.state.recommendation_store = world.recs

    # reports: the same bounded tool registry over the same read ports
    registry = build_default_registry(
        ToolDependencies(
            catalog=world.catalog,
            metrics=world.metrics,
            recommendations=world.recs,
            evidence=world.evidence,
            drafter=_NoDrafter(),
            clock=clock,
        )
    )
    configure_reports(app, store=report_store, tool_registry=registry, clock=clock)
    return Wiring(api=api, world=world)


class _NoDrafter:
    """Reports never draft actions; reaching this is a bug."""

    async def draft(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("reports never draft actions")

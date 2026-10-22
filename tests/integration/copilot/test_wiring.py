"""PRP-19 item 7: the copilot and reports routers are wired into the default app.

Unmarked: runs in CI, no network, no docker. The routes come from ``create_app`` (the
``REGISTERED`` hooks), not from test-supplied routers, so this fails if a hook is dropped. The
collaborators are configured through ``configure_copilot`` / ``configure_reports``, the same calls
a deployment's startup code will make; the stores are in-memory here and Cosmos emulator
containers in ``test_wiring_cosmos.py``. The chart validator is left at its default (the real
``validate_chart_plan``).
"""

from __future__ import annotations

import pytest
from neurosphere_api.copilot import PREFIX as COPILOT_PREFIX
from neurosphere_api.copilot import InMemoryConversationStore
from neurosphere_api.reports import PREFIX as REPORTS_PREFIX
from neurosphere_api.reports import InMemoryReportStore
from neurosphere_api.routers import RouterRegistry, register_default_routers

from .scenarios import (
    check_action_suggestion_is_a_draft,
    check_conversation_stream_and_ownership,
    check_report_runs_per_viewer_scope,
)
from .support import Wiring, compose


@pytest.fixture
def wired() -> Wiring:
    return compose(
        conversation_store=InMemoryConversationStore(), report_store=InMemoryReportStore()
    )


def test_both_prefixes_are_in_the_default_registry() -> None:
    registry = RouterRegistry()
    register_default_routers(registry)
    assert COPILOT_PREFIX == "/api/v1/copilot" and REPORTS_PREFIX == "/api/v1/reports"
    for prefix in (COPILOT_PREFIX, REPORTS_PREFIX):
        assert prefix in registry.prefixes
    assert len(registry.prefixes) == len(set(registry.prefixes))


def test_copilot_and_report_routes_are_in_openapi(wired: Wiring) -> None:
    paths = set(wired.app.openapi()["paths"])
    assert f"{COPILOT_PREFIX}/conversations" in paths
    assert f"{COPILOT_PREFIX}/conversations/{{conversation_id}}/messages" in paths
    assert f"{REPORTS_PREFIX}/domains/{{domain_id}}/reports" in paths


def test_unconfigured_copilot_fails_closed_with_503() -> None:
    from action_plane_harness import ALICE, make_api  # pyright: ignore[reportMissingImports]

    api = make_api()  # the default hooks, but no configure_copilot / configure_reports call
    created = api.h.client.post("/api/v1/copilot/conversations", headers=api.h.auth(ALICE))
    assert created.status_code == 503, created.text
    reports = api.h.client.get(
        "/api/v1/reports/domains/commercial:contoso:catalog:domain:finance/reports",
        headers=api.h.auth(ALICE),
    )
    assert reports.status_code == 503, reports.text


def test_streams_in_contract_order_and_conversations_are_user_scoped(wired: Wiring) -> None:
    check_conversation_stream_and_ownership(wired)


def test_a_shared_report_runs_under_each_viewers_own_scope(wired: Wiring) -> None:
    check_report_runs_per_viewer_scope(wired)


def test_an_action_suggestion_is_a_draft_intent_that_is_never_executed(wired: Wiring) -> None:
    check_action_suggestion_is_a_draft(wired)

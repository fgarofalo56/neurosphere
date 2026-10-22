"""The copilot HTTP and SSE contract (PRP-19 wire contract, items 6 and 7 code against it)."""

from __future__ import annotations

from typing import Any

from action_plane_harness import (  # pyright: ignore[reportMissingImports]
    ALICE,
    CAROL,
    FINANCE,
    principal,
)
from authz import authz_helpers as helpers  # pyright: ignore[reportMissingImports]
from copilot_api_harness import (  # pyright: ignore[reportMissingImports]
    ScriptedAdapter,
    call,
    query_args,
    say,
)
from copilot_http_harness import COPILOT_PREFIX, make_http  # pyright: ignore[reportMissingImports]
from neurosphere_api.authz import undeclared_routes
from neurosphere_api.copilot.models import (
    AbstainEvent,
    CitationEvent,
    ContextEvent,
    DeniedEvent,
    DoneEvent,
    ErrorEvent,
    TokenEvent,
    ToolEvent,
)
from neurosphere_core.auth.scope import Role
from neurosphere_core.copilot.models import Completed
from neurosphere_core.errors import DependencyTransientError

FIN_AGENT = "commercial:contoso:foundry:agent:fin-1"
AUDITOR = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
TERMINALS = {"done", "abstain", "denied", "error"}


def answering_model() -> ScriptedAdapter:
    return ScriptedAdapter(
        call("search_catalog", {"query": query_args("agent", domain=FINANCE)}),
        say("One agent is active [cite:r1]."),
    )


def test_event_order_and_shapes_match_the_wire_contract() -> None:
    http = make_http(answering_model())
    created = http.create(ALICE)
    assert created.status_code == 201
    body = created.json()
    assert set(body) == {"id", "created_at", "retention_class", "expires_at"}

    context = {
        "page": "catalog",
        "route": "/catalog/agents",
        "filters": {"environment": "prod", "provider": ["azure"]},
        "time_range": {"from": "2026-10-01T00:00:00Z", "to": "2026-10-10T00:00:00Z"},
        "selection": [FIN_AGENT],
        "domain_id": FINANCE,
    }
    response = http.send(ALICE, body["id"], "Which agents are active?", **context)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"

    events = _events(response.text)
    names = [name for name, _ in events]
    assert names[0] == "context"
    assert names[-1] == "done" and sum(n in TERMINALS for n in names) == 1
    rank = {"context": 0, "tool": 1, "token": 2, "citation": 3, "chart": 3, "action_suggestion": 3}
    body_ranks = [rank[n] for n in names[:-1]]
    assert body_ranks == sorted(body_ranks)

    by_name: dict[str, list[dict[str, Any]]] = {}
    for name, data in events:
        by_name.setdefault(name, []).append(data)

    ctx = ContextEvent.model_validate(by_name["context"][0])
    assert set(by_name["context"][0]) == {
        "page",
        "route",
        "filters",
        "time_range",
        "selection",
        "dropped_selection_count",
        "applied_domains",
    }
    assert by_name["context"][0]["time_range"] == context["time_range"]  # from/to on the wire
    assert ctx.selection == [FIN_AGENT] and ctx.dropped_selection_count == 0
    assert ctx.applied_domains == [FINANCE]

    assert [ToolEvent.model_validate(d).status for d in by_name["tool"]] == ["started", "ok"]
    assert all(set(d) == {"name", "status"} for d in by_name["tool"])
    assert all(TokenEvent.model_validate(d).text for d in by_name["token"])
    citation = CitationEvent.model_validate(by_name["citation"][0])
    assert set(by_name["citation"][0]) == {"record_id", "kind", "source", "as_of", "freshness"}
    assert citation.record_id == FIN_AGENT and citation.freshness in {"fresh", "stale", "unknown"}
    done = DoneEvent.model_validate(by_name["done"][0])
    assert done.status == "answered" and done.message_id


def test_a_denied_turn_is_a_normal_200_stream_ending_in_denied() -> None:
    http = make_http(ScriptedAdapter(call("delete_everything", {})))
    events = http.ask(ALICE)
    assert [n for n, _ in events] == ["context", "tool", "tool", "denied"]
    denied = DeniedEvent.model_validate(events[-1][1])
    assert denied.reason_code == "tool_not_registered" and denied.reason
    assert events[1][1] == {"name": "<unregistered>", "status": "started"}


def test_an_abstained_turn_ends_in_abstain_with_a_reason() -> None:
    http = make_http(ScriptedAdapter(say("Spend doubled [cite:x].")))
    events = http.ask(ALICE)
    assert [n for n, _ in events] == ["context", "abstain"]
    abstain = AbstainEvent.model_validate(events[-1][1])
    assert abstain.reason_code == "no_authorized_evidence" and abstain.reason


def test_a_failure_after_the_stream_starts_is_an_error_event() -> None:
    class Failing(ScriptedAdapter):
        async def stream(self, request):  # type: ignore[no-untyped-def]
            raise DependencyTransientError("down", reason="model_unavailable")
            yield Completed(stop_reason="end_turn")  # pragma: no cover

    events = make_http(Failing(say("x"))).ask(ALICE)
    assert [n for n, _ in events] == ["context", "error"]
    error = ErrorEvent.model_validate(events[-1][1])
    assert (error.code, error.detail) == ("dependency_transient", "model_unavailable")


def test_tool_output_and_prompts_are_not_in_the_event_stream() -> None:
    http = make_http(answering_model())
    events = http.ask(ALICE, "Which agents are active?")
    blob = str(events)
    assert "content_trust" not in blob and "Answer only from" not in blob


# -- authorization and addressing ---------------------------------------------------------------


def test_asking_requires_authentication_and_data_read_somewhere() -> None:
    auditor_policy = helpers.policy(AUDITOR, helpers.role(Role.SECURITY_AUDITOR, FINANCE))
    http = make_http(answering_model(), extra_policies=[auditor_policy])
    created = http.create(ALICE).json()

    url = f"{COPILOT_PREFIX}/conversations/{created['id']}/messages"
    anonymous = http.client.post(url, json={"text": "hi", "context": {}})
    assert anonymous.status_code == 401
    assert http.create(AUDITOR).status_code == 403  # no data.read in any domain
    assert http.create(CAROL).status_code == 201  # a viewer holds data.read


def test_unconfigured_copilot_fails_closed_with_503() -> None:
    http = make_http(answering_model(), configured=False)
    assert http.create(ALICE).status_code == 503


def test_unknown_conversation_is_404_before_any_stream() -> None:
    http = make_http(answering_model())
    response = http.send(ALICE, "00000000-0000-4000-8000-000000000000")
    assert response.status_code == 404


def test_context_with_a_non_allowlisted_filter_key_is_refused_before_streaming() -> None:
    http = make_http(answering_model())
    created = http.create(ALICE).json()
    response = http.send(ALICE, created["id"], filters={"domain_id": "other"})
    assert 400 <= response.status_code < 500
    assert not response.headers["content-type"].startswith("text/event-stream")
    assert http.model.requests == []


def test_overlong_text_and_extra_members_are_rejected() -> None:
    http = make_http(answering_model())
    created = http.create(ALICE).json()
    url = f"{COPILOT_PREFIX}/conversations/{created['id']}/messages"
    too_long = http.client.post(
        url, headers=http.headers(ALICE), json={"text": "x" * 8001, "context": {}}
    )
    assert too_long.status_code == 422
    smuggled = http.client.post(
        url,
        headers=http.headers(ALICE),
        json={"text": "hi", "context": {}, "customer_id": "fabrikam"},
    )
    assert smuggled.status_code == 422


def test_every_copilot_route_declares_a_permission() -> None:
    http = make_http(answering_model())
    undeclared = [r for r in undeclared_routes(http.api.h.app) if COPILOT_PREFIX in str(r)]
    assert undeclared == []


def test_principal_ids_never_appear_in_responses() -> None:
    http = make_http(answering_model())
    created = http.create(ALICE)
    events = http.send(ALICE, created.json()["id"])
    real = principal(ALICE)
    assert real not in created.text and real not in events.text and ALICE not in events.text


def _events(text: str) -> list[tuple[str, dict[str, Any]]]:
    from copilot_http_harness import parse_sse  # pyright: ignore[reportMissingImports]

    return parse_sse(text)

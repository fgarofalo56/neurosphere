"""Chat drafts, never executes (PRP-19 item 2): same intent, same hash, same executor as REST."""

from __future__ import annotations

from typing import Any

from action_plane_harness import (  # pyright: ignore[reportMissingImports]
    ALICE,
    CAROL,
    FINANCE,
    KIND,
    TARGET_VERSION,
    draft_body,
)
from copilot_api_harness import (  # pyright: ignore[reportMissingImports]
    FINANCE as FINANCE_DOMAIN,
)
from copilot_api_harness import (  # pyright: ignore[reportMissingImports]
    OPERATIONS,
    ScriptedAdapter,
    agent,
    call,
    make_world,
    say,
)
from copilot_http_harness import Http, make_http  # pyright: ignore[reportMissingImports]
from neurosphere_api.copilot.models import ActionSuggestionEvent, DeniedEvent, ErrorEvent
from neurosphere_core.actions import compute_confirmation_hash
from neurosphere_core.copilot.models import ActionSuggestion, Completed

assert FINANCE == FINANCE_DOMAIN
TARGET = "commercial:contoso:foundry:agent:chat-prod"
OPS_TARGET = "commercial:contoso:foundry:agent:ops-prod"


def _world() -> Any:
    return make_world(
        [agent(TARGET, FINANCE), agent(OPS_TARGET, OPERATIONS)],
        recs=[],
    )


def _diff(new_version: str = "2026-06-15") -> dict[str, Any]:
    return {
        "format": "json_patch",
        "operations": [
            {"op": "test", "path": "/model/version", "value": "2024-08-06"},
            {"op": "replace", "path": "/model/version", "value": new_version},
        ],
    }


def propose_args(target: str = TARGET) -> dict[str, Any]:
    return {
        "action_kind": KIND,
        "target": {"canonical_id": target, "entity_type": "agent"},
        "target_version": TARGET_VERSION,
        "proposed_diff": _diff(),
    }


def _drafting_model(target: str = TARGET) -> ScriptedAdapter:
    return ScriptedAdapter(
        call("propose_action", propose_args(target)),
        say("I drafted the swap for you to confirm [cite:r1]."),
    )


def _rest_body(key: str, new_version: str = "2026-06-15") -> dict[str, Any]:
    body = draft_body(key=key, new_version=new_version, target_id=TARGET)
    body["target"] = {"canonical_id": TARGET, "entity_type": "agent"}
    return body


def _suggestion(call_id: str = "s1") -> Any:
    return lambda _r: [
        ActionSuggestion(
            call_id=call_id,
            action_type=KIND,
            target_ref=TARGET,
            rationale="cheaper at equal quality",
            parameters={"target_version": TARGET_VERSION, "proposed_diff": _diff()},
        ),
        Completed(stop_reason="tool_calls"),
    ]


def _suggestions(events: list[tuple[str, dict[str, Any]]]) -> list[ActionSuggestionEvent]:
    return [ActionSuggestionEvent.model_validate(d) for n, d in events if n == "action_suggestion"]


def _intent(http: Http, intent_id: str) -> dict[str, Any]:
    response = http.api.get_intent(intent_id, who=ALICE)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_chat_draft_is_a_drafted_intent_that_is_never_confirmed_or_executed() -> None:
    http = make_http(_drafting_model(), world=_world())
    events = http.ask(ALICE, "Swap the chat deployment to the newer model")
    assert events[-1][0] == "done"

    [suggestion] = _suggestions(events)
    assert suggestion.domain_id == FINANCE and suggestion.action_type == KIND
    assert suggestion.target == {"canonical_id": TARGET, "entity_type": "agent"}
    assert suggestion.intent_hash.startswith("sha256:")

    stored = _intent(http, suggestion.intent_id)
    assert stored["intent"]["state"] == "drafted"
    assert stored["intent"]["channel"] == "chat"
    assert stored["intent"]["confirmation_hash"] is None
    assert stored["execution"] is None and stored["review_item_id"] is None
    # No connector call of any kind: the API only ever dry-runs, and nothing was validated.
    assert http.api.connector.forbidden_calls == [] and http.api.connector.dry_runs == []
    # The action_suggestion event comes after the tokens and before the terminal event.
    names = [n for n, _ in events]
    assert names.index("action_suggestion") > names.index("token")
    assert names[-1] == "done"


def test_chat_intent_hash_equals_the_rest_intent_hash_for_the_same_change() -> None:
    http = make_http(_drafting_model(), world=_world())
    [suggestion] = _suggestions(http.ask(ALICE))

    rest = http.api.draft(ALICE, _rest_body("idem-rest-same-change-0001"))
    assert rest.status_code == 201, rest.text
    rest_intent = rest.json()["intent"]

    assert rest_intent["intent_id"] != suggestion.intent_id  # two intents, one change
    assert compute_confirmation_hash(rest_intent) == suggestion.intent_hash
    chat_intent = _intent(http, suggestion.intent_id)["intent"]
    assert compute_confirmation_hash(chat_intent) == suggestion.intent_hash
    assert (chat_intent["channel"], rest_intent["channel"]) == ("chat", "rest")


def test_a_different_change_hashes_differently() -> None:
    http = make_http(_drafting_model(), world=_world())
    [suggestion] = _suggestions(http.ask(ALICE))
    other = http.api.draft(ALICE, _rest_body("idem-rest-other-change-0001", "2026-07-01"))
    assert compute_confirmation_hash(other.json()["intent"]) != suggestion.intent_hash


def test_a_model_action_hint_is_drafted_through_the_same_checked_path() -> None:
    model = ScriptedAdapter(
        _suggestion(),
        say("Drafted [cite:r1]."),
    )
    http = make_http(model, world=_world())
    events = http.ask(ALICE)
    [suggestion] = _suggestions(events)
    assert _intent(http, suggestion.intent_id)["intent"]["state"] == "drafted"
    rest = http.api.draft(ALICE, _rest_body("idem-rest-hint-change-0001"))
    assert compute_confirmation_hash(rest.json()["intent"]) == suggestion.intent_hash


def test_a_viewer_cannot_have_an_action_drafted_for_them() -> None:
    http = make_http(_drafting_model(), world=_world())
    events = http.ask(CAROL)  # viewer: data.read but not action.propose
    denied = DeniedEvent.model_validate(events[-1][1])
    assert events[-1][0] == "denied" and denied.reason_code == "permission_denied"
    assert not _suggestions(events)
    listing = http.api.call("GET", ALICE, http.api.intents_path()).json()
    assert listing["items"] == []


def test_a_target_in_a_domain_outside_the_scope_cannot_be_drafted() -> None:
    http = make_http(_drafting_model(OPS_TARGET), world=_world())
    events = http.ask(ALICE)  # steward on finance only
    assert events[-1][0] == "denied"
    assert DeniedEvent.model_validate(events[-1][1]).reason_code == "target_out_of_scope"
    assert http.api.call("GET", ALICE, http.api.intents_path(OPERATIONS)).status_code == 403


def test_without_an_action_plane_drafting_fails_closed_and_reads_still_work() -> None:
    http = make_http(_drafting_model(), world=_world(), action_plane=False)
    events = http.ask(ALICE)
    assert events[-1][0] == "error"
    error = ErrorEvent.model_validate(events[-1][1])
    assert (error.code, error.detail) == ("dependency_transient", "action_plane_unconfigured")
    assert not _suggestions(events)


def test_chat_has_no_confirm_or_execute_path() -> None:
    import neurosphere_api.copilot as copilot

    forbidden = {"confirm", "execute", "apply", "approve", "rollback", "validate"}
    surface = {name.lower() for name in dir(copilot.ActionPlaneDrafter) if not name.startswith("_")}
    assert surface.isdisjoint(forbidden)
    assert {"draft"} <= surface

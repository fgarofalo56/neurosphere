"""Checks shared by the in-memory (CI) and Cosmos-emulator (integration) wiring tests."""

from __future__ import annotations

from typing import Any

from action_plane_harness import ALICE, CAROL, FINANCE  # pyright: ignore[reportMissingImports]
from copilot_http_harness import (  # pyright: ignore[reportMissingImports]
    COPILOT_PREFIX,
    parse_sse,
)
from reports_harness import principal, report_body  # pyright: ignore[reportMissingImports]

from .support import (
    TARGET,
    Wiring,
    action_suggestion_adapter,
    cited_answer_adapter,
    text_answer_adapter,
)

# ``context`` first, tools, tokens, then citations/charts/suggestions, then exactly one terminal.
_ORDER = ["context", "tool", "token", "citation", "chart", "action_suggestion"]
_TERMINALS = {"done", "abstain", "denied", "error"}


def _assert_contract_order(names: list[str]) -> None:
    assert names[0] == "context"
    assert names[-1] in _TERMINALS and not _TERMINALS & set(names[:-1])
    ranks = [_ORDER.index(n) for n in names[:-1]]
    assert ranks == sorted(ranks), names


def check_conversation_stream_and_ownership(wired: Wiring) -> None:
    wired.use_model(cited_answer_adapter())
    created = wired.create_conversation(ALICE)
    assert created.status_code == 201, created.text
    body = created.json()
    assert {"id", "created_at", "retention_class", "expires_at"} <= set(body)

    response = wired.send(ALICE, body["id"])
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    names = [n for n, _ in events]
    _assert_contract_order(names)
    assert names[-1] == "done", events
    assert "tool" in names and "token" in names and "citation" in names
    citation = next(d for n, d in events if n == "citation")
    assert citation["freshness"] in {"fresh", "stale", "unknown"}

    # An answer with no backing tool record abstains (the recorded plain-text answer).
    wired.use_model(text_answer_adapter())
    second = wired.create_conversation(ALICE).json()["id"]
    abstained = parse_sse(wired.send(ALICE, second).text)
    _assert_contract_order([n for n, _ in abstained])
    assert abstained[-1][0] == "abstain"

    # Conversations are user scoped: another user gets 404, not 403, and sees nothing listed.
    path = f"{COPILOT_PREFIX}/conversations/{body['id']}"
    assert wired.client.get(path, headers=wired.headers(ALICE)).status_code == 200
    assert wired.client.get(path, headers=wired.headers(CAROL)).status_code == 404
    assert wired.client.delete(path, headers=wired.headers(CAROL)).status_code == 404
    assert (
        wired.client.post(
            f"{path}/messages", headers=wired.headers(CAROL), json={"text": "hi", "context": {}}
        ).status_code
        == 404
    )
    listing = wired.client.get(f"{COPILOT_PREFIX}/conversations", headers=wired.headers(CAROL))
    assert listing.status_code == 200 and listing.json()["items"] == []
    mine = wired.client.get(f"{COPILOT_PREFIX}/conversations", headers=wired.headers(ALICE))
    assert {c["id"] for c in mine.json()["items"]} == {body["id"], second}


def _names(response: Any) -> list[str]:
    assert response.status_code == 200, response.text
    values = response.json()["chart_plan"]["spec"]["data"]["values"]
    return sorted(row["display_name"] for row in values)


def check_report_runs_per_viewer_scope(wired: Wiring) -> None:
    created = wired.reports("POST", ALICE, json=report_body())
    assert created.status_code == 201, created.text
    report_id = created.json()["id"]

    # Not shared yet: invisible to a FINANCE viewer.
    assert wired.reports("POST", CAROL, f"/{report_id}/run").status_code == 404

    shared = wired.reports(
        "POST", ALICE, f"/{report_id}/shares", json={"principal_id": principal(CAROL)}
    )
    assert shared.status_code == 200, shared.text

    owner_rows = _names(wired.reports("POST", ALICE, f"/{report_id}/run"))
    viewer_response = wired.reports("POST", CAROL, f"/{report_id}/run")
    viewer_rows = _names(viewer_response)
    assert len(owner_rows) == 2 and len(viewer_rows) == 1  # FINANCE + OPERATIONS vs FINANCE only
    assert set(viewer_rows) < set(owner_rows)
    assert owner_rows != viewer_rows
    # Re-authorization on every run is covered in depth by services/api/tests/reports; this
    # proves the wiring (real authz + registry + store) yields scope-dependent rows.


def check_action_suggestion_is_a_draft(wired: Wiring) -> None:
    wired.use_model(action_suggestion_adapter())
    conversation_id = wired.create_conversation(ALICE).json()["id"]
    response = wired.send(ALICE, conversation_id, "Swap the chat deployment to the newer model")
    assert response.status_code == 200, response.text
    events = parse_sse(response.text)
    names = [n for n, _ in events]
    _assert_contract_order(names)
    assert names[-1] == "done", events
    [suggestion] = [d for n, d in events if n == "action_suggestion"]
    assert suggestion["domain_id"] == FINANCE and suggestion["target"]["canonical_id"] == TARGET

    stored = wired.api.get_intent(suggestion["intent_id"], who=ALICE)
    assert stored.status_code == 200, stored.text
    view = stored.json()
    assert view["intent"]["state"] == "drafted"
    assert view["intent"]["channel"] == "chat"
    assert view["intent"]["confirmation_hash"] is None
    assert view["execution"] is None
    # Chat never validated, confirmed or executed it: the connector was never touched.
    assert wired.api.connector.dry_runs == [] and wired.api.connector.forbidden_calls == []

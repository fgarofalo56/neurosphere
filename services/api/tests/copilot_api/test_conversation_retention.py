"""Stored conversations (PRP-19 item 2): redacted, retained per class, owner-only, deletable."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from action_plane_harness import ALICE, BOB, FINANCE  # pyright: ignore[reportMissingImports]
from copilot_api_harness import (  # pyright: ignore[reportMissingImports]
    ScriptedAdapter,
    call,
    query_args,
    say,
)
from copilot_http_harness import (  # pyright: ignore[reportMissingImports]
    COPILOT_PREFIX,
    Http,
    make_http,
)
from neurosphere_api.copilot import CopilotSettings, InMemoryConversationStore

DAY = 86400


def answering() -> ScriptedAdapter:
    return ScriptedAdapter(
        call("search_catalog", {"query": query_args("agent", domain=FINANCE)}),
        say("The agent is active [cite:r1]."),
    )


def now_of(http: Http) -> datetime:
    return datetime.fromtimestamp(http.api.h.clock(), UTC)


def get(http: Http, who: str, conversation_id: str) -> Any:
    return http.client.get(
        f"{COPILOT_PREFIX}/conversations/{conversation_id}", headers=http.headers(who)
    )


def stored_blob(http: Http) -> str:
    return json.dumps(http.store.raw_documents())


# -- creation and retention ---------------------------------------------------------------------


def test_create_reports_the_retention_class_and_expiry() -> None:
    http = make_http(answering())
    body = http.create(ALICE).json()
    assert set(body) == {"id", "created_at", "retention_class", "expires_at"}
    assert body["retention_class"] == "standard"
    expected = (now_of(http) + timedelta(days=30)).isoformat(timespec="milliseconds")
    assert body["expires_at"] == expected.replace("+00:00", "Z")


def test_every_stored_turn_carries_its_retention_class_and_expiry() -> None:
    settings = CopilotSettings(
        retention={"standard": timedelta(days=30), "short": timedelta(days=2)},
        default_retention_class="short",
    )
    http = make_http(answering(), settings=settings)
    cid = http.create(ALICE).json()["id"]
    assert http.send(ALICE, cid).status_code == 200

    view = get(http, ALICE, cid).json()
    assert [t["role"] for t in view["turns"]] == ["user", "assistant"]
    for t in view["turns"]:
        assert t["retention_class"] == "short"
        created = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00"))
        assert datetime.fromisoformat(
            t["expires_at"].replace("Z", "+00:00")
        ) == created + timedelta(days=2)
    assert view["retention_class"] == "short"


def test_turns_and_conversations_disappear_once_retention_has_passed() -> None:
    http = make_http(answering())
    cid = http.create(ALICE).json()["id"]
    http.send(ALICE, cid)
    assert get(http, ALICE, cid).status_code == 200

    http.api.h.clock.advance(31 * DAY)  # tokens are minted per request, so auth keeps working
    assert get(http, ALICE, cid).status_code == 404
    listing = http.client.get(f"{COPILOT_PREFIX}/conversations", headers=http.headers(ALICE))
    assert listing.json() == {"items": [], "next_cursor": None}
    assert http.send(ALICE, cid).status_code == 404


def test_an_unknown_retention_class_is_a_configuration_error() -> None:
    with pytest.raises(ValueError, match="retention"):
        CopilotSettings(default_retention_class="forever")


# -- redaction ----------------------------------------------------------------------------------


def test_stored_text_is_redacted_and_people_are_pseudonymized() -> None:
    email = "alice.smith@contoso.example"
    guid = str(uuid4())
    key_name = "pass" + "word"  # assembled so source scanners see no credential assignment
    value = uuid4().hex
    leak = f"{key_name}={value}"
    http = make_http(answering())
    cid = http.create(ALICE).json()["id"]
    text = f"Ask {email} about {guid}, my {leak}"
    assert http.send(ALICE, cid, text, filters={"environment": email}).status_code == 200

    blob = stored_blob(http)
    for original in (email, guid, leak, value):
        assert original not in blob
    view = get(http, ALICE, cid)
    assert email not in view.text and guid not in view.text
    user = view.json()["turns"][0]["text"]
    assert "[person]" in user and "[id]" in user and "[credential]" in user


def test_person_pseudonyms_are_stable_and_keyed_when_a_key_is_configured() -> None:
    settings = CopilotSettings(pseudonym_key=uuid4().bytes)
    http = make_http(ScriptedAdapter(say("x")), settings=settings)
    texts = [
        "alice.smith@contoso.example",
        "alice.smith@contoso.example",
        "bob.jones@contoso.example",
    ]
    pseudonyms: list[str] = []
    for text in texts:
        cid = http.create(ALICE).json()["id"]
        http.send(ALICE, cid, f"who is {text}?")
        pseudonyms.append(get(http, ALICE, cid).json()["turns"][0]["text"])
    assert pseudonyms[0] == pseudonyms[1] != pseudonyms[2]
    assert "person-" in pseudonyms[0] and "@" not in "".join(pseudonyms)
    assert "alice.smith" not in stored_blob(http)


def test_a_refused_or_abstained_turn_stores_status_and_reason_but_no_answer_text() -> None:
    http = make_http(ScriptedAdapter(say("Confident but unsupported [cite:r9].")))
    cid = http.create(ALICE).json()["id"]
    http.send(ALICE, cid)
    assistant = get(http, ALICE, cid).json()["turns"][1]
    assert (assistant["status"], assistant["reason_code"]) == ("abstain", "no_authorized_evidence")
    assert assistant["text"] == "" and assistant["citations"] == []

    denied = make_http(ScriptedAdapter(call("delete_everything", {})))
    cid = denied.create(ALICE).json()["id"]
    denied.send(ALICE, cid)
    turn = get(denied, ALICE, cid).json()["turns"][1]
    assert (turn["status"], turn["reason_code"], turn["text"]) == (
        "denied",
        "tool_not_registered",
        "",
    )


def test_answered_turns_store_the_numbered_text_and_the_citations() -> None:
    http = make_http(answering())
    cid = http.create(ALICE).json()["id"]
    http.send(ALICE, cid)
    assistant = get(http, ALICE, cid).json()["turns"][1]
    assert assistant["status"] == "answered" and assistant["text"] == "The agent is active [1]."
    assert [c["record_id"] for c in assistant["citations"]] == [
        "commercial:contoso:foundry:agent:fin-1"
    ]
    assert assistant["citations"][0]["freshness"] in {"fresh", "stale", "unknown"}


def test_tool_results_and_the_system_prompt_are_never_stored() -> None:
    http = make_http(answering())
    cid = http.create(ALICE).json()["id"]
    http.send(ALICE, cid)
    blob = stored_blob(http)
    assert "content_trust" not in blob and "Answer only from" not in blob
    assert "cite_as" not in blob


# -- ownership ----------------------------------------------------------------------------------


def test_another_user_gets_404_for_read_delete_and_message() -> None:
    http = make_http(answering())
    cid = http.create(BOB).json()["id"]
    http.send(BOB, cid)

    unknown = "00000000-0000-4000-8000-000000000000"
    for method, suffix, kwargs in (
        ("GET", "", {}),
        ("DELETE", "", {}),
        ("POST", "/messages", {"json": {"text": "hi", "context": {}}}),
    ):
        mine = http.client.request(
            method,
            f"{COPILOT_PREFIX}/conversations/{cid}{suffix}",
            headers=http.headers(ALICE),
            **kwargs,
        )
        none = http.client.request(
            method,
            f"{COPILOT_PREFIX}/conversations/{unknown}{suffix}",
            headers=http.headers(ALICE),
            **kwargs,
        )
        assert mine.status_code == 404, (method, mine.status_code)
        # Indistinguishable from a conversation that never existed (URL and request id differ).
        stable = {k: v for k, v in mine.json().items() if k not in {"instance", "correlation_id"}}
        assert stable == {
            k: v for k, v in none.json().items() if k not in {"instance", "correlation_id"}
        }
    assert len(get(http, BOB, cid).json()["turns"]) == 2  # untouched


def test_listing_shows_only_the_callers_own_conversations_newest_first_and_paged() -> None:
    http = make_http(answering())
    mine = []
    for _ in range(3):
        mine.append(http.create(ALICE).json()["id"])
        http.api.h.clock.advance(1)
    http.create(BOB)

    url = f"{COPILOT_PREFIX}/conversations"
    first = http.client.get(url, params={"limit": 2}, headers=http.headers(ALICE)).json()
    assert [c["id"] for c in first["items"]] == [mine[2], mine[1]] and first["next_cursor"]
    second = http.client.get(
        url, params={"limit": 2, "cursor": first["next_cursor"]}, headers=http.headers(ALICE)
    ).json()
    assert [c["id"] for c in second["items"]] == [mine[0]] and second["next_cursor"] is None
    assert not set(c["id"] for c in first["items"] + second["items"]) & {
        c["id"] for c in http.client.get(url, headers=http.headers(BOB)).json()["items"]
    }


def test_delete_removes_everything_the_conversation_stored() -> None:
    http = make_http(answering())
    cid = http.create(ALICE).json()["id"]
    http.send(ALICE, cid)
    assert http.store.raw_documents()
    deleted = http.client.delete(
        f"{COPILOT_PREFIX}/conversations/{cid}", headers=http.headers(ALICE)
    )
    assert deleted.status_code == 204 and deleted.content == b""
    assert get(http, ALICE, cid).status_code == 404
    assert http.store.raw_documents() == []
    again = http.client.delete(f"{COPILOT_PREFIX}/conversations/{cid}", headers=http.headers(ALICE))
    assert again.status_code == 404


# -- history ------------------------------------------------------------------------------------


def test_only_answered_exchanges_are_replayed_to_the_model() -> None:
    first_answer = [
        call("search_catalog", {"query": query_args("agent", domain=FINANCE)}),
        say("The agent is active [cite:r1]."),
    ]
    abstain = say("I will invent something [cite:r9].")
    model = ScriptedAdapter(*first_answer, abstain, say("final [cite:r1]."))
    http = make_http(model)
    cid = http.create(ALICE).json()["id"]
    http.send(ALICE, cid, "first question")  # answered (2 model calls)
    http.api.h.clock.advance(5)
    http.send(ALICE, cid, "second question")  # abstains (1 model call)
    http.api.h.clock.advance(5)
    http.send(ALICE, cid, "third question")

    replayed = [t.content for t in model.requests[-1].turns]
    assert any("first question" in c for c in replayed)
    assert any("The agent is active [1]." in c for c in replayed)
    assert not any("second question" in c for c in replayed)
    assert not any("invent" in c for c in replayed)
    assert "third question" in replayed[-1]


def test_a_store_outage_surfaces_as_an_error_not_a_silent_loss() -> None:
    class Failing(InMemoryConversationStore):
        async def append(self, *args: Any, **kwargs: Any) -> bool:
            from neurosphere_core.errors import DependencyTransientError

            raise DependencyTransientError("down", reason="conversation_store_unavailable")

    http = make_http(answering(), store=Failing())
    cid = http.create(ALICE).json()["id"]
    response = http.send(ALICE, cid)
    names = [
        line.removeprefix("event: ")
        for line in response.text.split("\n")
        if line.startswith("event: ")
    ]
    assert names[-1] == "error" and "done" not in names and "token" not in names

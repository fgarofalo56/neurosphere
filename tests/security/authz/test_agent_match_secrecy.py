"""Secrecy of the agent match routes (PRP-72 item 5).

A match and a feedback post carry a distinctive task text. The text is tokenized by the matcher
(at most 32 normalized tokens are stored by design, so later similar tasks can find the match);
the TEXT ITSELF and the caller's clear identifier must appear nowhere: not in any log record, not
in the audit chain, not in a response body beyond the match, and not in a stored match or feedback
document. Individual tokens must additionally stay out of logs and audit records.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from .test_agent_match import (
    FIN_ID,
    MATCH_BODY,
    ROUTES,
    VIEWER_FIN,
    MatchWorld,
    call,
    install,
)
from .world import World

TASK = "Quarterly Zyxwvut migration: reconcile the Initech invoices"
TOKENS = ("zyxwvut", "initech")


@pytest.fixture
def mworld(world: World) -> MatchWorld:
    return install(world)


def audit_text(world: World) -> str:
    dep = world["contoso"]
    docs: list[dict[str, Any]] = []
    for chain in sorted({chain for (chain, _doc) in dep.audit_store._docs}):  # pyright: ignore[reportPrivateUsage]
        docs.extend(dep.audit_store.raw_documents(chain))
    return json.dumps(docs, sort_keys=True)


def stored_text(mw: MatchWorld) -> str:
    store = mw.feedback
    matches = store._matches.values()  # pyright: ignore[reportPrivateUsage]
    feedback = store._feedback.values()  # pyright: ignore[reportPrivateUsage]
    return repr(list(matches)) + repr(list(feedback))


def test_task_text_and_clear_principal_leak_nowhere(
    mworld: MatchWorld, caplog: pytest.LogCaptureFixture
) -> None:
    dep = mworld.world["contoso"]
    headers = dep.bearer(VIEWER_FIN)
    with caplog.at_level(logging.DEBUG):
        matched = dep.client.post(
            ROUTES[0].path(FIN_ID), headers=headers, json={**MATCH_BODY, "task_text": TASK}
        )
        assert matched.status_code == 200, matched.text
        body = matched.json()
        candidates = body["match"]["candidates"]
        assert candidates, "the match must rank something for the feedback flow"
        feedback_body = {
            "schema_version": "1.0.0",
            "match_id": body["match"]["match_id"],
            "entity_id": str(candidates[0]["entity_id"]),
            "decision": "accepted",
            "reason_code": None,
        }
        accepted = dep.client.post(ROUTES[1].path(FIN_ID), headers=headers, json=feedback_body)
        assert accepted.status_code == 202, accepted.text
        metrics = call(dep, ROUTES[2], FIN_ID, headers)
        assert metrics.status_code == 200, metrics.text
    clear_id = VIEWER_FIN.object_id
    token = headers["Authorization"].removeprefix("Bearer ")
    outputs = {
        "log": caplog.text,
        "audit": audit_text(mworld.world),
        "stored match and feedback": stored_text(mworld),
        "feedback body": accepted.text,
        "metrics body": metrics.text,
        "match body": matched.text,
    }
    for label, text in outputs.items():
        assert TASK not in text and TASK.lower() not in text.lower(), f"{label} holds the task text"
        assert clear_id not in text, f"{label} holds the clear principal identifier"
        assert token not in text, f"{label} holds the bearer token"
    # The store was really inspected: tokens are kept by design, the text is not.
    assert "zyxwvut" in outputs["stored match and feedback"]
    assert "FeedbackRecord" in outputs["stored match and feedback"]
    for label in ("log", "audit"):
        for fragment in TOKENS:
            assert fragment not in outputs[label].lower(), f"{label} holds a task token"
    assert "task_text" not in outputs["stored match and feedback"]

"""PRP-49: telemetry model_call -> contribution carries the agent/model dimension."""

from __future__ import annotations

from neurosphere_workers.aggregates.mapping import contribution_from_event

from .support import CUST, days_ago, event_doc

AGENT = "commercial:cust-1:src-1:agent:alpha"


def test_dimension_is_copied_into_the_event_fact() -> None:
    loaded = event_doc(
        "e1",
        at=days_ago(1),
        duration_ms=120,
        outcome="error",
        agent=AGENT,
        provider="azure_openai",
        model="GPT-4o",
        input_tokens=10,
        output_tokens=5,
    )
    fact = contribution_from_event(CUST, loaded.doc_id, loaded.event)
    assert fact is not None
    assert fact.event is not None
    assert fact.event.agent_id == AGENT
    assert (fact.event.provider, fact.event.model) == ("azure_openai", "GPT-4o")
    assert (fact.event.input_tokens, fact.event.output_tokens) == (10, 5)


def test_missing_dimension_stays_none_not_zero() -> None:
    loaded = event_doc("e2", at=days_ago(1), duration_ms=None, outcome=None)
    fact = contribution_from_event(CUST, loaded.doc_id, loaded.event)
    assert fact is not None
    assert fact.event is not None
    assert fact.event.agent_id is None
    assert fact.event.provider is None
    assert fact.event.input_tokens is None
    assert fact.event.output_tokens is None
    assert fact.event.duration_ms is None

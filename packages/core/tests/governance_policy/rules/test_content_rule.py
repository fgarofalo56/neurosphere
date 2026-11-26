"""``content_rule`` over detection-finding counts from the ``InteractionFindingReader`` port."""

from __future__ import annotations

import ast
import inspect

from neurosphere_core.governance.policy.rules import (
    ContentRuleEvaluator,
    InteractionFindingCount,
    InteractionFindingReader,
)
from neurosphere_core.governance.policy.rules import content_rule as content_rule_module

from .rules_helpers import FakeFindingReader, agent_id, context, dom, only_rule, policy

CARDS = {
    "detected_categories": ["payment_card", "us_ssn"],
    "min_count": 3,
    "parts": ["prompt"],
    "window_minutes": 60,
}


def _count(name: str, category: str, count: int, *ids: str) -> InteractionFindingCount:
    return InteractionFindingCount(
        subject_id=agent_id(name),
        subject_type="agent",
        domain_id=dom("a"),
        category=category,
        count=count,
        interaction_ids=ids,
    )


async def test_subject_at_min_count_is_a_finding_with_counts_and_ids() -> None:
    reader = FakeFindingReader(
        [
            _count("leaky", "payment_card", 2, "int-1", "int-2"),
            _count("leaky", "us_ssn", 1, "int-3"),
            _count("quiet", "payment_card", 1, "int-4"),
        ]
    )
    definition = policy("content_rule", CARDS)

    outcome = await ContentRuleEvaluator(reader).evaluate(
        context("a"), definition, only_rule(definition)
    )

    assert not outcome.truncated
    assert len(outcome.findings) == 1
    finding = outcome.findings[0]
    assert finding.subject_id == agent_id("leaky")
    assert finding.counts == {"payment_card": 2, "us_ssn": 1}
    assert finding.categories == ("payment_card", "us_ssn")
    assert {e.ref for e in finding.evidence} == {"int-1", "int-2", "int-3"}
    assert {e.kind for e in finding.evidence} == {"interaction_record"}
    assert reader.calls[0]["categories"] == ["payment_card", "us_ssn"]


async def test_below_min_count_is_clean() -> None:
    reader = FakeFindingReader([_count("quiet", "payment_card", 2, "int-4")])
    definition = policy("content_rule", CARDS)

    outcome = await ContentRuleEvaluator(reader).evaluate(
        context("a"), definition, only_rule(definition)
    )

    assert outcome.findings == ()


async def test_reader_truncation_is_reported() -> None:
    reader = FakeFindingReader(
        [_count(f"agent-{i}", "payment_card", 5, f"int-{i}") for i in range(3)]
    )
    definition = policy("content_rule", CARDS)

    outcome = await ContentRuleEvaluator(reader).evaluate(
        context("a", max_subjects=2), definition, only_rule(definition)
    )

    assert outcome.truncated
    assert reader.calls[0]["limit"] == 2
    assert len(outcome.findings) == 2


def test_port_and_evaluator_carry_no_content_fields() -> None:
    port_params = set(inspect.signature(InteractionFindingReader.count_findings).parameters)
    assert port_params.isdisjoint({"body", "text", "content", "prompt", "response"})
    assert set(InteractionFindingCount.model_fields).isdisjoint(
        {"body", "text", "content", "matched", "spans"}
    )
    tree = ast.parse(inspect.getsource(content_rule_module))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert names.isdisjoint({"body", "redacted_text", "spans", "content"})

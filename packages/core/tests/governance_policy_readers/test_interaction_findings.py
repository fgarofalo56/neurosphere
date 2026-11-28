"""PRP-104 item 8: ``InteractionFindingReaderAdapter`` over the interaction metadata index.

Counts per (subject, category) in a window, filtered by category and part, bounded by subjects
and by index pages; the scope narrows domains and never widens them; content is never read.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord
from neurosphere_contracts.policy.v1.policy_definition import PolicyDefinition
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.governance.policy.readers import (
    MAX_INDEX_PAGES_PER_CALL,
    IndexQueryable,
    InteractionFindingReaderAdapter,
    index_only_source,
)
from neurosphere_core.governance.policy.rules import (
    ContentRuleEvaluator,
    InteractionFindingReader,
)
from neurosphere_core.governance.policy.rules.base import RuleContext, RunBudget
from neurosphere_core.governance.policy.rules.findings_port import InteractionFindingCount
from neurosphere_core.interactions import (
    IndexPage,
    InMemoryInteractionIndex,
    InteractionQuery,
)
from neurosphere_core.scope import IdentityScope

CUSTOMER = "acme"
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
START = NOW - timedelta(hours=1)
_POLICY_EXAMPLES = (
    Path(__file__).resolve().parents[3] / "contracts" / "schemas" / "policy" / "v1" / "examples"
) / "valid"


def dom(name: str) -> str:
    return f"commercial:{CUSTOMER}:neurosphere:domain:{name}"


def agent(name: str) -> str:
    return f"commercial:{CUSTOMER}:foundry:agent:{name}"


def make_scope(*domains: str, customer: str = CUSTOMER) -> IdentityScope:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": "commercial",
        "customer_id": customer,
        "principal": {
            "principal_id": f"commercial:{customer}:idp:person:p-0001",
            "principal_pseudonym": "p-0001",
            "principal_kind": "user",
        },
        "roles": [{"role": "viewer", "domain_ids": [dom(d) for d in domains]}],
        "allowed_domains": [dom(d) for d in domains],
        "allowed_resources": [],
        "policy_version": "v1",
        "derived_at": "2026-01-01T00:00:00Z",
        "scope_hash": "sha256:" + hashlib.sha256(b"p-0001").hexdigest(),
    }
    return IdentityScope._from_verified_contract(ContractScope.model_validate(payload))


def _stamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def record(
    *,
    domain: str = "a",
    subject: str | None = "leaky",
    findings: dict[str, int] | None = None,
    parts: tuple[str, ...] = ("prompt",),
    at: datetime = NOW - timedelta(minutes=5),
    customer: str = CUSTOMER,
    **overrides: Any,
) -> InteractionRecord:
    interaction_id = str(uuid.uuid4())
    doc: dict[str, Any] = {
        "schema_version": "1.2.0",
        "interaction_id": interaction_id,
        "cloud": "commercial",
        "customer_id": customer,
        "domain_id": dom(domain),
        "source_id": "otel-gateway",
        "event_id": "evt-" + interaction_id[:8],
        "correlation_id": "corr-" + interaction_id[:8],
        "capture_source": "edge_push",
        "occurred_at": _stamp(at),
        "captured_at": _stamp(at),
        "agent_id": agent(subject) if subject else None,
        "capture_policy_id": "support-capture",
        "capture_policy_version": 1,
        "detector_set_version": "detectors-1.0",
        "redaction_state": "redacted",
        "parts": [{"part": p, "char_count": 10, "truncated": False} for p in parts],
        "content_ref": None,
        "findings_summary": [
            {"category": c, "count": n, "action": "replaced"}
            for c, n in (findings or {"payment_card": 1}).items()
        ],
        "expires_at": "2027-02-18T10:15:01Z",
    }
    doc.update(overrides)
    return InteractionRecord.model_validate(doc)


class SpyStore:
    """An ``InteractionStore`` look-alike: queries the index, explodes on any content read."""

    def __init__(self) -> None:
        self.index = InMemoryInteractionIndex()
        self.queries: list[InteractionQuery] = []
        self.content_reads = 0

    async def add(self, *records: InteractionRecord) -> list[str]:
        for rec in records:
            await self.index.create(rec)
        return [r.interaction_id.root for r in records]

    async def query_index(self, query: InteractionQuery) -> IndexPage:
        self.queries.append(query)
        return await self.index.query(query)

    async def read_content(self, *_args: Any, **_kwargs: Any) -> Any:
        self.content_reads += 1
        raise AssertionError("the finding reader must never read content")

    async def get_metadata(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("not needed")


async def _count(
    reader: InteractionFindingReaderAdapter,
    *,
    scope: IdentityScope | None = None,
    domains: tuple[str, ...] = ("a",),
    categories: tuple[str, ...] = ("payment_card",),
    parts: tuple[str, ...] = (),
    limit: int = 10,
) -> Any:
    return await reader.count_findings(
        scope or make_scope("a", "b"),
        domain_ids=[dom(d) for d in domains],
        categories=list(categories),
        parts=list(parts),
        start=START,
        end=NOW,
        limit=limit,
    )


def _by_key(page: Any) -> dict[tuple[str, str], InteractionFindingCount]:
    return {(row.subject_id, row.category): row for row in page.counts}


def test_adapter_implements_the_port() -> None:
    reader = InteractionFindingReaderAdapter(SpyStore())
    assert isinstance(reader, InteractionFindingReader)
    assert isinstance(SpyStore(), IndexQueryable)


async def test_counts_per_subject_and_category_with_interaction_ids() -> None:
    store = SpyStore()
    first = await store.add(
        record(findings={"payment_card": 2, "us_ssn": 1}),
        record(findings={"payment_card": 3}),
        record(subject="quiet", findings={"email_address": 4}),
    )
    page = await _count(
        InteractionFindingReaderAdapter(store), categories=("payment_card", "us_ssn")
    )
    rows = _by_key(page)
    assert set(rows) == {(agent("leaky"), "payment_card"), (agent("leaky"), "us_ssn")}
    card = rows[(agent("leaky"), "payment_card")]
    assert card.count == 5
    assert card.subject_type == "agent"
    assert card.domain_id == dom("a")
    assert set(card.interaction_ids) == set(first[:2])
    assert rows[(agent("leaky"), "us_ssn")].interaction_ids == (first[0],)
    assert not page.truncated
    assert store.content_reads == 0


async def test_window_is_start_inclusive_end_exclusive() -> None:
    store = SpyStore()
    inside = await store.add(record(at=START))
    await store.add(record(at=NOW), record(at=START - timedelta(seconds=1)))
    page = await _count(InteractionFindingReaderAdapter(store))
    assert [row.interaction_ids for row in page.counts] == [tuple(inside)]
    assert all(q.captured_from == START and q.captured_before == NOW for q in store.queries)


async def test_categories_filter_server_side_and_count_only_that_category() -> None:
    store = SpyStore()
    await store.add(record(findings={"email_address": 7, "payment_card": 1}))
    page = await _count(InteractionFindingReaderAdapter(store))
    assert [(r.category, r.count) for r in page.counts] == [("payment_card", 1)]
    assert {q.detected_category for q in store.queries} == {"payment_card"}


async def test_parts_select_records_by_captured_part_and_empty_means_any() -> None:
    store = SpyStore()
    prompt_only = await store.add(record(parts=("prompt",)))
    tool = await store.add(record(parts=("tool_output", "response")))
    reader = InteractionFindingReaderAdapter(store)

    narrowed = await _count(reader, parts=("tool_output",))
    assert [r.interaction_ids for r in narrowed.counts] == [tuple(tool)]
    any_part = await _count(reader, parts=())
    assert set(any_part.counts[0].interaction_ids) == set(prompt_only + tool)


async def test_limit_caps_subjects_and_marks_truncated() -> None:
    store = SpyStore()
    await store.add(*(record(subject=f"agent-{i}") for i in range(3)))
    page = await _count(InteractionFindingReaderAdapter(store), limit=2)
    assert page.truncated
    assert sorted({r.subject_id for r in page.counts}) == [agent("agent-0"), agent("agent-1")]

    full = await _count(InteractionFindingReaderAdapter(store), limit=3)
    assert not full.truncated
    assert len({r.subject_id for r in full.counts}) == 3


async def test_page_budget_bounds_the_scan_and_marks_truncated() -> None:
    store = SpyStore()
    await store.add(*(record() for _ in range(250)))  # 3 index pages of 100
    capped = await _count(InteractionFindingReaderAdapter(store, max_pages=2))
    assert capped.truncated
    assert capped.counts[0].count == 200
    assert len(store.queries) == 2
    assert len(capped.counts[0].interaction_ids) == 50  # the port's evidence cap

    store.queries.clear()
    full = await _count(InteractionFindingReaderAdapter(store))
    assert not full.truncated
    assert full.counts[0].count == 250
    assert len(store.queries) == 3
    assert MAX_INDEX_PAGES_PER_CALL == 50


async def test_domains_outside_scope_are_dropped_never_widened() -> None:
    store = SpyStore()
    await store.add(record(domain="a"), record(domain="b", subject="other"))
    page = await _count(
        InteractionFindingReaderAdapter(store), scope=make_scope("a"), domains=("a", "b")
    )
    assert {r.domain_id for r in page.counts} == {dom("a")}
    assert {q.domain_id for q in store.queries} == {dom("a")}
    assert {q.customer_id for q in store.queries} == {CUSTOMER}

    store.queries.clear()
    nothing = await _count(
        InteractionFindingReaderAdapter(store), scope=make_scope("a"), domains=("b",)
    )
    assert nothing.counts == ()
    assert store.queries == []


async def test_customer_comes_from_the_scope() -> None:
    store = SpyStore()
    await store.add(
        record(customer="other-co", domain_id="commercial:other-co:neurosphere:domain:a")
    )
    page = await _count(InteractionFindingReaderAdapter(store))
    assert page.counts == ()
    assert {q.customer_id for q in store.queries} == {CUSTOMER}


async def test_records_without_a_subject_are_not_counted_and_service_is_a_fallback() -> None:
    store = SpyStore()
    await store.add(record(subject=None))
    service = f"commercial:{CUSTOMER}:apim:service:gateway"
    await store.add(record(subject=None, service_id=service))
    page = await _count(InteractionFindingReaderAdapter(store))
    assert [(r.subject_id, r.subject_type) for r in page.counts] == [(service, "service")]


async def test_empty_inputs_answer_empty_without_querying() -> None:
    store = SpyStore()
    await store.add(record())
    reader = InteractionFindingReaderAdapter(store)
    assert (await _count(reader, categories=())).counts == ()
    assert (await _count(reader, limit=0)).counts == ()
    assert (await _count(reader, domains=())).counts == ()
    assert store.queries == []


async def test_index_only_source_wraps_a_bare_backend() -> None:
    index = InMemoryInteractionIndex()
    rec = record()
    await index.create(rec)
    reader = InteractionFindingReaderAdapter(index_only_source(index))
    page = await _count(reader)
    assert page.counts[0].interaction_ids == (rec.interaction_id.root,)
    assert not hasattr(index_only_source(index), "read_content")


def test_max_pages_must_be_positive() -> None:
    with pytest.raises(ValueError):
        InteractionFindingReaderAdapter(SpyStore(), max_pages=0)


def _content_policy() -> PolicyDefinition:
    raw = json.loads((_POLICY_EXAMPLES / "policy-definition.all-kinds.json").read_text("utf-8"))
    raw["rules"] = [
        {
            "rule_id": "rule-1",
            "kind": "content_rule",
            "severity": None,
            "applies_to": {"entity_types": [], "tags": [], "environments": [], "entity_ids": []},
            "params": {
                "detected_categories": ["payment_card"],
                "min_count": 3,
                "parts": [],
                "window_minutes": 60,
            },
        }
    ]
    return PolicyDefinition.model_validate(raw)


async def test_content_rule_evidence_is_interaction_ids_only() -> None:
    store = SpyStore()
    ids = await store.add(
        record(findings={"payment_card": 2}),
        record(findings={"payment_card": 1}),
        record(subject="quiet", findings={"payment_card": 1}),
    )
    definition = _content_policy()
    ctx = RuleContext(
        scope=make_scope("a"),
        domain_ids=(dom("a"),),
        now=NOW,
        budget=RunBudget.start(100, 60.0),
    )
    outcome = await ContentRuleEvaluator(InteractionFindingReaderAdapter(store)).evaluate(
        ctx, definition, definition.rules[0]
    )
    assert len(outcome.findings) == 1
    finding = outcome.findings[0]
    assert finding.subject_id == agent("leaky")
    assert finding.counts == {"payment_card": 3}
    assert {e.kind for e in finding.evidence} == {"interaction_record"}
    assert {e.ref for e in finding.evidence} == set(ids[:2])
    assert store.content_reads == 0

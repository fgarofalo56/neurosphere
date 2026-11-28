"""PRP-104 item 8: the API binds PRP-105's ``InteractionFindingReader`` over the shared store.

Reuses PRP-105's governance policy API harness (``governance_policy_api/govpolicy_api_harness``):
the REAL authz and governance builders over the in-memory backend. The interactions builder is
stood in for by publishing a synthetic store under ``INTERACTION_STORE``, exactly where the
real one memoizes it, so ``runtime/builders/governance.interaction_finding_reader`` takes the
factory's memoized path. Synthetic data only.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

_GOVPOLICY_TESTS = Path(__file__).resolve().parent.parent / "governance_policy_api"
if str(_GOVPOLICY_TESTS) not in sys.path:
    sys.path.insert(0, str(_GOVPOLICY_TESTS))

from govpolicy_api_harness import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    FINANCE,
    STEWARD,
    SUBJECT,
    VIEWER,
    GovWorld,
    rule,
)
from neurosphere_api.runtime.builders import BuildContext, BuilderSpec  # noqa: E402
from neurosphere_api.runtime.builders import governance as governance_builder  # noqa: E402
from neurosphere_api.runtime.builders.interactions import INTERACTION_STORE  # noqa: E402
from neurosphere_contracts.interactions.v1.interaction_record import (  # noqa: E402
    InteractionRecord,
)
from neurosphere_core.governance.policy import EvaluationBudget, PolicyEvaluator  # noqa: E402
from neurosphere_core.governance.policy.readers import (  # noqa: E402
    InteractionFindingReaderAdapter,
)
from neurosphere_core.interactions import (  # noqa: E402
    IndexPage,
    InMemoryInteractionIndex,
    InteractionQuery,
)

CUSTOMER = "contoso"


@pytest.fixture(autouse=True)
def _clean_govpolicy_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in sorted(os.environ):
        if name.startswith("NS_GOVPOLICY_"):
            monkeypatch.delenv(name, raising=False)
    yield


class SyntheticStore:
    """The shared interaction store stand-in: an in-memory index; content reads explode."""

    def __init__(self) -> None:
        self.index = InMemoryInteractionIndex()
        self.content_reads = 0
        self.queries: list[InteractionQuery] = []

    async def query_index(self, query: InteractionQuery) -> IndexPage:
        self.queries.append(query)
        return await self.index.query(query)

    async def read_content(self, *_args: Any, **_kwargs: Any) -> Any:
        self.content_reads += 1
        raise AssertionError("content_rule must never read interaction content")


def _stamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(captured: datetime, *, findings: dict[str, int]) -> InteractionRecord:
    interaction_id = str(uuid.uuid4())
    return InteractionRecord.model_validate(
        {
            "schema_version": "1.2.0",
            "interaction_id": interaction_id,
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "domain_id": FINANCE,
            "source_id": "src-synthetic",
            "event_id": "evt-" + interaction_id[:8],
            "correlation_id": "corr-" + interaction_id[:8],
            "capture_source": "edge_push",
            "occurred_at": _stamp(captured),
            "captured_at": _stamp(captured),
            "agent_id": SUBJECT,
            "capture_policy_id": "support-capture",
            "capture_policy_version": 1,
            "detector_set_version": "detectors-1.0",
            "redaction_state": "redacted",
            "parts": [{"part": "prompt", "char_count": 40, "truncated": False}],
            "content_ref": None,
            "findings_summary": [
                {"category": c, "count": n, "action": "replaced"} for c, n in findings.items()
            ],
            "expires_at": _stamp(captured + timedelta(days=30)),
        }
    )


@pytest.fixture
def store() -> SyntheticStore:
    return SyntheticStore()


@pytest.fixture
def bound_world(monkeypatch: pytest.MonkeyPatch, store: SyntheticStore) -> GovWorld:
    """Governance composed after an interactions stand-in that published the shared store."""
    real = governance_builder.BUILDER

    def build(ctx: BuildContext) -> None:
        ctx.publish(INTERACTION_STORE, cast(Any, store))
        real.build(ctx)

    monkeypatch.setattr(
        governance_builder, "BUILDER", BuilderSpec(real.name, real.components, build)
    )
    return GovWorld.build(monkeypatch)


def _rule_kinds(world: GovWorld) -> dict[str, dict[str, Any]]:
    response = world.call("GET", VIEWER, "/status")
    assert response.status_code == 200, response.text
    return {k["kind"]: k for k in response.json()["rule_kinds"]}


def test_bound_reader_makes_content_rule_available(bound_world: GovWorld) -> None:
    kinds = _rule_kinds(bound_world)
    assert kinds["content_rule"] == {"kind": "content_rule", "status": "available", "reason": None}
    assert "content_rule" in bound_world.plane.registry.available_kinds


async def test_published_content_rule_opens_a_violation_with_interaction_ids_only(
    bound_world: GovWorld, store: SyntheticStore
) -> None:
    world = bound_world
    now = world.now()
    records = [
        _record(now - timedelta(minutes=5), findings={"payment_card": 2}),
        _record(now - timedelta(minutes=10), findings={"payment_card": 1, "email_address": 3}),
        _record(now - timedelta(hours=3), findings={"payment_card": 9}),  # outside the window
    ]
    for rec in records:
        await store.index.create(rec)
    created = world.create(policy_id="card-leaks", rules=[rule("cards", "content_rule")])
    assert created.status_code == 201, created.text
    stored = await world.plane.policies.get(CUSTOMER, "card-leaks")
    assert stored is not None
    scope = await world.scope_of(STEWARD)
    await world.publish_directly(scope, stored)

    plane = world.plane
    evaluator = PolicyEvaluator(
        plane.policies,
        plane.violations,
        plane.statuses,
        plane.registry,
        plane.audit,
        clock=plane.clock,
    )
    await evaluator.run(
        CUSTOMER,
        scope=scope,
        trigger="interval",
        budget=EvaluationBudget(max_subjects_per_rule=100, seconds_per_rule=60),
    )

    listed = await asyncio.to_thread(
        world.call, "GET", VIEWER, f"/domains/{FINANCE}/violations?status=open"
    )
    assert listed.status_code == 200, listed.text
    items = [v["violation"] for v in listed.json()["items"]]
    assert len(items) == 1, items
    violation = items[0]
    assert violation["rule_kind"] == "content_rule"
    assert violation["subject"]["canonical_id"] == SUBJECT
    evidence = violation["evidence"]
    assert {e["evidence_kind"] for e in evidence} == {"interaction_record"}
    assert {e["ref"] for e in evidence} == {r.interaction_id.root for r in records[:2]}
    assert store.content_reads == 0
    assert store.queries, "the reader queried the metadata index"
    assert {q.customer_id for q in store.queries} == {CUSTOMER}


def test_without_a_store_content_rule_stays_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Capture and the explorer off (no stored ``interaction_capture`` setting): unbound."""
    world = GovWorld.build(monkeypatch)
    kinds = _rule_kinds(world)
    assert kinds["content_rule"]["status"] == "evaluator_unavailable"
    assert kinds["content_rule"]["reason"] == "finding_reader_unbound"
    assert "content_rule" not in world.plane.registry.available_kinds


def test_binding_returns_the_adapter_over_the_memoized_store(
    monkeypatch: pytest.MonkeyPatch, store: SyntheticStore
) -> None:
    seen: list[object] = []
    real = governance_builder.BUILDER

    def build(ctx: BuildContext) -> None:
        ctx.publish(INTERACTION_STORE, cast(Any, store))
        seen.append(governance_builder.interaction_finding_reader(ctx))
        real.build(ctx)

    monkeypatch.setattr(
        governance_builder, "BUILDER", BuilderSpec(real.name, real.components, build)
    )
    GovWorld.build(monkeypatch)
    assert len(seen) == 1
    reader = seen[0]
    assert isinstance(reader, InteractionFindingReaderAdapter)
    assert reader._source is store  # pyright: ignore[reportPrivateUsage]

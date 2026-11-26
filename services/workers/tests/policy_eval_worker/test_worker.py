"""PRP-105 item 5: the ``policy_eval`` tick on in-memory fakes.

Acceptance criterion 2 through the role: a published ``data_sensitivity_access`` PII policy and an
agent with a ``reads`` edge to a PII grounding source give exactly one violation (ids and
evidence references, no content); the next run bumps ``occurrence_count`` and ``last_seen_at``
instead of creating a second record. A store outage releases the tick with a reason code and the
next tick proceeds.
"""

from __future__ import annotations

import logging

import pytest
from neurosphere_core.governance.policy import ViolationFilters
from neurosphere_core.governance.policy.store import store_unavailable
from neurosphere_core.paging import PageRequest
from neurosphere_workers.policy_eval.worker import (
    POLICY_STORE_UNAVAILABLE,
    WORKER_SCOPE_UNAVAILABLE,
    DueFirstPolicies,
    published_after,
)

from .support import (
    CUSTOMER,
    DOMAIN_A,
    READ_EDGE,
    READER,
    SOURCE,
    Harness,
    build_harness,
    pii_policy,
)


async def _violations(harness: Harness) -> list[dict[str, object]]:
    page = await harness.violations.list(
        CUSTOMER, ViolationFilters(domain_ids=(DOMAIN_A,)), PageRequest(page_size=50)
    )
    return [s.violation.model_dump(mode="json") for s in page.items]


async def test_tick_opens_one_violation_then_bumps_it() -> None:
    harness = await build_harness()
    await harness.publish(pii_policy())

    first = await harness.parts.worker.tick()
    assert first.action == "ran"
    assert first.trigger == "interval"
    assert first.run is not None
    assert first.run.state == "completed"
    assert len(first.run.opened_violation_ids) == 1
    rows = await _violations(harness)
    assert len(rows) == 1
    violation = rows[0]
    assert violation["policy_id"] == "pii-guard"
    assert violation["policy_version"] == 1
    assert violation["rule_id"] == "pii-read"
    assert violation["status"] == "open"
    assert violation["occurrence_count"] == 1
    subject = violation["subject"]
    assert isinstance(subject, dict)
    assert subject["canonical_id"] == READER
    evidence = violation["evidence"]
    assert isinstance(evidence, list)
    refs = {e["ref"] for e in evidence}  # pyright: ignore[reportUnknownVariableType]
    assert {READ_EDGE, SOURCE} <= refs
    first_seen = violation["first_seen_at"]
    assert violation["last_seen_at"] == first_seen

    # Next interval: the same breach is observed again.
    harness.clock.advance(minutes=6)
    harness.monotonic.advance(301)
    second = await harness.parts.worker.tick()
    assert second.action == "ran"
    assert second.run is not None
    assert second.run.opened_violation_ids == ()
    rows = await _violations(harness)
    assert len(rows) == 1
    assert rows[0]["occurrence_count"] == 2
    assert rows[0]["first_seen_at"] == first_seen
    assert rows[0]["last_seen_at"] != first_seen
    assert rows[0]["violation_id"] == violation["violation_id"]

    operations = await harness.operations()
    assert operations.count("govpolicy.violation_open") == 1
    assert operations.count("govpolicy.evaluation_run") == 4  # before + after, two runs


async def test_violation_carries_ids_and_category_names_only() -> None:
    harness = await build_harness()
    await harness.publish(pii_policy())
    await harness.parts.worker.tick()
    rows = await _violations(harness)
    text = str(rows[0])
    assert "display_name" not in text
    assert "Source customers" not in text
    assert "Agent reader" not in text


async def test_between_intervals_the_tick_waits() -> None:
    harness = await build_harness()
    await harness.publish(pii_policy())
    first = await harness.parts.worker.tick()
    assert first.action == "ran"
    harness.monotonic.advance(5)
    waiting = await harness.parts.worker.tick()
    assert waiting.action == "waiting"
    assert waiting.run is None


async def test_policy_published_since_the_last_run_is_due() -> None:
    harness = await build_harness()
    first = await harness.parts.worker.tick()
    assert first.action == "ran"
    assert first.run is not None
    assert first.run.opened_violation_ids == ()

    harness.clock.advance(minutes=1)
    await harness.publish(pii_policy())
    harness.monotonic.advance(31)  # past the due check, well inside the interval
    due = await harness.parts.worker.tick()
    assert due.action == "ran"
    assert due.trigger == "due"
    assert due.due_policies == 1
    assert due.run is not None
    assert len(due.run.opened_violation_ids) == 1

    # Nothing new published: the next due check finds nothing and the tick waits.
    harness.clock.advance(minutes=1)
    harness.monotonic.advance(31)
    quiet = await harness.parts.worker.tick()
    assert quiet.action == "waiting"


async def test_due_policies_are_listed_first() -> None:
    harness = await build_harness()
    await harness.publish(pii_policy("aa-older"))
    mark = harness.clock()
    harness.clock.advance(minutes=1)
    await harness.publish(pii_policy("mm-newer"))
    harness.clock.advance(minutes=1)
    await harness.publish(pii_policy("zz-newest"))

    ordered: DueFirstPolicies = harness.parts.policies
    plain = [s.policy.policy_id.root for s in await ordered.list_published(CUSTOMER)]
    assert plain == ["aa-older", "mm-newer", "zz-newest"]
    ordered.prioritise(mark)
    published = await ordered.list_published(CUSTOMER)
    assert [s.policy.policy_id.root for s in published] == ["mm-newer", "zz-newest", "aa-older"]
    assert [published_after(s.policy, mark) for s in published] == [True, True, False]
    due_ids = await ordered.due(CUSTOMER, mark)
    assert due_ids == ("mm-newer", "zz-newest")
    ordered.prioritise(None)
    reset = [s.policy.policy_id.root for s in await ordered.list_published(CUSTOMER)]
    assert reset == plain


async def test_store_outage_releases_the_tick_and_the_next_tick_proceeds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = await build_harness()
    await harness.publish(pii_policy())
    harness.definitions.fail_with(store_unavailable())

    with caplog.at_level(logging.WARNING):
        released = await harness.parts.worker.tick()
    assert released.action == "released"
    assert released.reason_code == "govpolicy_store_unavailable"
    assert released.run is None
    events = [r for r in caplog.records if getattr(r, "event", None)]
    assert any(
        getattr(r, "event", None) == "worker.policy_eval_released"
        and getattr(r, "reason", None) == "govpolicy_store_unavailable"
        for r in events
    )
    after_outage = await _violations(harness)
    assert after_outage == []

    # Not a hot loop: the next poll right after the outage waits for the retry delay.
    harness.definitions.fail_with(None)
    harness.monotonic.advance(1)
    paused = await harness.parts.worker.tick()
    assert paused.action == "waiting"

    harness.monotonic.advance(60)
    recovered = await harness.parts.worker.tick()
    assert recovered.action == "ran"
    assert recovered.run is not None
    assert len(recovered.run.opened_violation_ids) == 1


async def test_outage_inside_the_run_is_released_with_a_reason() -> None:
    harness = await build_harness()
    await harness.publish(pii_policy())

    # The due check succeeds, then the violation store fails inside the run: the rule fails
    # (resolving nothing), the run status says why, and the tick still returns normally.
    harness.violations.backend.fail_with(store_unavailable())
    outcome = await harness.parts.worker.tick()
    assert outcome.action == "ran"
    assert outcome.run is not None
    assert outcome.run.state == "failed"
    assert outcome.reason_code == "govpolicy_store_unavailable"
    assert outcome.run.resolved_violation_ids == ()
    harness.violations.backend.fail_with(None)
    harness.monotonic.advance(301)
    again = await harness.parts.worker.tick()
    assert again.action == "ran"
    assert again.run is not None
    assert len(again.run.opened_violation_ids) == 1


async def test_scope_failure_releases_the_tick() -> None:
    harness = await build_harness()
    harness.scopes.error = RuntimeError("no scope")
    outcome = await harness.parts.worker.tick()
    assert outcome.action == "released"
    assert outcome.reason_code == WORKER_SCOPE_UNAVAILABLE


async def test_unexpected_error_in_the_due_check_uses_the_default_reason() -> None:
    harness = await build_harness()
    harness.definitions.fail_with(RuntimeError("boom"))
    outcome = await harness.parts.worker.tick()
    assert outcome.action == "released"
    assert outcome.reason_code == POLICY_STORE_UNAVAILABLE


async def test_content_rule_is_unavailable_until_a_finding_reader_is_bound() -> None:
    harness = await build_harness()
    registry = harness.parts.registry
    assert "data_sensitivity_access" in registry
    assert registry.unavailable_reason("content_rule") == "finding_reader_unbound"

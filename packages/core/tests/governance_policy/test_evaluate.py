"""``PolicyEvaluator.run`` on in-memory fakes (PRP-105 item 3, acceptance criteria 2, 3 and 10)."""

from __future__ import annotations

from typing import get_args

import pytest
from neurosphere_contracts.notifications.v1.notification_subscription import (
    NotificationEventClass,
)
from neurosphere_core.audit import find_sensitive_content
from neurosphere_core.errors import DependencyTransientError, ForbiddenError
from neurosphere_core.governance.policy import (
    EvaluationBudget,
    ViolationFilters,
)
from neurosphere_core.governance.policy.events import (
    EXCEPTION_DECIDED,
    VIOLATION_OPENED,
    VIOLATION_RESOLVED,
)
from neurosphere_core.governance.policy.rules import FindingEvidence, RuleFinding, RuleOutcome
from neurosphere_core.governance.policy.store import store_unavailable
from neurosphere_core.paging import PageRequest

from .engine_helpers import (
    CONTROL,
    CUSTOMER,
    CUSTOMERS_SOURCE,
    DOMAIN_A,
    DOMAIN_B,
    DOMAIN_HIDDEN,
    INTENT,
    READ_EDGE,
    READER,
    WORKER_SCOPE,
    CannedEvaluator,
    Engine,
    build_engine,
    make_scope,
    policy_draft,
    rule,
)
from .rules.rules_helpers import (
    SCOPE,
    agent,
    agent_version,
    grounding_source,
    reads,
    seed,
    source_id,
    version_id,
)

#: Every key a stored violation document may carry: ids, counts, category-free metadata.
_VIOLATION_KEYS = {
    "schema_version",
    "violation_id",
    "cloud",
    "customer_id",
    "domain_id",
    "policy_id",
    "policy_version",
    "rule_id",
    "rule_kind",
    "severity",
    "subject",
    "status",
    "dedup_key",
    "first_seen_at",
    "last_seen_at",
    "occurrence_count",
    "evidence",
    "exception_id",
    "resolution",
    "correlation_id",
    "evaluator_version",
    "id",
    "doc_kind",
    "sort_key",
    "subject_id",
    "last_run_id",
    "_etag",
}


async def _violations(engine: Engine, *domains: str) -> list:  # type: ignore[type-arg]
    page = await engine.violations.list(
        CUSTOMER, ViolationFilters(domain_ids=domains or (DOMAIN_A,)), PageRequest()
    )
    return [s.violation for s in page.items]


async def _approve_reader(engine: Engine) -> None:
    """The condition disappears: ``reader`` gets an approved current version."""
    await seed(engine.catalog, agent_version("reader-v1", "reader", state="approved"))
    current = await engine.catalog.get_entity(SCOPE, READER)
    assert current is not None
    body = current.model_dump(mode="json")
    updated = agent(
        "reader",
        current_version_id=version_id("reader-v1"),
        etag=body["etag"],
        version=body["version"],
    )
    await engine.catalog.update_entity(SCOPE, updated, body["etag"])


def _finding() -> RuleFinding:
    return RuleFinding(
        subject_id=READER,
        subject_type="agent",
        domain_id=DOMAIN_A,
        evidence_class="sensitive_data_access",
        evidence=(
            FindingEvidence(kind="relation", ref=READ_EDGE),
            FindingEvidence(kind="catalog_entity", ref=CUSTOMERS_SOURCE),
        ),
        categories=("pii",),
    )


# --- criterion 2 ------------------------------------------------------------------------------


async def test_a_published_pii_policy_opens_one_violation_with_ids_and_no_content() -> None:
    engine = await build_engine()
    published = await engine.publish(policy_draft())

    run = await engine.tick()

    assert run.state == "completed"
    assert run.status.rules[0].outcome == "complete"
    assert run.status.violations_opened == 1
    (violation,) = await _violations(engine)
    assert violation.policy_id.root == "pii-guard"
    assert violation.policy_version == published.stored.policy.policy_version == 1
    assert violation.rule_id.root == "pii-read"
    assert violation.subject.canonical_id == READER
    assert {(e.evidence_kind, e.ref) for e in violation.evidence} == {
        ("relation", READ_EDGE),
        ("catalog_entity", CUSTOMERS_SOURCE),
    }
    assert violation.first_seen_at.root == violation.last_seen_at.root
    assert violation.occurrence_count == 1
    assert violation.status == "open"
    assert run.opened_violation_ids == (violation.violation_id.root,)
    # no content: only the contract's id/count fields are stored, and nothing sensitive
    (doc,) = [d for d in engine.violations.backend._docs.values()]
    assert set(doc) <= _VIOLATION_KEYS
    # (GUID-shaped ids are fine here: the guard's object-id rule is for audit records)
    assert [f for f in find_sensitive_content(doc) if f[1] != "raw_object_id"] == []
    operations = await engine.operations()
    assert "govpolicy.evaluation_run" in operations
    assert "govpolicy.violation_open" in operations
    assert [e.event_class for e in engine.sink.opened_events] == [VIOLATION_OPENED]
    assert engine.sink.opened_events[0].violation_id == violation.violation_id.root


async def test_a_second_tick_bumps_last_seen_and_count_without_a_second_record() -> None:
    engine = await build_engine()
    await engine.publish(policy_draft())
    first = await engine.tick()
    second = await engine.tick()

    assert second.opened_violation_ids == ()
    (violation,) = await _violations(engine)
    assert violation.violation_id.root == first.opened_violation_ids[0]
    assert violation.occurrence_count == 2
    assert violation.last_seen_at.root > violation.first_seen_at.root
    assert len(engine.violations.backend._docs) == 1
    assert len(engine.sink.opened_events) == 1


async def test_run_status_is_stored_under_the_control_domain() -> None:
    engine = await build_engine()
    await engine.publish(policy_draft())
    run = await engine.tick()

    stored = await engine.statuses.get(CUSTOMER, CONTROL, run.run_id)
    assert stored is not None
    assert stored.status == run.status
    assert run.status.domains_evaluated == (DOMAIN_A,)
    assert run.status.trigger == "interval"
    latest = await engine.statuses.latest(CUSTOMER, CONTROL)
    assert latest is not None
    assert latest.status.run_id == run.run_id


# --- criterion 3 ------------------------------------------------------------------------------


async def test_a_complete_run_resolves_the_violation_once_the_condition_is_gone() -> None:
    engine = await build_engine()
    await engine.publish(policy_draft())
    first = await engine.tick()
    await _approve_reader(engine)

    run = await engine.tick()

    assert run.state == "completed"
    assert run.resolved_violation_ids == first.opened_violation_ids
    (violation,) = await _violations(engine)
    assert violation.status == "resolved"
    assert violation.resolution is not None
    assert violation.resolution.resolved_at.root == run.status.finished_at
    assert run.status.rules[0].violations_resolved == 1
    operations = await engine.operations()
    assert "govpolicy.violation_resolve" in operations
    assert [e.event_class for e in engine.sink.resolved_events] == [VIOLATION_RESOLVED]


async def test_a_truncated_rule_resolves_nothing_and_the_run_says_truncated() -> None:
    engine = await build_engine(real_pii_evaluator=False)
    canned = CannedEvaluator(
        "data_sensitivity_access",
        RuleOutcome(kind="data_sensitivity_access", findings=(_finding(),)),
    )
    engine.registry.register(canned)
    await engine.publish(policy_draft())
    await engine.tick()
    canned.outcome = RuleOutcome(
        kind="data_sensitivity_access", truncated=True, reason="subject_budget"
    )

    run = await engine.tick()

    assert run.state == "truncated"
    assert run.status.reason_code == "truncated"
    (status,) = run.status.rules
    assert status.outcome == "truncated"
    assert status.reason_code == "subject_budget"
    assert status.violations_resolved == 0
    assert run.resolved_violation_ids == ()
    (violation,) = await _violations(engine)
    assert violation.status == "open"
    # the next COMPLETE run of the rule does resolve it
    canned.outcome = RuleOutcome(kind="data_sensitivity_access")
    done = await engine.tick()
    assert done.state == "completed"
    assert len(done.resolved_violation_ids) == 1


async def test_the_real_evaluator_hitting_its_subject_budget_resolves_nothing() -> None:
    engine = await build_engine()
    await engine.publish(policy_draft())
    await engine.tick()
    await _approve_reader(engine)
    # a second PII source: the access engine, bounded to the one subject left, truncates
    await seed(
        engine.catalog,
        grounding_source("contacts", sensitivity_categories=["pii"]),
        reads("r-reader-contacts", READER, source_id("contacts")),
    )

    run = await engine.tick(budget=EvaluationBudget(max_subjects_per_rule=1, seconds_per_rule=60))

    assert run.state == "truncated"
    assert run.resolved_violation_ids == ()
    (violation,) = await _violations(engine)
    assert violation.status == "open"


async def test_every_rule_gets_a_fresh_budget() -> None:
    engine = await build_engine(real_pii_evaluator=False)
    canned = CannedEvaluator("data_sensitivity_access")
    engine.registry.register(canned)
    await engine.publish(policy_draft(rules=[rule("one"), rule("two")]))

    await engine.tick(budget=EvaluationBudget(max_subjects_per_rule=7, seconds_per_rule=30))

    first, second = canned.calls
    assert first.budget is not second.budget
    assert first.budget.max_subjects == second.budget.max_subjects == 7
    assert first.domain_ids == second.domain_ids == (DOMAIN_A,)


async def test_a_failing_violation_store_fails_the_rule_and_resolves_nothing() -> None:
    engine = await build_engine()
    await engine.publish(policy_draft())
    engine.violations.backend.fail_with(store_unavailable())

    run = await engine.tick()

    assert run.state == "failed"
    assert run.status.rules[0].outcome == "failed"
    assert run.status.reason_code == "govpolicy_store_unavailable"


async def test_a_policy_store_outage_ends_the_run_and_re_raises() -> None:
    engine = await build_engine()
    await engine.publish(policy_draft())
    engine.definitions.fail_with(store_unavailable())

    with pytest.raises(DependencyTransientError):
        await engine.tick()


# --- criterion 10 and scope -------------------------------------------------------------------


async def test_a_kind_without_an_evaluator_is_reported_evaluator_unavailable() -> None:
    engine = await build_engine()
    budget_rule = rule(
        "monthly-cap",
        "budget",
        {
            "budget_record_id": "budget-support-monthly",
            "threshold_percent": 100,
            "on_breach": "alert",
        },
    )
    created = await engine.create(policy_draft(rules=[budget_rule]))
    # Published before the evaluator went away (the lifecycle would refuse it today).
    await engine.policies.mark_published(
        CUSTOMER,
        "pii-guard",
        1,
        if_match=created.etag,
        published_at=engine.clock(),
        intent_id=INTENT,
        audit_id=INTENT,
    )

    run = await engine.tick()

    (status,) = run.status.rules
    assert status.outcome == "evaluator_unavailable"
    assert status.reason_code == "no_evaluator"
    assert run.state == "completed"


async def test_a_policy_in_a_domain_outside_the_scope_is_skipped_and_listed() -> None:
    engine = await build_engine()
    wide = make_scope(
        "a",
        [("domain_steward", [DOMAIN_A, DOMAIN_HIDDEN])],
        [DOMAIN_A, DOMAIN_HIDDEN],
    )
    await engine.publish(policy_draft("hidden-guard", domain=DOMAIN_HIDDEN), scope=wide)

    run = await engine.tick()

    assert run.status.domains_skipped == (DOMAIN_HIDDEN,)
    (status,) = run.status.rules
    assert status.outcome == "skipped"
    assert status.reason_code == "domain_out_of_scope"
    assert run.opened_violation_ids == ()


async def test_a_customer_wide_policy_covers_only_domains_the_scope_can_see() -> None:
    engine = await build_engine()
    await engine.publish(policy_draft("org-pii", domain=CONTROL))

    narrow = make_scope("a", [("domain_steward", [DOMAIN_B, CONTROL])], [DOMAIN_B, CONTROL])
    blind = await engine.tick(scope=narrow)
    assert blind.opened_violation_ids == ()
    assert blind.status.domains_evaluated == (DOMAIN_B,)

    seen = await engine.tick()
    assert len(seen.opened_violation_ids) == 1
    assert set(seen.status.domains_evaluated) == {DOMAIN_A, DOMAIN_B}
    (violation,) = await _violations(engine)
    assert violation.domain_id.root == DOMAIN_A
    assert violation.policy_id.root == "org-pii"


async def test_a_policy_in_mode_off_is_not_evaluated() -> None:
    engine = await build_engine()
    await engine.publish(policy_draft(mode="off"))

    run = await engine.tick()

    assert run.opened_violation_ids == ()
    assert run.status.rules[0].outcome == "skipped"
    assert run.status.rules[0].reason_code == "policy_mode_off"


def test_event_classes_are_prp99_notification_event_classes() -> None:
    allowed = set(get_args(NotificationEventClass.model_fields["root"].annotation))
    assert {VIOLATION_OPENED, VIOLATION_RESOLVED, EXCEPTION_DECIDED} <= allowed


async def test_another_customers_scope_is_refused() -> None:
    engine = await build_engine()
    with pytest.raises(ForbiddenError):
        await engine.evaluator.run(
            "globex", scope=WORKER_SCOPE, trigger="manual", budget=EvaluationBudget()
        )

"""Review-item completion: an approved maker-checker intent that finishes marks its item.

succeeded -> ``executed``; failed / rolled_back -> ``failed``. A hook failure never changes the
intent outcome, is logged and audited, and is retried by the next pass over the terminal intent.
Also: the worker and the API share ONE action-kind table (core's).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from neurosphere_core.actions import ActionCaller
from neurosphere_core.actions.targets import ACTION_CONNECTORS
from neurosphere_core.errors import DependencyTransientError, StaleVersionError
from neurosphere_workers.actions import (
    DEFAULT_ACTION_CONNECTORS,
    ActionExecutor,
    ReviewItemCompletion,
)
from neurosphere_workers.actions import targets as worker_targets

from .executor_support import (
    ACTION_KIND,
    CUSTOMER,
    DOMAIN,
    FAKE_CONNECTOR,
    Harness,
    draft_request,
    maker,
)

APPROVER_ID = "commercial:contoso:entra:person:p-checker00000001"
ITEM_ID = "00000000-0000-4000-8000-0000000000aa"


class FakeItem:
    def __init__(self, state_name: str) -> None:
        self.state_name = state_name


class FakeHitl:
    """The ``ReviewItemOutcomes`` surface with one maker_checker item in ``approved``."""

    def __init__(self) -> None:
        self.state = "approved"
        self.marked: list[tuple[str, str]] = []
        self.error: Exception | None = None

    async def mark_executed(self, item_id: str, now: datetime, *, correlation_id: str) -> object:
        return self._mark(item_id, "executed")

    async def mark_failed(self, item_id: str, now: datetime, *, correlation_id: str) -> object:
        return self._mark(item_id, "failed")

    def _mark(self, item_id: str, target: str) -> FakeItem:
        if self.error is not None:
            raise self.error
        if self.state != "approved":
            raise StaleVersionError("not approved", reason="invalid_review_transition")
        self.state = target
        self.marked.append((item_id, target))
        return FakeItem(target)

    async def get(self, item_id: str) -> FakeItem | None:
        return FakeItem(self.state)


def approver() -> ActionCaller:
    return ActionCaller.model_validate(
        {
            "principal_id": APPROVER_ID,
            "actor": {
                "principal_pseudonym": "p-checker1",
                "principal_kind": "user",
                "on_behalf_of": None,
            },
            "scope_hash": "sha256:" + "b" * 64,
            "correlation_id": "corr-exec-0002",
            "channel": "rest",
        }
    )


async def approved_with_review_item(h: Harness, *, operations: list[dict[str, str]] | None = None):
    """Draft -> ... -> awaiting_approval (linked to ITEM_ID) -> approved -> executing."""
    from neurosphere_contracts.actions.v1.action_intent import PrerequisiteResult

    h.rechecker.grant(APPROVER_ID, CUSTOMER, DOMAIN, "action.approve")
    who = maker()
    request = draft_request() if operations is None else draft_request(operations=operations)
    drafted = await h.service.draft(who, request, customer_id=CUSTOMER, domain_id=DOMAIN)
    check = PrerequisiteResult.model_validate(
        {
            "check_id": "actor_permission",
            "status": "passed",
            "detail": None,
            "evaluated_at": "2026-10-20T12:00:00Z",
            "evidence_ids": [],
        }
    )
    validated = await h.service.record_validation(drafted.stored.key, who, [check])
    presented = await h.service.present_confirmation(validated.key, who)
    bound = presented.intent.confirmation_hash
    assert bound is not None
    waiting = await h.service.confirm(
        presented.key,
        who,
        confirmation_hash=bound.root,
        current_target_version=presented.intent.target_version,
        requires_approval=True,
        advisory=False,
    )
    assert waiting.state == "awaiting_approval"
    await h.service.link_review_item(waiting.key, ITEM_ID)
    done = await h.service.apply_approval(
        waiting.key,
        approver(),
        approved=True,
        approved_confirmation_hash=bound.root,
        current_target_version=presented.intent.target_version,
    )
    assert done.state == "executing"
    return done.key


def with_hook(h: Harness, hitl: FakeHitl) -> ActionExecutor:
    return h.executor(on_finished=ReviewItemCompletion(hitl, auditor=h.auditor, clock=h.clock))


async def test_success_marks_the_review_item_executed() -> None:
    h, hitl = Harness(), FakeHitl()
    key = await approved_with_review_item(h)
    report = await with_hook(h, hitl).execute(key)
    assert report.outcome == "succeeded"
    assert hitl.marked == [(ITEM_ID, "executed")]


async def test_verify_failure_rollback_marks_the_review_item_failed() -> None:
    h, hitl = Harness(), FakeHitl()
    h.connector.apply_noop = True  # apply reports success but changes nothing -> verify fails
    key = await approved_with_review_item(h)
    report = await with_hook(h, hitl).execute(key)
    assert report.outcome == "rolled_back"
    assert hitl.marked == [(ITEM_ID, "failed")]


async def test_revoked_permission_marks_the_review_item_failed() -> None:
    h, hitl = Harness(), FakeHitl()
    key = await approved_with_review_item(h)
    h.rechecker.revoke(maker().principal_id, CUSTOMER, DOMAIN, "action.execute")
    report = await with_hook(h, hitl).execute(key)
    assert (report.outcome, report.reason) == ("failed", "permission_revoked")
    assert hitl.marked == [(ITEM_ID, "failed")]


async def test_intent_without_a_review_item_does_not_call_the_hook_target() -> None:
    h, hitl = Harness(), FakeHitl()
    key = await h.executing()  # no approval required, no review item
    assert (await with_hook(h, hitl).execute(key)).outcome == "succeeded"
    assert hitl.marked == []


async def test_deferred_pass_does_not_complete_the_item() -> None:
    h, hitl = Harness(), FakeHitl()
    key = await approved_with_review_item(h)
    await h.control.set(
        CUSTOMER, disabled=True, reason="incident_response", changed_by="p-admin01", now=h.clock()
    )
    report = await with_hook(h, hitl).execute(key)
    assert report.outcome == "deferred"
    assert hitl.marked == []
    assert hitl.state == "approved"


async def test_hook_failure_keeps_the_outcome_audits_and_retries_on_the_next_pass() -> None:
    h, hitl = Harness(), FakeHitl()
    key = await approved_with_review_item(h)
    hitl.error = DependencyTransientError("hitl store down", reason="hitl_store_unavailable")
    executor = with_hook(h, hitl)
    report = await executor.execute(key)
    # The change landed and stays succeeded; only the review item is behind.
    assert (report.outcome, report.state) == ("succeeded", "succeeded")
    assert (await h.current(key)).state == "succeeded"
    assert hitl.marked == [] and hitl.state == "approved"
    failures = [e for e in h.auditor.events if e.operation == "hitl.review.completion_hook"]
    assert [(e.kind, e.result, e.reason) for e in failures] == [
        ("after", "failed", "hitl_store_unavailable")
    ]
    # Retry-safe: the store recovers, a repeat pass over the finished intent completes the item
    # without touching the connector again.
    hitl.error = None
    calls = list(h.connector.calls)
    again = await executor.execute(key)
    assert again.outcome == "skipped"
    assert hitl.marked == [(ITEM_ID, "executed")]
    assert h.connector.calls == calls
    # And a further pass is a harmless no-op.
    await executor.execute(key)
    assert hitl.marked == [(ITEM_ID, "executed")]


async def test_unexpected_hook_error_never_escapes_the_executor() -> None:
    h, hitl = Harness(), FakeHitl()
    key = await approved_with_review_item(h)
    hitl.error = RuntimeError("boom")
    report = await with_hook(h, hitl).execute(key)
    assert report.outcome == "succeeded"
    assert (await h.current(key)).state == "succeeded"


async def test_executor_without_a_hook_is_unchanged() -> None:
    h = Harness()
    key = await approved_with_review_item(h)
    assert (await h.executor().execute(key)).outcome == "succeeded"


def test_worker_uses_the_one_core_action_kind_table() -> None:
    assert DEFAULT_ACTION_CONNECTORS is ACTION_CONNECTORS
    assert worker_targets.DEFAULT_ACTION_CONNECTORS is ACTION_CONNECTORS
    assert dict(DEFAULT_ACTION_CONNECTORS) == {
        "model_deployment_swap": "foundry-model-swap",
        "budget_cap_change": "apim-gateway",
        "grant_publish": "apim-gateway",
        "grant_unpublish": "apim-gateway",
        "mcp_server_publish": "apim-gateway",
        "mcp_server_unpublish": "apim-gateway",
        "gateway_mode_change": "apim-gateway",
    }
    assert ACTION_KIND in DEFAULT_ACTION_CONNECTORS
    assert FAKE_CONNECTOR not in DEFAULT_ACTION_CONNECTORS.values()


@pytest.mark.parametrize("name", ["DEFAULT_ACTION_CONNECTORS"])
def test_the_alias_is_read_only(name: str) -> None:
    table = getattr(worker_targets, name)
    with pytest.raises(TypeError):
        table["x"] = "y"

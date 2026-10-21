"""Failed verify or canary -> rollback; rollback failure -> failed; connector-restored applies."""

from __future__ import annotations

from neurosphere_connector.write import ApplyResult, VerifyResult, WriteRequest
from neurosphere_core.actions import CanaryOutcome
from neurosphere_core.errors import CapabilityUnavailableError, DependencyTransientError
from neurosphere_workers.actions import DEFAULT_ACTION_CONNECTORS

from .executor_support import (
    FOUNDRY_SWAP_OPS,
    CountingConnector,
    FakeArm,
    Harness,
    draft_request,
    foundry_connector,
)

PRIOR_MODEL = {"format": "OpenAI", "name": "gpt-4o", "version": "2024-08-06"}


class FailingCanary:
    def __init__(self) -> None:
        self.seen: list[tuple[str, bool]] = []

    async def probe(
        self, request: WriteRequest, applied: ApplyResult, observed: VerifyResult
    ) -> CanaryOutcome:
        self.seen.append((applied.version_before, observed.matched))
        return "failed"


class PassingCanary:
    async def probe(
        self, request: WriteRequest, applied: ApplyResult, observed: VerifyResult
    ) -> CanaryOutcome:
        return "passed"


class BrokenCanary:
    async def probe(
        self, request: WriteRequest, applied: ApplyResult, observed: VerifyResult
    ) -> CanaryOutcome:
        raise RuntimeError("probe crashed")


async def test_failed_verify_triggers_rollback_with_evidence() -> None:
    h = Harness()
    h.connector.apply_noop = True  # a "pretend" change: apply says ok, the target never moved
    key = await h.executing()
    report = await h.executor().execute(key)
    assert (report.outcome, report.reason, report.state) == (
        "rolled_back",
        "verification_failed",
        "rolled_back",
    )
    assert h.connector.calls == ["dry_run", "apply", "verify", "verify", "rollback"]
    record = (await h.current(key)).execution
    assert record is not None
    assert record.verify_matched is False
    assert record.rolled_back is True
    assert record.rollback_result is not None
    assert record.rollback_result["status"] == "rolled_back"
    assert record.details["rollback_reason"] == "verification_failed"
    assert record.details["mismatched_paths"] == [
        "/properties/model/name",
        "/properties/model/version",
    ]
    assert h.final_transition() == ("executing", "rolled_back", "verification_failed")


async def test_drift_between_canary_and_verify_rolls_back() -> None:
    h = Harness()
    h.connector.drift_after_verify = 1  # someone changes the target after the canary read
    key = await h.executing()
    report = await h.executor(canary=PassingCanary()).execute(key)
    assert (report.outcome, report.reason) == ("rolled_back", "verification_failed")
    assert h.connector.state["properties"]["model"] == PRIOR_MODEL
    record = (await h.current(key)).execution
    assert record is not None and record.canary == "passed"


async def test_failed_canary_triggers_rollback_before_final_verify() -> None:
    h = Harness()
    canary = FailingCanary()
    key = await h.executing()
    report = await h.executor(canary=canary).execute(key)
    assert (report.outcome, report.reason) == ("rolled_back", "canary_failed")
    assert canary.seen == [("etag-1", True)]
    assert h.connector.calls == ["dry_run", "apply", "verify", "rollback"]
    assert h.connector.state["properties"]["model"] == PRIOR_MODEL
    record = (await h.current(key)).execution
    assert record is not None
    assert record.canary == "failed"
    assert record.verify_matched is None
    assert record.rolled_back is True


async def test_canary_that_raises_counts_as_failed() -> None:
    h = Harness()
    key = await h.executing()
    report = await h.executor(canary=BrokenCanary()).execute(key)
    assert (report.outcome, report.reason) == ("rolled_back", "canary_failed")


async def test_rollback_failure_ends_failed_rollback_failed_flagged() -> None:
    h = Harness()
    h.connector.apply_noop = True
    h.connector.rollback_error = DependencyTransientError(reason="arm_unreachable")
    key = await h.executing()
    report = await h.executor().execute(key)
    assert (report.outcome, report.reason, report.state) == (
        "failed",
        "rollback_failed",
        "failed",
    )
    record = (await h.current(key)).execution
    assert record is not None
    assert record.rolled_back is False
    assert record.rollback_result == {"error": "arm_unreachable"}
    assert record.details["operator_attention"] is True
    assert record.last_error == "rollback_failed"


async def test_connector_restored_apply_failure_is_failed_without_rollback() -> None:
    h = Harness()
    h.connector.apply_error = CapabilityUnavailableError("apply_failed_restored", "restored")
    key = await h.executing()
    report = await h.executor().execute(key)
    assert (report.outcome, report.reason) == ("failed", "apply_failed_restored")
    assert h.connector.calls == ["dry_run", "apply"]  # no verify, no rollback, no re-apply
    record = (await h.current(key)).execution
    assert record is not None
    assert record.details["connector_restored"] is True
    assert "operator_attention" not in record.details


async def test_connector_restore_failure_is_flagged_for_the_operator() -> None:
    h = Harness()
    h.connector.apply_error = CapabilityUnavailableError("apply_failed_restore_failed", "x")
    key = await h.executing()
    report = await h.executor().execute(key)
    assert (report.outcome, report.reason) == ("failed", "apply_failed_restore_failed")
    assert h.connector.calls == ["dry_run", "apply"]
    record = (await h.current(key)).execution
    assert record is not None
    assert record.details["operator_attention"] is True
    assert record.details["connector_restored"] is False


async def test_apply_error_with_unknown_outcome_is_discovered_not_retried() -> None:
    h = Harness()
    h.connector.apply_error = DependencyTransientError(reason="arm_unreachable")
    key = await h.executing()
    report = await h.executor().execute(key)
    # The target did not change: the apply error is the failure reason; nothing re-applied.
    assert (report.outcome, report.reason) == ("failed", "arm_unreachable")
    assert h.connector.calls == ["dry_run", "apply", "verify"]


async def test_foundry_failed_put_is_restored_by_the_connector_and_not_rolled_back() -> None:
    arm = FakeArm()
    arm.fail_put_number = 1  # the first PUT answers 500
    h = Harness(connector=CountingConnector(advisory=True))
    h.registry.register(foundry_connector(arm))
    key = await h.executing(draft_request(operations=FOUNDRY_SWAP_OPS))
    report = await h.executor(table=dict(DEFAULT_ACTION_CONNECTORS)).execute(key)
    assert (report.outcome, report.reason) == ("failed", "apply_failed_restored")
    assert len(arm.puts) == 2  # the failed swap PUT + the connector's own restore PUT
    assert arm.model() == PRIOR_MODEL


async def test_foundry_verify_mismatch_rolls_back_through_the_connector() -> None:
    arm = FakeArm()
    h = Harness(connector=CountingConnector(advisory=True))
    h.registry.register(foundry_connector(arm))
    key = await h.executing(draft_request(operations=FOUNDRY_SWAP_OPS))
    canary = FailingCanary()
    report = await h.executor(canary=canary, table=dict(DEFAULT_ACTION_CONNECTORS)).execute(key)
    assert (report.outcome, report.reason) == ("rolled_back", "canary_failed")
    assert len(arm.puts) == 2  # swap + rollback
    assert arm.model() == PRIOR_MODEL

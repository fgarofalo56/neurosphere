"""Audit before and after each apply; fail closed on audit outage; no principal ids anywhere."""

from __future__ import annotations

import logging

import pytest
from neurosphere_connector.write import ApplyResult, DryRunResult, WriteRequest
from neurosphere_core.errors import DependencyTransientError

from .executor_support import MAKER_ID, CountingConnector, Harness


class AuditWitness(CountingConnector):
    """Records which executor audit records existed at the moment ``apply`` was called."""

    def __init__(self) -> None:
        super().__init__()
        self.harness: Harness | None = None
        self.audit_at_apply: list[tuple[str, str | None, str | None]] = []
        self.break_audit_after_dry_run = False

    async def dry_run(self, request: WriteRequest) -> DryRunResult:
        result = await super().dry_run(request)
        if self.harness is not None and self.break_audit_after_dry_run:
            self.harness.auditor.fail_with(DependencyTransientError(reason="audit_write_failed"))
        return result

    async def apply(self, request: WriteRequest) -> ApplyResult:
        assert self.harness is not None
        self.audit_at_apply = self.harness.exec_events()
        return await super().apply(request)


def _witnessed() -> tuple[Harness, AuditWitness]:
    connector = AuditWitness()
    h = Harness(connector=connector)
    connector.harness = h
    return h, connector


async def test_before_record_is_durable_before_apply_and_after_records_follow() -> None:
    h, connector = _witnessed()
    key = await h.executing()
    assert (await h.executor().execute(key)).outcome == "succeeded"
    assert connector.audit_at_apply == [("before", "applying", None)]
    assert h.exec_events() == [
        ("before", "applying", None),
        ("after", "applied", None),
        ("after", "verifying", None),
    ]
    phase_events = [e for e in h.auditor.events if e.phase is not None]
    assert all(e.state_digest and e.state_digest.startswith("sha256:") for e in phase_events)
    verified = phase_events[-1]
    assert (verified.result, verified.verified) == ("succeeded", True)
    assert all(e.channel == "worker" for e in phase_events)


async def test_rollback_is_audited_before_and_after() -> None:
    h, connector = _witnessed()
    connector.apply_noop = True
    key = await h.executing()
    assert (await h.executor().execute(key)).outcome == "rolled_back"
    assert h.exec_events() == [
        ("before", "applying", None),
        ("after", "applied", None),
        ("after", "verifying", "verification_failed"),
        ("before", "rolling_back", "verification_failed"),
        ("after", "rolling_back", "verification_failed"),
    ]
    assert h.auditor.events[-1].to_state == "rolled_back"


async def test_failed_apply_is_audited_after() -> None:
    h, connector = _witnessed()
    connector.apply_error = DependencyTransientError(reason="arm_unreachable")
    key = await h.executing()
    await h.executor().execute(key)
    after = [e for e in h.auditor.events if e.kind == "after" and e.phase == "applying"]
    assert [(e.result, e.reason) for e in after] == [("failed", "arm_unreachable")]


async def test_audit_outage_before_apply_means_no_apply() -> None:
    h, connector = _witnessed()
    connector.break_audit_after_dry_run = True
    key = await h.executing()
    report = await h.executor().execute(key)
    assert (report.outcome, report.reason) == ("deferred", "audit_write_failed")
    assert connector.count("apply") == 0
    stored = await h.current(key)
    assert stored.state == "executing"
    assert stored.execution is not None and stored.execution.phase == "dry_run_done"
    assert stored.execution.lease_owner is None  # released, another worker may take it
    h.auditor.fail_with(None)
    connector.break_audit_after_dry_run = False
    assert (await h.executor().execute(key)).outcome == "succeeded"
    assert connector.count("apply") == 1


async def test_no_principal_id_or_token_in_audit_records_or_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="neurosphere.workers.actions")
    h, connector = _witnessed()
    connector.apply_noop = True
    key = await h.executing()
    await h.executor().execute(key)
    for event in h.auditor.events:
        assert MAKER_ID not in event.model_dump_json()
    for record in caplog.records:
        assert MAKER_ID not in record.getMessage()
        assert MAKER_ID not in str(record.__dict__)
    stored = await h.current(key)
    assert stored.execution is not None
    assert MAKER_ID not in stored.execution.model_dump_json()

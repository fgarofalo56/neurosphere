"""The composed app audits denied attempts (PRP-06 audit close-out D1).

A refused ``require`` check in the COMPOSED app appends a ``denied`` record to the composed
``AuditRepository``; the default recorder is never ``None``; a missing audit store fails a
mutating denial closed (503) and still answers 403 on a safe one. In-memory stores only.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    FINANCE,
    HR,
    FakeClock,
    RecordingDenials,
)
from neurosphere_api.authz import AuthzState, DeniedAttempt
from neurosphere_api.runtime.builders import AUDIT_REPOSITORY, BuildContext, BuilderSpec
from neurosphere_api.runtime.builders.authz import DENIAL_CHAIN_NAME, AuditDenialRecorder
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.errors import DependencyTransientError

from .runtime_helpers import (
    ALICE,
    Composed,
    builders_with_stubs,
    compose,
    composed_principal_id,
    configure_auth_env,
    configured_overrides,
)

AUDIT_RECORDS = "/api/v1/audit/chains/{chain}/records"
EMERGENCY = "/api/v1/actions/emergency-disable"
DENIAL_CHAIN = f"{CUSTOMER}.{DENIAL_CHAIN_NAME}"


def _builders_with_audit(audit: AuditRepository) -> tuple[BuilderSpec, ...]:
    """Default order with the data stub replaced by one that publishes ``audit``."""
    out: list[BuilderSpec] = []
    for spec in builders_with_stubs():
        if spec.name != "stub-data":
            out.append(spec)
            continue
        components = spec.components

        def build(ctx: BuildContext, components: tuple[str, ...] = components) -> None:
            ctx.app.state.audit_repository = audit
            ctx.publish(AUDIT_REPOSITORY, audit)
            for name in components:
                ctx.ok(name)

        out.append(BuilderSpec("audit-data", components, build))
    return tuple(out)


def _compose(
    monkeypatch: pytest.MonkeyPatch, audit: AuditRepository | None, **extra: Any
) -> Composed:
    configure_auth_env(monkeypatch)
    clock = FakeClock()
    builders = builders_with_stubs() if audit is None else _builders_with_audit(audit)
    return compose(configured_overrides(clock, **extra), builders=builders, clock=clock)


def _records(audit: AuditRepository, chain: str) -> list[AuditRecord]:
    return asyncio.run(audit.read_range(chain, start=0, limit=50))


def test_default_composed_recorder_is_audit_backed(monkeypatch: pytest.MonkeyPatch) -> None:
    composed = _compose(monkeypatch, AuditRepository(InMemoryAuditStore()))
    state = composed.app.state.authz
    assert isinstance(state, AuthzState)
    assert state.denial_recorder is not None
    assert isinstance(state.denial_recorder, AuditDenialRecorder)


def test_safe_403_writes_a_denied_record_on_the_target_domain_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = AuditRepository(InMemoryAuditStore())
    composed = _compose(monkeypatch, audit)
    with composed.client() as client:
        # ALICE is a finance Analyst: no audit.read, so the finance chain is refused.
        response = client.get(
            AUDIT_RECORDS.format(chain="contoso.finance"), headers=composed.auth()
        )
    assert response.status_code == 403, response.text
    reason = response.json()["reason"]

    records = _records(audit, "contoso.finance")
    assert len(records) == 1
    record = records[0]
    assert record.kind == "denied"
    assert record.outcome is None
    assert record.denial is not None
    assert (record.denial.code, record.denial.reason) == ("forbidden", reason)
    assert record.operation == "audit.read"
    assert record.channel == "rest"
    # The actor is the pseudonym part of the composed principal id, never the object id.
    assert composed_principal_id(ALICE).endswith(":" + record.actor.principal_pseudonym)
    assert record.subject is not None
    assert record.subject.target.canonical_id == FINANCE
    assert record.subject.target.entity_type == "domain"
    assert record.subject.state_digest is None
    assert record.correlation_id.startswith("corr-")


def test_mutating_403_writes_a_denied_record_on_the_denial_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = AuditRepository(InMemoryAuditStore())
    composed = _compose(monkeypatch, audit)
    with composed.client() as client:
        response = client.put(EMERGENCY, json={}, headers=composed.auth())
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "permission_missing"

    records = _records(audit, DENIAL_CHAIN)
    assert [(r.kind, r.operation) for r in records] == [("denied", "config.manage")]
    assert records[0].denial is not None
    assert records[0].denial.reason == "permission_missing"
    assert records[0].subject is None  # no target resolved
    verification = asyncio.run(audit.verify(DENIAL_CHAIN))
    assert verification.ok


def test_records_carry_metadata_only(monkeypatch: pytest.MonkeyPatch) -> None:
    audit = AuditRepository(InMemoryAuditStore())
    composed = _compose(monkeypatch, audit)
    headers = composed.auth()
    with composed.client() as client:
        client.put(EMERGENCY, json={"reason": "body-marker-xyz"}, headers=headers)
    dumped = json.dumps([r.model_dump(mode="json") for r in _records(audit, DENIAL_CHAIN)])
    token = headers["Authorization"].removeprefix("Bearer ")
    for forbidden in (token, ALICE, "body-marker-xyz", EMERGENCY):
        assert forbidden not in dumped


def test_out_of_membership_domain_goes_to_the_denial_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = AuditRepository(InMemoryAuditStore())
    composed = _compose(monkeypatch, audit)
    with composed.client() as client:
        response = client.get(AUDIT_RECORDS.format(chain="contoso.hr"), headers=composed.auth())
    assert response.status_code == 403
    assert _records(audit, "contoso.hr") == []  # chain names never come from request input
    records = _records(audit, DENIAL_CHAIN)
    assert len(records) == 1
    assert records[0].subject is not None
    assert records[0].subject.target.canonical_id == HR


def test_an_injected_recorder_still_replaces_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    audit = AuditRepository(InMemoryAuditStore())
    denials = RecordingDenials()
    composed = _compose(monkeypatch, audit, denial_recorder=denials)
    assert composed.app.state.authz.denial_recorder is denials
    with composed.client() as client:
        response = client.put(EMERGENCY, json={}, headers=composed.auth())
    assert response.status_code == 403
    assert len(denials.attempts) == 1
    assert _records(audit, DENIAL_CHAIN) == []


def test_without_an_audit_store_a_mutating_denial_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed = _compose(monkeypatch, None)  # data stubbed: no AUDIT_REPOSITORY published
    assert isinstance(composed.app.state.authz.denial_recorder, AuditDenialRecorder)
    with composed.client() as client:
        mutating = client.put(EMERGENCY, json={}, headers=composed.auth())
        safe = client.get(AUDIT_RECORDS.format(chain="contoso.finance"), headers=composed.auth())
    assert mutating.status_code == 503
    assert mutating.json()["reason"] == "audit_write_failed"
    assert safe.status_code == 403  # still denied, never allowed


# --------------------------------------------------------------------------- recorder unit


def _attempt(scope: Any, **values: Any) -> DeniedAttempt:
    fields: dict[str, Any] = {
        "scope": scope,
        "permission": "data.read",
        "reason": "target_out_of_scope",
        "method": "GET",
        "path": "/x",
        "domain_id": None,
        "resource_id": None,
        **values,
    }
    return DeniedAttempt(**fields)


def _alice_scope(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A real derived scope for ALICE, captured through an injected recorder."""
    denials = RecordingDenials()
    composed = _compose(monkeypatch, None, denial_recorder=denials)
    with composed.client() as client:
        client.put(EMERGENCY, json={}, headers=composed.auth())
    return denials.attempts[0].scope


@pytest.mark.parametrize(
    ("values", "target"),
    [
        ({"resource_id": "commercial:contoso:foundry:agent:support-bot"}, "agent"),
        ({"resource_id": "not-a-canonical-id"}, None),
        # A person canonical id carrying a raw object id is dropped, the denial still recorded.
        ({"resource_id": f"commercial:contoso:entra:user:{ALICE}"}, None),
        ({"domain_id": "commercial:contoso:catalog:domain:Bad Name"}, None),
    ],
)
def test_recorder_keeps_only_safe_canonical_targets(
    monkeypatch: pytest.MonkeyPatch, values: dict[str, Any], target: str | None
) -> None:
    scope = _alice_scope(monkeypatch)
    audit = AuditRepository(InMemoryAuditStore())
    recorder = AuditDenialRecorder(lambda: audit)
    asyncio.run(recorder.record_denial(_attempt(scope, **values)))
    (record,) = _records(audit, DENIAL_CHAIN)
    if target is None:
        assert record.subject is None
    else:
        assert record.subject is not None
        assert record.subject.target.entity_type == target


def test_recorder_maps_a_non_code_reason_to_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _alice_scope(monkeypatch)
    audit = AuditRepository(InMemoryAuditStore())
    recorder = AuditDenialRecorder(lambda: audit)
    asyncio.run(recorder.record_denial(_attempt(scope, reason="Not A Code!")))
    (record,) = _records(audit, DENIAL_CHAIN)
    assert record.denial is not None
    assert record.denial.reason == "forbidden"


def test_recorder_without_a_repository_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _alice_scope(monkeypatch)
    recorder = AuditDenialRecorder(lambda: None)
    with pytest.raises(DependencyTransientError):
        asyncio.run(recorder.record_denial(_attempt(scope)))

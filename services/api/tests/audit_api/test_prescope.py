"""PRP-40 item 5: failures before a scope exists (Clarification 3).

Identity known (revoked, policy-store 503, timeout) -> a denied record on
``<customer>.authz-denials`` with a reason code; unauthenticated 401 -> a SIEM signal and a
counter, never a chain record. The HTTP outcome is unchanged in every case.
"""

from __future__ import annotations

import asyncio
import dataclasses
import io
import json
from datetime import datetime
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    FINANCE,
    FakeClock,
    Harness,
    harness,
    policy,
    pseudonymizer,
    role,
)
from neurosphere_api.audit.prescope import NO_SCOPE_HASH, PrescopeAuditor
from neurosphere_api.authz.dependencies import PRESCOPE_AUDIT_ATTRIBUTE
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.audit.siem import SiemExporter, StdoutSink
from neurosphere_core.auth.scope import Role
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    compose,
    configure_auth_env,
)
from runtime_data.data_helpers import (  # pyright: ignore[reportMissingImports]
    builders_with_real_data,
    data_overrides,
)

DENIALS = "contoso.authz-denials"
PROTECTED = "/t/data"


class _Revoked:
    async def is_revoked(self, principal_id: str, issued_at: datetime) -> bool:
        return True


class _SlowRevocation:
    async def is_revoked(self, principal_id: str, issued_at: datetime) -> bool:
        await asyncio.sleep(5)
        return False


def _install(h: Harness, *, stream: io.StringIO | None = None) -> tuple[AuditRepository, Any]:
    repository = AuditRepository(InMemoryAuditStore())
    exporter = SiemExporter([StdoutSink(stream)]) if stream is not None else None
    auditor = PrescopeAuditor(
        repository=lambda: repository,
        pseudonymizer=pseudonymizer(),
        customer_id="contoso",
        exporter=exporter,
    )
    setattr(h.app.state, PRESCOPE_AUDIT_ATTRIBUTE, auditor)
    return repository, auditor


async def _denials(repository: AuditRepository) -> list[Any]:
    tail = await repository.tail(DENIALS)
    if tail is None:
        return []
    return await repository.read_range(DENIALS, start=0, limit=tail.sequence + 1)


async def test_revoked_principal_gets_a_denial_record() -> None:
    h = harness(policy(ALICE, role(Role.ANALYST, FINANCE)), revocation_checker=_Revoked())
    repository, _ = _install(h)
    response = h.client.get(PROTECTED, headers=h.auth(ALICE))
    assert response.status_code == 403
    assert response.json()["reason"] == "principal_revoked"
    (record,) = await _denials(repository)
    assert record.kind == "denied" and record.operation == "authz.derive"
    assert record.denial is not None
    assert (record.denial.code, record.denial.reason) == ("forbidden", "principal_revoked")
    assert record.actor.principal_pseudonym == pseudonymizer().pseudonym(
        "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0", ALICE
    )
    assert record.scope_hash.root == NO_SCOPE_HASH
    assert ALICE not in json.dumps(record.model_dump(mode="json"))


@pytest.mark.parametrize("error", [ConnectionError("down"), RuntimeError("x")])
async def test_policy_store_outage_gets_a_denial_record(error: Exception) -> None:
    h = harness(policy(ALICE, role(Role.ANALYST, FINANCE)))
    h.repo.fail_with(error)
    repository, _ = _install(h)
    response = h.client.get(PROTECTED, headers=h.auth(ALICE))
    assert response.status_code == 503
    (record,) = await _denials(repository)
    assert record.denial is not None
    assert record.denial.code == "dependency_transient"
    assert record.denial.reason == response.json()["reason"]


async def test_timeout_gets_a_denial_record() -> None:
    h = harness(
        policy(ALICE, role(Role.ANALYST, FINANCE)),
        revocation_checker=_SlowRevocation(),
        store_timeout_seconds=30,
    )
    h.app.state.authz = dataclasses.replace(h.app.state.authz, timeout_seconds=0.05)
    repository, _ = _install(h)
    response = h.client.get(PROTECTED, headers=h.auth(ALICE))
    assert response.status_code == 503
    assert response.json()["reason"] == "authz_timeout"
    (record,) = await _denials(repository)
    assert record.denial is not None and record.denial.reason == "authz_timeout"


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-token"}, {"Authorization": "Basic abc"}],
    ids=["missing", "malformed", "wrong_scheme"],
)
async def test_unauthenticated_is_a_siem_signal_and_a_counter_only(
    headers: dict[str, str],
) -> None:
    h = harness(policy(ALICE, role(Role.ANALYST, FINANCE)))
    stream = io.StringIO()
    repository, auditor = _install(h, stream=stream)
    response = h.client.get(PROTECTED, headers=headers)
    assert response.status_code == 401
    reason = response.json()["reason"]
    assert await _denials(repository) == []  # never a chain record
    assert auditor.unauthenticated_counts() == {reason: 1}
    (line,) = stream.getvalue().splitlines()
    event = json.loads(line)
    assert event["event_type"] == "neurosphere.authn.v1"
    assert event["signal"]["reason"] == reason
    assert "not-a-token" not in line


async def test_hook_failure_never_changes_the_outcome() -> None:
    h = harness(policy(ALICE, role(Role.ANALYST, FINANCE)), revocation_checker=_Revoked())
    _install(h)

    class _Broken:
        async def identity_failure(self, *args: Any) -> None:
            raise ConnectionError("audit store down")

        async def unauthenticated(self, *args: Any) -> None:
            raise ConnectionError("siem down")

    setattr(h.app.state, PRESCOPE_AUDIT_ATTRIBUTE, _Broken())
    assert h.client.get(PROTECTED, headers=h.auth(ALICE)).status_code == 403
    assert h.client.get(PROTECTED).status_code == 401


async def test_success_records_nothing() -> None:
    h = harness(policy(ALICE, role(Role.ANALYST, FINANCE)))
    repository, auditor = _install(h)
    assert h.client.get(PROTECTED, headers=h.auth(ALICE)).status_code == 200
    assert await _denials(repository) == []
    assert auditor.unauthenticated_counts() == {}


def test_composition_installs_the_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    clock = FakeClock()
    composed = compose(data_overrides(clock), builders=builders_with_real_data(), clock=clock)
    assert composed.registry.get("audit").state == "ok"
    hook = getattr(composed.app.state, PRESCOPE_AUDIT_ATTRIBUTE, None)
    assert isinstance(hook, PrescopeAuditor)
    assert hook.chain_id.endswith(".authz-denials")
    # A 401 against the composed app is counted, never chained.
    with composed.client() as client:
        assert client.get("/api/v1/audit/denials").status_code == 401
    assert sum(hook.unauthenticated_counts().values()) == 1

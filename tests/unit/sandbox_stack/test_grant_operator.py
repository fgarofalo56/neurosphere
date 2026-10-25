"""PRP-29 item 6: sbx_grant_operator.py against an in-memory policy repository and writer."""

from __future__ import annotations

import asyncio
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from neurosphere_core.auth.scope import PolicyHead, PrincipalPolicy

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "sandbox" / "sbx_grant_operator.py"
CUSTOMER = "synthco"
PRINCIPAL = "commercial:synthco:entra:principal:p-abc123"
DOMAINS = (
    "commercial:synthco:catalog:domain:d-one",
    "commercial:synthco:catalog:domain:d-two",
)
NOW = datetime(2030, 1, 1, tzinfo=UTC)
FAKE_OID = "55555555-5555-4555-8555-555555555555"
FAKE_TENANT = "22222222-2222-4222-8222-222222222222"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sbx_grant_operator_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load()


class MemoryPolicy:
    """Conforms to the PolicyRepository read protocol and the PolicyWriter write protocol."""

    def __init__(self) -> None:
        self.head: PolicyHead | None = None
        self.principals: dict[str, PrincipalPolicy] = {}
        self.writes: list[dict[str, Any]] = []

    async def get_policy_head(self, customer_id: str) -> PolicyHead | None:
        return self.head

    async def get_principal_policy(
        self, customer_id: str, principal_id: str
    ) -> PrincipalPolicy | None:
        return self.principals.get(principal_id)

    async def upsert(self, document: dict[str, Any]) -> None:
        self.writes.append(document)
        if document["doc_type"] == "policy_head":
            self.head = PolicyHead.model_validate(document)
        else:
            policy = PrincipalPolicy.model_validate(document)
            self.principals[policy.principal_id] = policy


def grant(store: MemoryPolicy, role: str = "admin", now: datetime = NOW) -> str:
    return asyncio.run(
        mod.grant_operator(
            store,
            store,
            customer_id=CUSTOMER,
            principal_id=PRINCIPAL,
            role=role,
            domain_ids=DOMAINS,
            now=now,
        )
    )


def test_writes_policy_then_head_and_validates() -> None:
    store = MemoryPolicy()
    assert grant(store) == "created"
    assert [w["doc_type"] for w in store.writes] == ["principal_policy", "policy_head"]
    policy = store.principals[PRINCIPAL]
    assert set(policy.domain_memberships) == set(DOMAINS)
    (assignment,) = policy.role_assignments
    assert assignment.role.value == "admin" and set(assignment.domain_ids) == set(DOMAINS)
    assert assignment.expires_at == NOW + timedelta(days=30)
    assert store.head is not None and store.head.policy_version == "local-1"


def test_second_run_is_unchanged_and_writes_nothing() -> None:
    store = MemoryPolicy()
    grant(store)
    count = len(store.writes)
    assert grant(store, now=NOW + timedelta(days=1)) == "unchanged"
    assert len(store.writes) == count


def test_changed_role_bumps_version_and_keeps_other_assignments() -> None:
    store = MemoryPolicy()
    grant(store, "viewer")
    assert store.principals[PRINCIPAL].role_assignments[0].expires_at is None
    assert grant(store, "viewer") == "unchanged"
    assert grant(store, "analyst") == "updated"
    assert store.head is not None and store.head.policy_version == "local-2"
    roles = {a.assignment_id: a.role.value for a in store.principals[PRINCIPAL].role_assignments}
    assert roles == {"operator-viewer": "viewer", "operator-analyst": "analyst"}


def test_privileged_grant_renews_near_expiry() -> None:
    store = MemoryPolicy()
    grant(store)
    later = NOW + timedelta(days=25)
    assert grant(store, now=later) == "renewed"
    assert store.principals[PRINCIPAL].role_assignments[0].expires_at == later + timedelta(days=30)


def test_refuses_non_loopback_endpoint(capsys: pytest.CaptureFixture[str]) -> None:
    env = {"NS_COSMOS_ENDPOINT": "https://acct.documents.azure.com:443/"}
    code = mod.main(
        ["--object-id", FAKE_OID, "--role", "admin", "--tenant-id", FAKE_TENANT], env=env
    )
    assert code == mod.EXIT_REFUSED
    assert "REFUSED" in capsys.readouterr().err


def test_refuses_bad_ids_before_connecting() -> None:
    env = {"NS_COSMOS_ENDPOINT": "http://127.0.0.1:8081"}
    assert mod.main(["--object-id", "not-a-guid", "--role", "admin"], env=env) != 0


def test_next_version() -> None:
    assert mod.next_version(None) == "local-1"
    assert mod.next_version("local-9") == "local-10"
    assert mod.next_version("v7") == "local-1"
